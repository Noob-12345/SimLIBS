"""Startup rejects broken local resources before any worker/network is used."""
from dataclasses import replace
import json,shutil,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from simlibs_ui.settings import Settings,UI_ROOT
sys.path.insert(0,str(UI_ROOT/'web'))
from backend_api import SingleRequest,BatchRequest,ScanRequest,ApiError
from real_backend import RealBackend

class LocalPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        source=Path(Settings().line_database)
        for name in ('FeI.csv','FeII.csv','simlibs-atomic-metadata.json'):shutil.copyfile(source/name,self.root/name)
        self.backend=RealBackend.__new__(RealBackend);self.backend._lock=threading.Lock();self.backend._jobs={}
        self.backend._settings=replace(Settings(),line_database=str(self.root));self.backend._launch=Mock(return_value='valid')
        self.p={'te':1,'ne':1e17,'resolution':1000,'low_w':240,'up_w':260,'max_ion_charge':2,'mode':'local','mode_version':2}
    def single(self,comp=None):return SingleRequest.from_api({'params':self.p,'composition':comp or [{'el':'Fe','pct':100}]})
    def batch(self,template):return BatchRequest.from_api({'params':self.p,'template_csv':template})
    def scan(self,comp=None):return ScanRequest.from_api({'params':self.p,'composition':comp or [{'el':'Fe','pct':100}],'axis':'te','start':1,'end':1.1,'frames':2})
    def reject(self):
        requests=[(self.backend.start_single,self.single()),(self.backend.start_batch,self.batch('name,Fe\na,100\n')),
                  (self.backend.start_scan,self.scan())]
        with patch('socket.create_connection',side_effect=AssertionError('network')),patch('requests.get',side_effect=AssertionError('HTTP')):
            for start,request in requests:
                with self.subTest(start=start.__name__),self.assertRaises(ApiError) as error:start(request)
                self.assertEqual(error.exception.status,400)
        self.backend._launch.assert_not_called()
    def test_missing_fe_stage_rejects_all_operations_zero_spawn(self):
        (self.root/'FeI.csv').unlink();self.reject()
    def test_missing_empty_directory_status_and_params_remain_usable(self):
        for directory in (self.root/'missing',self.root/'empty'):
            if directory.name=='empty':directory.mkdir()
            self.backend._settings=replace(self.backend._settings,line_database=str(directory))
            self.reject()
            status=self.backend.engine_status('local');params=self.backend.default_params()
            self.assertEqual(status['local']['elements'],[]);self.assertTrue(status['local']['error'])
            self.assertEqual(params['params']['mode'],'local')
    def test_no_effective_lines_and_corrupt_file_reject(self):
        for value in ('','NaN'):
            text='Intensity,Wavelength,Aki,Energy,c,t,j,g\n1,5000,'+value+',0,,,0,1\n1,5000,'+value+',20000,,,0,1\n'
            for stage in ('I','II'):(self.root/('Fe'+stage+'.csv')).write_text(text)
            self.reject()
    def test_bad_atomic_metadata_rejects_before_spawn(self):
        original=json.loads((self.root/'simlibs-atomic-metadata.json').read_text())
        for key,value in (('atomic_mass_u',0),('first_ionization_eV',float('nan')),('source_url',''),('response_sha256','invalid')):
            data=json.loads(json.dumps(original));data['elements']['Fe'][key]=value
            (self.root/'simlibs-atomic-metadata.json').write_text(json.dumps(data));self.reject()
        (self.root/'simlibs-atomic-metadata.json').write_text('{broken');self.reject()
    def test_unknown_positive_elements_reject_but_zero_is_preserved(self):
        positive=[{'el':'Fe','pct':99},{'el':'H','pct':1}]
        for start,request in ((self.backend.start_single,self.single(positive)),(self.backend.start_scan,self.scan(positive)),
                              (self.backend.start_batch,self.batch('name,Fe,H\na,99,1\n'))):
            with self.assertRaises(ApiError):start(request)
        self.backend._launch.assert_not_called()
        zero=[{'el':'Fe','pct':100},{'el':'H','pct':0}]
        self.assertEqual(self.backend.start_single(self.single(zero)),'valid')
        self.assertEqual(self.backend.start_scan(self.scan(zero)),'valid')
        self.assertEqual(self.backend.start_batch(self.batch('name,Fe,H\na,100,0\n')),'valid')
        self.assertEqual(self.backend._launch.call_args.args[2]['parameters']['percentages'],(100.,0.))
    def test_unrelated_broken_element_does_not_block_valid_fe(self):
        (self.root/'AlI.csv').write_text('Intensity,Wavelength,Aki,Energy,c,t,j,g\n1,5000,NaN,0,,,0,1\n')
        self.assertEqual(self.backend.start_single(self.single()),'valid')

    def test_http_preflight_template_and_missing_library_are_400_not_500(self):
        import importlib.util
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        spec=importlib.util.spec_from_file_location('preflight_http',UI_ROOT/'web/server.py')
        with patch.dict('os.environ', {'SIMLIBS_SESSION_TOKEN': 'test-preflight-token'}), patch('real_backend.RealBackend',return_value=self.backend):
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        server=ThreadingHTTPServer(('127.0.0.1',0),module.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url=f'http://127.0.0.1:{server.server_port}'
        (self.root/'FeI.csv').unlink()
        cases=[('single',{'params':self.p,'composition':[{'el':'Fe','pct':100}]}),
               ('batch',{'params':self.p,'template_csv':'name,Fe\na,100\n'}),
               ('scan',{'params':self.p,'composition':[{'el':'Fe','pct':100}],'axis':'te','start':1,'end':1.1,'frames':2})]
        with patch('requests.get',side_effect=AssertionError('external HTTP')),patch.object(self.backend,'_probe_nist',side_effect=AssertionError('probe')):
            for route,body in cases+[('validate',cases[1][1])]:
                path='/api/templates/validate' if route=='validate' else '/api/simulate/'+route
                try:urlopen(Request(url+path,json.dumps(body).encode(),{'Content-Type':'application/json','X-SimLIBS-Token':'test-preflight-token'}),timeout=5)
                except HTTPError as error:self.assertEqual(error.code,400);self.assertIn('FeI',json.load(error)['error']['message'])
                else:self.fail('invalid library started worker')
            for path in ('/api/status?mode=local','/api/params'):
                with urlopen(Request(url+path,headers={'X-SimLIBS-Token':'test-preflight-token'}),timeout=5) as response:self.assertEqual(response.status,200)
        self.backend._launch.assert_not_called()
if __name__=='__main__':unittest.main()
