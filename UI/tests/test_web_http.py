import importlib.util
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock,patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'web') not in sys.path:sys.path.insert(0,str(ROOT/'web'))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.backend=Mock()
        self.backend.start_single.return_value='fixture'
        self.backend.start_batch.return_value='fixture'
        self.backend.start_scan.return_value='fixture'
        self.backend.get_job.return_value={'job_id':'fixture','status':'completed','events':[{'type':'status','status':'completed','final':True,'job_id':'fixture'}]}
        spec=importlib.util.spec_from_file_location('http_test_server',ROOT/'web'/'server.py')
        with patch('real_backend.RealBackend',return_value=self.backend):
            self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.module.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def post(self,path,body):
        request=Request(self.url+path,json.dumps(body).encode(),{'Content-Type':'application/json'},method='POST')
        try:
            with urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except HTTPError as exc:return exc.code,json.load(exc)

    def test_three_http_routes_pass_energy_and_reject_bad_composition(self):
        params={'te':1,'ne':1e17,'resolution':1000,'low_w':650,'up_w':660,'max_ion_charge':3,'mode':'static','intensity_scale':'energy'}
        body={'params':params,'composition':[{'el':'H','pct':100}]}
        cases=[('single',body,'start_single'),
               ('batch',dict(params=params,n_samples=2,seed=1,te_range=[1,1],ne_range=[17,17],compositions=[{'name':'H','items':body['composition']}]),'start_batch'),
               ('scan',dict(body,axis='te',start=1,end=1.2,frames=2),'start_scan')]
        for name,request,method in cases:
            status,response=self.post('/api/simulate/'+name,request)
            self.assertEqual(status,200,response)
            self.assertEqual(getattr(self.backend,method).call_args.args[0].params.intensity_scale,'energy')
        self.backend.start_single.reset_mock()
        for bad in [[{'el':'Fe','pct':99}],[{'el':'FE','pct':100}],[{'el':'H','pct':float('nan')}]]:
            status,response=self.post('/api/simulate/single',dict(body,composition=bad))
            self.assertEqual(status,400,response)
        self.backend.start_single.assert_not_called()

    def test_sse_terminal_event_has_completed_status(self):
        with urlopen(self.url+'/api/jobs/fixture/events',timeout=5) as response:
            self.assertIn('text/event-stream',response.headers['Content-Type'])
            while True:
                line=response.readline().decode('utf-8')
                self.assertTrue(line,'SSE已结束但没有终态事件')
                if line.startswith('data:'):
                    payload=json.loads(line[5:]);break
        self.assertEqual(payload['status'],'completed')
        self.assertTrue(payload['final'])


if __name__=='__main__':unittest.main()
