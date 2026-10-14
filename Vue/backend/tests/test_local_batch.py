from dataclasses import replace
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from simlibs_ui.models import Parameters,BatchSpec,ScanSpec
from simlibs_ui.settings import Settings,UI_ROOT
from simlibs_ui.offline_database import parse_file,load_library,capabilities
from simlibs_ui.offline_engine import local_simulate,partition
from simlibs_ui.batch_template import parse_template
from simlibs_ui.operations import batch,scan
from simlibs_ui.storage import read_manifest


def params(**values):
    return replace(Parameters(),**dict(dict(webscraping='local',mode_version=2,broadening='local',broaden_convention='physics',
       elements=('Fe','Al'),percentages=(50,50),low_w=200,upper_w=500,broaden_grid_step=.02),**values)).validated()


class LocalPhysicsTests(unittest.TestCase):
    def test_actual_formats_missing_aki_and_unique_levels(self):
        root=Path(Settings().line_database)
        fe=parse_file(root/'FeI.csv');ce=parse_file(root/'CeII.csv');na=parse_file(root/'NaI.csv');gd=parse_file(root/'GdII.csv')
        self.assertEqual(fe['transitions'][0]['rows'],[3,4]);self.assertEqual(ce['transitions'][0]['rows'],[2,3])
        self.assertAlmostEqual(fe['transitions'][0]['wavelength_nm'],248.32708)
        self.assertAlmostEqual(fe['transitions'][0]['Aki_s']/1e8,4.81)
        self.assertTrue(na['transitions']);self.assertTrue(gd['levels']);self.assertTrue(gd['excluded'])
        self.assertFalse(gd['transitions'])
        self.assertEqual(len({(v['energy_cm'],v['g']) for v in fe['levels']}),len(fe['levels']))
        self.assertEqual(capabilities(root)['csv_count'],62)

    def test_invalid_physical_values_reject_but_missing_aki_does_not_invent(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'FeI.csv'
            for value in ('NaN','Inf','-1'):
                path.write_text('Intensity,Wavelength,Aki,Energy,Configurations,Terms,J,g\n1,2483,'+value+',0,,,4,9\n1,2483,'+value+',40273.86,,,5,11\n')
                with self.assertRaises(ValueError):parse_file(path)
            path.write_text('Unnamed: 0,Unnamed: 1,(108s-1),Levels (cm -1 ),c,t,j,Unnamed: 7\n1,2483,,0,,,4,9\n1,2483,,40273.86,,,5,11\n')
            result=parse_file(path);self.assertFalse(result['transitions']);self.assertEqual(len(result['levels']),2)

    def test_local_zero_network_ne_te_and_width_have_real_effects(self):
        with patch('requests.get',side_effect=AssertionError('network')),patch('socket.create_connection',side_effect=AssertionError('tcp')),patch('selenium.webdriver.Chrome',side_effect=AssertionError('browser')):
            first,origin=local_simulate(params(),Settings())
            second,other=local_simulate(params(Te=1.5,Ne=2e17),Settings())
            wider,_=local_simulate(params(local_gaussian_nm=.4,local_lorentz_nm=.1,local_temperature_K=5000),Settings())
        self.assertFalse(origin['network_used']);self.assertEqual(len(first['raw']),15001)
        self.assertFalse(np.array_equal(first['raw']['intensity'],second['raw']['intensity']))
        self.assertFalse(np.array_equal(first['raw']['intensity'],wider['raw']['intensity']))
        self.assertAlmostEqual(sum(origin['ion_fractions']['Fe'].values()),1)
        ions=first['ion'];np.testing.assert_allclose(ions.drop(columns=['Wavelength (nm)','Sum(calc)']).sum(axis=1),ions['Sum(calc)'],rtol=1e-14)

    def test_missing_element_rejected_no_fallback_and_max_limits(self):
        with self.assertRaisesRegex(ValueError,'不支持'):local_simulate(params(elements=('H',),percentages=(100,)),Settings())
        for charge in (-1,3,5):
            with self.assertRaises(ValueError):params(max_ion_charge=charge)

    def test_single_line_photon_area_fwhm_and_outside_center_wings(self):
        from simlibs_ui.offline_engine import ion_fractions,CM_TO_EV
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            text='Intensity,Wavelength,Aki,Energy,Configurations,Terms,J,g\n999,5000,1,0,,,0,1\n999,5000,1,20000,,,0,1\n'
            for stage in ('I','II'):(root/('Fe'+stage+'.csv')).write_text(text)
            metadata={'elements':{'Fe':{'atomic_mass_u':55.845,'first_ionization_eV':7.9024}}}
            (root/'simlibs-atomic-metadata.json').write_text(json.dumps(metadata))
            setting=replace(Settings(),line_database=str(root))
            p=params(elements=('Fe',),percentages=(100,),low_w=498,upper_w=502,broaden_grid_step=.001,max_ion_charge=0)
            frames,origin=local_simulate(p,setting);x=frames['raw']['wavelength'].to_numpy();y=frames['raw']['intensity'].to_numpy()
            u=1+np.exp(-20000*CM_TO_EV/p.Te)
            expected=origin['ion_fractions']['Fe']['I']*np.exp(-20000*CM_TO_EV/p.Te)/u*1e8
            self.assertAlmostEqual(np.trapezoid(y,x)/expected,1,places=7)
            half=x[y>=y.max()/2];self.assertAlmostEqual(half[-1]-half[0],.5,delta=.002)
            for lorentz in (0,.1):
                wing,_=local_simulate(replace(p,low_w=500.1,upper_w=500.2,local_lorentz_nm=lorentz),setting)
                self.assertTrue((wing['raw']['intensity']>0).all())


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name);self.calls=[]
        self.p=params(low_w=240,upper_w=260,broaden_grid_step=.1)
        self.pool=pd.DataFrame({'Fe':[100,50],'Al':[0,50],'name':['Fe','Mix']})
    def fake(self,p,s):
        self.calls.append(p.to_dict());frame=pd.DataFrame({'wavelength':[240.,250.,260.],'intensity':[0,p.Te,0]})
        return {'raw':frame,'interpolated':frame},{'kind':'simulation','parameters':p.to_dict()}
    def emit(self,*args,**kwargs):pass
    def test_order_repeats_and_ne_te_are_elements_not_parameters(self):
        text='name,Fe,Al,Te[eV],Ne[cm^-3],R\na,100,0,1.1,1.2e17,1000\nb,0,100,1.2,1.3e17,2000\n'
        plan=parse_template(text,self.p,2)
        self.assertEqual([e['name'] for e in plan['entries']],['a','a','b','b'])
        with patch('requests.get',side_effect=AssertionError('network')):
            path=batch(self.p,Settings(),BatchSpec(size=4,batch_size=3),self.pool,self.path/'ordered',self.emit,lambda:False,self.fake,planned=plan)
        self.assertEqual([p['Te'] for p in self.calls],[1.1,1.1,1.2,1.2])
        self.assertEqual(read_manifest(path)['training_package']['sample_counts'],[3,1])
        online=replace(self.p,webscraping='client',elements=('Ne','Te'),percentages=(50,50))
        row=parse_template('name,Ne,Te\ngas,60,40\n',online)['entries'][0]
        self.assertEqual(row['parameters']['elements'],('Ne','Te'));self.assertEqual(row['parameters']['Ne'],self.p.Ne)
    def test_fail_after_two_resume_reuses_exact_plan_without_recalculation(self):
        def fail(p,s):
            if len(self.calls)==2:raise RuntimeError('controlled third failure')
            return self.fake(p,s)
        with self.assertRaises(RuntimeError):batch(self.p,Settings(),BatchSpec(size=3,batch_size=2),self.pool,self.path/'original',self.emit,lambda:False,fail)
        self.assertEqual(len(self.calls),2)
        cp=self.path/'original'/'checkpoint.json'
        result=batch(self.p,Settings(),BatchSpec(),self.pool,self.path/'resume',self.emit,lambda:False,self.fake,resume_checkpoint=str(cp))
        self.assertEqual(len(self.calls),3)
        m=read_manifest(result);self.assertEqual(m['completed'],3);self.assertEqual(m['training_package']['sample_counts'],[2,1])
        self.assertTrue(Path(m['samples'][0]).is_relative_to(self.path/'original'))
    def test_cancel_then_resume_and_packaging_failure_only_repacks(self):
        p=batch(self.p,Settings(),BatchSpec(size=3),self.pool,self.path/'cancelled',self.emit,lambda:len(self.calls)>=2,self.fake)
        self.assertTrue(read_manifest(p)['partial'])
        with patch('simlibs_ui.training.build_training_package',side_effect=RuntimeError('packing failure')),self.assertRaises(RuntimeError):
            batch(self.p,Settings(),BatchSpec(),self.pool,self.path/'packing',self.emit,lambda:False,self.fake,resume_checkpoint=str(self.path/'cancelled'/'checkpoint.json'))
        self.assertEqual(len(self.calls),3)
        batch(self.p,Settings(),BatchSpec(),self.pool,self.path/'repack',self.emit,lambda:False,self.fake,resume_checkpoint=str(self.path/'packing'/'checkpoint.json'))
        self.assertEqual(len(self.calls),3)
    def test_tamper_samples_or_plan_rejected_before_reuse(self):
        result=batch(self.p,Settings(),BatchSpec(size=3),self.pool,self.path/'original',self.emit,lambda:len(self.calls)>=1,self.fake)
        m=read_manifest(result);sample=read_manifest(m['samples'][0]);Path(sample['files']['raw']).write_text('tampered')
        with self.assertRaises(ValueError):batch(self.p,Settings(),BatchSpec(),self.pool,self.path/'bad',self.emit,lambda:False,self.fake,resume_checkpoint=str(self.path/'original'/'checkpoint.json'))

    def test_real_local_diagnostics_survive_failure_new_process_resume(self):
        import subprocess,sys,hashlib
        plan=parse_template('name,Fe,Al,Te[eV]\na,100,0,1\nb,50,50,1.2\nc,0,100,1.4\n',self.p)
        calls=[]
        def actual(p,s):
            calls.append(p.to_dict())
            if len(calls)==3:raise RuntimeError('controlled third failure')
            return local_simulate(p,s)
        original=self.path/'real-original'
        with self.assertRaises(RuntimeError):batch(self.p,Settings(),BatchSpec(size=3,batch_size=2),self.pool,original,self.emit,lambda:False,actual,planned=plan)
        cp=read_manifest(original/'checkpoint.json');before={file:sha for row in cp['samples'] for file,sha in row['hashes'].items()}
        tables=[read_manifest(row['manifest'])['origin']['line_table'] for row in cp['samples']]
        self.assertEqual(len(set(tables)),2)
        code="from simlibs_ui.worker import execute;import json,sys;print(execute(json.loads(sys.argv[1]),lambda *a,**k:None,lambda:False))"
        request={'kind':'resume','settings':Settings().to_dict(),'directory':str(self.path/'real-resume'),'checkpoint_path':str(original/'checkpoint.json')}
        process=subprocess.run([sys.executable,'-c',code,json.dumps(request)],cwd=UI_ROOT,capture_output=True,text=True,timeout=60)
        self.assertEqual(process.returncode,0,process.stderr)
        result=read_manifest(self.path/'real-resume'/'result'/'manifest.json')
        self.assertEqual(result['samples'][:2],[row['manifest'] for row in cp['samples']]);self.assertEqual(result['completed'],3)
        for file,sha in before.items():self.assertEqual(hashlib.sha256(Path(file).read_bytes()).hexdigest(),sha)
        self.assertTrue(Path(read_manifest(result['samples'][2])['origin']['line_table']).is_relative_to(self.path/'real-resume'))

    def test_template_invalid_values_and_inconsistent_grid_rejected(self):
        for text in ('name,Fe,Al\na,100,\n','name,Fe\na,NaN\n','name,Fe\na,99\n','name,Fe,R\na,100,NaN\n',
                     'name,Fe,grid_step[nm]\na,100,.1\nb,100,.2\n'):
            with self.subTest(text=text),self.assertRaises(ValueError):parse_template(text,self.p)

    def test_repeated_failure_changed_library_and_plan_parameters_reject(self):
        from simlibs_ui.batch_pipeline import load_checkpoint
        result=batch(self.p,Settings(),BatchSpec(size=3),self.pool,self.path/'first',self.emit,lambda:len(self.calls)>=2,self.fake)
        def fail(*args):raise RuntimeError('repeat failure')
        with self.assertRaises(RuntimeError):batch(self.p,Settings(),BatchSpec(),self.pool,self.path/'again',self.emit,lambda:False,fail,resume_checkpoint=str(self.path/'first'/'checkpoint.json'))
        self.assertEqual(len(self.calls),2)
        load_checkpoint(self.path/'again'/'checkpoint.json',Settings())
        import shutil
        shutil.copyfile(Path(Settings().line_database)/'FeI.csv',self.path/'FeI.csv')
        with self.assertRaisesRegex(ValueError,'版本'):load_checkpoint(self.path/'again'/'checkpoint.json',replace(Settings(),line_database=str(self.path)))
        plan=read_manifest(self.path/'again'/'plan.json');plan['entries'][0]['parameters']['Te']=9
        (self.path/'again'/'plan.json').write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError,'哈希'):load_checkpoint(self.path/'again'/'checkpoint.json',Settings())

    def test_resume_api_ownership_old_task_and_concurrency_guards(self):
        import sys,threading
        sys.path.insert(0,str(UI_ROOT/'web'))
        from real_backend import RealBackend
        from backend_api import ApiError
        jid='a'*32
        batch(self.p,Settings(),BatchSpec(size=3),self.pool,self.path/'.jobs'/jid/'result',self.emit,lambda:len(self.calls)>=2,self.fake)
        backend=RealBackend.__new__(RealBackend);backend._lock=threading.Lock();backend._jobs={jid:{'status':'running'}}
        backend._settings=replace(Settings(),output=str(self.path));backend._settings_path=self.path/'settings.json'
        with self.assertRaises(ApiError):backend.resume(jid)
        backend._jobs[jid]['status']='failed';backend._resume_active={jid:'active'}
        with self.assertRaises(ApiError):backend.resume(jid)
        backend._resume_active={};backend._jobs['b'*32]={'status':'failed'}
        with self.assertRaises(ApiError):backend.resume('b'*32)
        self.assertEqual(len(self.calls),2)


if __name__=='__main__':unittest.main()
