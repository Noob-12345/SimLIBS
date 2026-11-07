import json,sys,tempfile,unittest,zipfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
import pandas as pd
from simlibs_ui.models import Parameters,BatchSpec
from simlibs_ui.settings import Settings,UI_ROOT
from simlibs_ui.offline_engine import local_simulate
from simlibs_ui.batch_random import generate_plan
from simlibs_ui.batch_template import parse_template
from simlibs_ui.operations import batch
from simlibs_ui.storage import read_manifest,save_result
sys.path.insert(0,str(UI_ROOT/'web'))
from backend_api import BatchRequest,CommonParams,ApiError

def params(**kwargs):return replace(Parameters(),**dict(dict(webscraping='local',mode_version=2,broadening='local',broaden_convention='physics',
       elements=('Fe',),low_w=240,upper_w=260,broaden_grid_step=.1,local_broadening_enabled=False),**kwargs)).validated()

class UnbroadenedTests(unittest.TestCase):
    def test_exact_weak_coincident_lines_conservative_grid_no_hidden_widths_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);head='Intensity,Wavelength,Aki,Energy,c,t,j,g\n'
            (root/'FeI.csv').write_text(head+'1,5000,1,0,,,0,1\n1,5000,1,20000,,,0,1\n9,5000.1,1e-10,0,,,0,1\n9,5000.1,1e-10,19999.600008,,,0,1\n')
            (root/'FeII.csv').write_text(head+'1,5000,2,0,,,0,1\n1,5000,2,20000,,,0,1\n')
            (root/'simlibs-atomic-metadata.json').write_text(json.dumps({'elements':{'Fe':{'atomic_mass_u':55.845,'first_ionization_eV':7.9}}}))
            settings=replace(Settings(),line_database=str(root));p=params(low_w=499.95,upper_w=500.05,broaden_grid_step=.025)
            with patch('requests.get',side_effect=AssertionError('network')),patch('selenium.webdriver.Chrome',side_effect=AssertionError('Chrome')):
                frames,origin=local_simulate(p,settings)
                other,_=local_simulate(replace(p,resolution=999999,local_temperature_mode='linked',local_temperature_K=1e6,local_gaussian_nm=10,local_lorentz_nm=10),settings)
            for key in frames:pd.testing.assert_frame_equal(frames[key],other[key])
            raw=frames['raw'];self.assertIn(500.,raw['wavelength'].tolist());self.assertIn(5000.1*.1,raw['wavelength'].tolist())
            self.assertEqual(np.count_nonzero(raw['intensity']),2);self.assertEqual(np.count_nonzero(frames['interpolated']['intensity']),1)
            self.assertAlmostEqual(raw['intensity'].sum(),frames['interpolated']['intensity'].sum(),delta=raw['intensity'].sum()*1e-14)
            for key in ('ion','ion_interpolated'):
                df=frames[key];np.testing.assert_allclose(df.drop(columns=['Wavelength (nm)','Sum(calc)']).sum(axis=1),df['Sum(calc)'])
            self.assertIsNone(origin['actual_resolution']);self.assertIsNone(origin['effective_heavy_temperature_K']);self.assertEqual(origin['spectrum_style'],'sticks')
            from simlibs_ui.plotting import figure_for
            m=read_manifest(save_result(root/'result',frames,origin));figure=figure_for(m,'raw','lines','#2563eb',False)
            self.assertFalse(figure.axes[0].lines);self.assertTrue(figure.axes[0].collections);figure.clear()
            broadened,_=local_simulate(replace(p,local_broadening_enabled=True),settings)
            self.assertFalse(np.array_equal(frames['interpolated']['intensity'],broadened['interpolated']['intensity']))
    def test_missing_switch_is_legacy_broadened_and_generation_structure_errors_400(self):
        p=params();self.assertTrue(Parameters.from_dict({k:v for k,v in p.to_dict().items() if k!='local_broadening_enabled'}).local_broadening_enabled)
        raw={'mode':'local','mode_version':2,'te':1,'ne':1e17,'resolution':1000,'low_w':240,'up_w':260,'max_ion_charge':2}
        self.assertTrue(CommonParams.from_api(raw).local_broadening_enabled)
        for rule in ({'kind':'random','te':None,'concentrations':[{'el':'Fe','fixed':100}]},
                     {'kind':'random','ne':1,'concentrations':[{'el':'Fe','fixed':100}]},
                     {'kind':'random','concentrations':[1]}):
            with self.subTest(rule=rule),self.assertRaises(ApiError) as caught:BatchRequest.from_api({'params':raw,'n_samples':3,'generation':rule})
            self.assertEqual(caught.exception.status,400)

class RandomTests(unittest.TestCase):
    def rule(self):return {'kind':'random','te':{'enabled':True,'min':1.1,'max':1.3},'ne':{'enabled':True,'min':1.23456789123e17,'max':2e17},
                         'concentrations':[{'el':'Fe','enabled':False,'fixed':20},{'el':'Al','enabled':True,'min':30,'max':50},{'el':'Ca','enabled':True,'min':30,'max':50}]}
    def test_seed_bounds_fixed_values_and_not_joint_uniform(self):
        a=generate_plan(params(),30,42,self.rule());self.assertEqual(a,generate_plan(params(),30,42,self.rule()))
        self.assertNotEqual(a['entries'],generate_plan(params(),30,43,self.rule())['entries'])
        for entry in a['entries']:
            p=entry['parameters'];self.assertEqual(p['percentages'][0],20);self.assertAlmostEqual(sum(p['percentages']),100)
            for pct in p['percentages'][1:]:self.assertGreaterEqual(pct,30);self.assertLessEqual(pct,50)
            self.assertGreaterEqual(p['Te'],1.1);self.assertLessEqual(p['Te'],1.3);self.assertGreaterEqual(p['Ne'],1.23456789123e17);self.assertLessEqual(p['Ne'],2e17)
        self.assertIn('not joint uniform',a['distribution'])
    def test_disabled_invalid_drafts_ignored_infeasible_nan_and_cancel_reject(self):
        rule={'kind':'random','te':{'enabled':False,'min':float('nan')},'ne':{'enabled':False,'max':'bad'},'concentrations':[{'el':'Fe','enabled':False,'fixed':100,'min':'bad'}]}
        plan=generate_plan(params(),2,4,rule);json.dumps(plan,allow_nan=False);self.assertEqual(plan['entries'][0]['parameters']['Ne'],1e17)
        for specs in ([{'el':'Fe','enabled':False,'fixed':80},{'el':'Al','enabled':True,'min':30,'max':40}],
                      [{'el':'Fe','enabled':True,'min':0,'max':99}],
                      [{'el':'Fe','enabled':True,'min':float('nan'),'max':100}]):
            with self.assertRaises(ValueError):generate_plan(params(),2,4,dict(rule,concentrations=specs))
        with self.assertRaises(InterruptedError):generate_plan(params(),2,4,self.rule(),cancelled=lambda:True)
        with self.assertRaises(ValueError):generate_plan(params(broaden_grid_step=.001),5000,4,self.rule())
    def test_saved_random_plan_cancel_resume_csv_labels_and_template_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=params(local_temperature_mode='linked');calls=[];planned=generate_plan(p,3,42,self.rule())
            def actual(p,s):calls.append(p.to_dict());return local_simulate(p,s)
            with patch('requests.get',side_effect=AssertionError('network')):
                first=batch(p,Settings(),BatchSpec(size=3,batch_size=2),pd.DataFrame(),root/'first',lambda *a,**k:None,lambda:len(calls)>=2,actual,planned=planned)
                result=batch(p,Settings(),BatchSpec(),pd.DataFrame(),root/'resume',lambda *a,**k:None,lambda:False,actual,resume_checkpoint=str(root/'first/checkpoint.json'))
            self.assertEqual(len(calls),3);m=read_manifest(result);self.assertEqual(m['samples'][:2],read_manifest(first)['samples'])
            csv=pd.read_csv(m['actual_parameters'],float_precision='round_trip');self.assertEqual(len(csv),3)
            for index,row in csv.iterrows():
                actual_params=read_manifest(m['samples'][index])['origin']['parameters'];self.assertEqual(row['index'],index+1)
                self.assertEqual(row['Te[eV]'],actual_params['Te']);self.assertEqual(row['Ne[cm^-3]'],actual_params['Ne'])
                for el,pct in zip(actual_params['elements'],actual_params['percentages']):self.assertEqual(row[el+'_at%'],pct)
            reused=parse_template(Path(m['template_csv']).read_text(encoding='utf-8-sig'),p)
            for original,again in zip(planned['entries'],reused['entries']):
                self.assertEqual(dict(zip(original['parameters']['elements'],original['parameters']['percentages'])),dict(zip(again['parameters']['elements'],again['parameters']['percentages'])))
            with zipfile.ZipFile(m['training_package']['archive']) as archive:
                self.assertIn('actual_parameters.csv',archive.namelist());self.assertIn('template.csv',archive.namelist())
                metadata=json.loads(archive.read('package-manifest.json'));seen=0
                for part in metadata['packages']:
                    labels=pd.read_csv(archive.open(part['contents']),float_precision='round_trip')
                    spectra=np.loadtxt(archive.open(part['spectra']),delimiter=',',ndmin=2)
                    self.assertEqual(len(labels),part['sample_count']);self.assertEqual(len(spectra),2*len(labels))
                    for index,label in labels.iterrows():
                        sample=read_manifest(m['samples'][seen]);p_actual=sample['origin']['parameters'];frame=pd.read_csv(sample['files']['interpolated'],float_precision='round_trip')
                        np.testing.assert_array_equal(spectra[2*index],frame['wavelength']);np.testing.assert_array_equal(spectra[2*index+1],frame['intensity'])
                        actual_by_el=dict(zip(p_actual['elements'],p_actual['percentages']))
                        for el,value in label.items():self.assertEqual(value,actual_by_el.get(el,0))
                        self.assertEqual(metadata['samples'][seen]['origin']['parameters']['Te'],p_actual['Te']);self.assertEqual(metadata['samples'][seen]['origin']['parameters']['Ne'],p_actual['Ne']);seen+=1
                self.assertEqual(seen,3)
            self.assertEqual(m['training_package']['sample_counts'],[2,1])
if __name__=='__main__':unittest.main()
