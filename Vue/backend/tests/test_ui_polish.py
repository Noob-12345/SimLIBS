from dataclasses import replace
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit
import numpy as np
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings,UI_ROOT
from simlibs_ui.offline_engine import local_simulate,E,K,C,U_MASS
from simlibs_ui.mode_engine import client_simulate
from simlibs_ui.adapter import simulate,source_module
from simlibs_ui.batch_template import parse_template
from tests.test_adapter import CSV
sys.path.insert(0,str(UI_ROOT/'web'))
from backend_api import CommonParams,SingleRequest,BatchRequest,ScanRequest,ApiError
from real_backend import RealBackend

class PolishTests(unittest.TestCase):
    def test_linked_doppler_width_changes_manual_and_legacy_stay_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            text='Intensity,Wavelength,Aki,Energy,c,t,j,g\n1,5000,1,0,,,0,1\n1,5000,1,20000,,,0,1\n'
            for stage in ('I','II'):(root/('Fe'+stage+'.csv')).write_text(text)
            (root/'simlibs-atomic-metadata.json').write_text(json.dumps({'elements':{'Fe':{'atomic_mass_u':55.845,'first_ionization_eV':7.9024}}}))
            s=replace(Settings(),line_database=str(root))
            p=replace(Parameters(),webscraping='local',mode_version=2,broadening='local',broaden_convention='physics',elements=('Fe',),
                      low_w=499.96,upper_w=500.04,broaden_grid_step=.00005,resolution=1_000_000,max_ion_charge=0,local_temperature_mode='linked').validated()
            widths=[]
            for te in (1,2):
                frames,origin=local_simulate(replace(p,Te=te),s);y=frames['raw']['intensity'].to_numpy();x=frames['raw']['wavelength'].to_numpy()
                self.assertAlmostEqual(origin['effective_heavy_temperature_K'],te*E/K)
                self.assertEqual(origin['thermal_temperature_mode'],'linked')
                expected=np.sqrt((500/p.resolution)**2+(500*np.sqrt(8*E*te*np.log(2)/(55.845*U_MASS*C*C)))**2)
                half=x[y>=y.max()/2];width=half[-1]-half[0];self.assertAlmostEqual(width,expected,delta=.00011);widths.append(width)
            self.assertGreater(widths[1],widths[0]*1.35)
            manual=replace(p,local_temperature_mode='manual',local_temperature_K=8000)
            first,_=local_simulate(manual,s);second,_=local_simulate(replace(manual,Te=2),s)
            np.testing.assert_allclose(first['raw']['intensity']/first['raw']['intensity'].max(),second['raw']['intensity']/second['raw']['intensity'].max(),rtol=1e-12,atol=1e-12)
            legacy=Parameters.from_dict({k:v for k,v in replace(manual,local_temperature_K=0).to_dict().items() if k!='local_temperature_mode'})
            self.assertEqual(legacy.local_temperature_mode,'manual');self.assertEqual(legacy.effective_temperature_K,0)
            with self.assertRaises(ValueError):replace(p,Te=1e308).validated()

    def test_api_absent_temperature_mode_legacy_manual_new_defaults_linked(self):
        raw={'te':1,'ne':1e17,'resolution':1000,'low_w':240,'up_w':260,'max_ion_charge':2,'mode':'local','mode_version':2}
        self.assertEqual(CommonParams.from_api(raw).local_temperature_mode,'manual')
        p=CommonParams.from_api(dict(raw,local_temperature_mode='linked'));self.assertEqual(p.local_temperature_mode,'linked')
        backend=RealBackend.__new__(RealBackend);backend._settings=Settings();backend._lock=__import__('threading').Lock();backend._jobs={}
        self.assertEqual(backend.default_params()['params']['local_temperature_mode'],'linked')
        for extra in ({'local_temperature_mode':'bad'},{'local_temperature_mode':'linked','te':1e308},{'intensity_scale':'energy'}):
            with self.assertRaises(ApiError):CommonParams.from_api(dict(raw,**extra))
        self.assertFalse(CommonParams.from_api(dict(raw,resample=False,resample_step='bad')).resample)

    def test_template_explicit_temperature_is_manual_and_energy_forwarded(self):
        p=replace(Parameters(),webscraping='local',mode_version=2,broadening='local',broaden_convention='physics',
                  elements=('Fe',),local_temperature_mode='linked')
        entry=parse_template('name,Fe,T_h[K],Te[eV]\na,100,8000,2\n',p)['entries'][0]['parameters']
        self.assertEqual(entry['local_temperature_mode'],'manual');self.assertEqual(entry['local_temperature_K'],8000)
        with self.assertRaisesRegex(ValueError,'冲突'):parse_template('name,Fe,T_h[K],doppler_mode\na,100,8000,linked\n',p)
        online=replace(p,webscraping='client',broaden_convention='nist')
        entry=parse_template('name,H,intensity_scale\na,100,energy\n',online)['entries'][0]['parameters']
        self.assertEqual(entry['intensity_scale'],'energy')

    def test_client_real_transport_parameters_two_fluxes_never_reads_user_library(self):
        def getter(url,**kwargs):
            query=parse_qs(urlsplit(url).query);number=query['int_scale'][0];self.assertTrue(kwargs['verify'])
            weight=17 if number=='1' else 53
            return Mock(text=f"<script>var dataSticksArray=[[{{label:'Wavelength (nm)'}},{{label:'H I'}}],[655,{weight}]];</script>")
        s=replace(Settings(),line_database=r'Z:\intentionally-missing-user-library')
        results=[]
        for scale,number in (('photon','2'),('energy','1')):
            p=replace(Parameters(),webscraping='client',mode_version=2,broadening='local',intensity_scale=scale)
            with patch('simlibs_ui.offline_database.load_library',side_effect=AssertionError('client must use NIST')),patch('selenium.webdriver.Chrome',side_effect=AssertionError('browser')):
                frames,origin=client_simulate(p,s,request_get=getter)
            self.assertEqual(parse_qs(urlsplit(origin['nist_url']).query)['int_scale'],[number]);self.assertEqual(origin['intensity_scale'],scale)
            results.append(frames['raw']['intensity'].max())
        self.assertAlmostEqual(results[1]/results[0],17/53)

    def test_server_js_request_two_fluxes_reads_response_without_rescaling(self):
        module=source_module(Settings().source)
        for scale,number in (('photon','2'),('energy','1')):
            driver=Mock();driver.window_handles=['main','csv'];driver.page_source='<pre>'+CSV+'</pre>'
            driver.get_log.side_effect=lambda kind:[{'message':json.dumps({'message':{'method':'Network.responseReceived','params':{'requestId':str(i),'response':{'url':url,'status':200}}}})} for i,url in enumerate((driver.get.call_args.args[0],'https://physics.nist.gov/PhysRefData/ASD/LIBS/js/saha_lte.js'))]
            driver.execute_cdp_cmd.return_value={'body':'fixture transport response','base64Encoded':False}
            driver.find_element.return_value.is_displayed.return_value=True;driver.find_element.return_value.is_enabled.return_value=True
            driver.execute_script.return_value={'runtime_r':1000,'effective_r':1000,'requested_r':1000,'title':'R 1000','rows':3}
            p=replace(Parameters(),webscraping='server',mode_version=2,intensity_scale=scale)
            with patch('simlibs_ui.adapter.resolve_driver',return_value=('mock.exe','154')),patch.object(module.webdriver,'Chrome',return_value=driver):
                frames,origin=simulate(p,Settings())
            self.assertEqual(parse_qs(urlsplit(driver.get.call_args.args[0]).query)['int_scale'],[number])
            self.assertEqual(origin['intensity_scale'],scale);self.assertEqual(frames['raw']['intensity'].tolist(),[0,2,0])
            self.assertTrue(driver.execute_script.called);driver.quit.assert_called_once()

if __name__=='__main__':unittest.main()
