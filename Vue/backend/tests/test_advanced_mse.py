"""Actual HTTP/API -> worker.main -> cascade math -> persisted exports.
Captured official B III ASD atomic data, controlled transport; not live NIST.
"""
from dataclasses import replace
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from scipy.constants import e, k
from simlibs_ui import worker
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings
from simlibs_ui.storage import read_manifest
from simlibs_ui.advanced_nist import simulate
from simLIBS import stark_atomic_data as atomic
from simLIBS.stark_b import SourceCache, StarkDataAccessError
from test_stark_cascade import captured_b, CMEV

EVIDENCE=Path(__file__).resolve().parents[2]/'.ai-workflow/20261104-advanced-stark-cascade'


class Response:
    def __init__(self, text, url):
        self.content=text.encode('utf-8');self.url=url;self.status_code=200;self.headers={}
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):pass
    def raise_for_status(self):pass
    def iter_content(self,size):
        for start in range(0,len(self.content),size):yield self.content[start:start+size]


class AdvancedMSETests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.docs,self.atomic,self.line=captured_b();self.calls=[];self.events=[]
        self.s=replace(Settings(),output=str(self.root),python=r'E:/Anaconda/envs/simLIBS/python.exe')
        self.p=replace(Parameters(),elements=('B',),percentages=(100,),Te=10000*k/e,Ne=1e17,
            low_w=206.55,upper_w=206.75,max_ion_charge=2,broaden_grid_step=.0002,step=.0002,
            webscraping='local',mode_version=2,broadening='local',broaden_convention='physics').validated()
        self.raw=dict(model='nist',matrix=False,self_absorption=False,instrument_broadening=False,missing_stark='error')
        self.empty=self.root/'empty.json';self.empty.write_text(json.dumps(dict(schema_version=1,source='STARK-B',rows=[],
            rows_sha256='4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',manifest={'complete':True,'failures':[]})))
        self.env=patch.dict(os.environ,{'SIMLIBS_STARK_DATABASE':str(self.empty),'SIMLIBS_STARK_CACHE_DIR':str(self.root/'cache')})
        self.env.start();self.addCleanup(self.env.stop)

    def libs_html(self):
        r=self.line
        return ('var dataSticksArray=[[{label:"Wavelength"},{label:"B III"}],['+repr(r['wavelength_nm'])+',1.0]];'
            +'var cmeV='+repr(CMEV)+';spectra[5][3][\'name\']=\'B test fixture\';var lines='
            +json.dumps([[r['wavelength_nm'],r['gA_s'],r['upper_eV']*CMEV,5,3,r['lower_eV']*CMEV]])+';')

    def provider(self,session,method,url,**kwargs):
        from urllib.parse import urlsplit,parse_qs
        query=parse_qs(urlsplit(url).query);params=kwargs.get('params',{})
        self.calls.append(dict(method=method,url=url,params=params,data=kwargs.get('data'),verify=kwargs.get('verify'),timeout=kwargs.get('timeout')))
        if query.get('libs')==['1']:return Response(self.libs_html(),url)
        if 'stark-b.obspm.fr' in url:
            if kwargs.get('data',{}).get('action')=='periodictable:datasets':return Response('<table id="ion-datasets"></table>',url)
            raise AssertionError('Unexpected Stark source query '+url)
        if url==atomic.ASD_LEVELS:return Response(self.docs['levels']['text'],url)
        if url==atomic.ASD_IE:return Response(self.docs['ionization']['text'],url)
        if url==atomic.ASD_LINES and params.get('low_w')=='':return Response(self.docs['lines']['text'],url)
        raise AssertionError('Unexpected request '+url)

    def test_real_worker_entry_and_http_exports_keep_stages_sources_and_original_job(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
        from real_backend import RealBackend
        backend=RealBackend.__new__(RealBackend);backend._settings=self.s;backend._settings_path=self.root/'settings.json'
        backend._lock=threading.Lock();backend._jobs={}
        counter=[]
        def launch(kind,task_kind,payload,summary):
            jid=f'{len(counter)+1:032x}';counter.append(jid)
            directory=self.root/'.jobs'/jid;directory.mkdir(parents=True)
            request=dict(payload,job_id=jid,kind=task_kind,settings=self.s.to_dict(),directory=str(directory))
            request_path=directory/'request.json';request_path.write_text(json.dumps(request),encoding='utf-8');(directory/'go').touch()
            job=dict(job_id=jid,kind=kind,status='running',summary=summary,progress=0,events=[],subs=set(),
                     expected_result_path=str(directory/'result/manifest.json'),result_path=None)
            backend._jobs[jid]=job
            with patch.object(sys,'argv',['worker',str(request_path)]),patch.dict(os.environ,{'SIMLIBS_TASK_DIR':str(directory)}):
                exit_code=worker.main()
            events=[json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines()]
            for item in events:
                if item['event']=='progress':backend._emit(jid,'log',message=item['message'],progress=item['current'])
                elif item['event']=='success':job.update(status='completed',progress=100,result_path=item['path'],manifest=read_manifest(item['path']))
                elif item['event']=='error':job.update(status='failed',error=item['message'])
            self.assertEqual(exit_code,0,events[-1]);self.events=events;return jid
        with patch.dict(os.environ,{'SIMLIBS_SESSION_TOKEN':'cascade-local-fixture'}),patch('real_backend.RealBackend',return_value=backend):
            spec=importlib.util.spec_from_file_location('cascade_http',Path(__file__).resolve().parents[1]/'web/server.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        server=ThreadingHTTPServer(('127.0.0.1',0),module.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def http(path,body=None):
            request=Request(f'http://127.0.0.1:{server.server_port}'+path,None if body is None else json.dumps(body).encode(),
                {'Content-Type':'application/json','X-SimLIBS-Token':'cascade-local-fixture'})
            with urlopen(request,timeout=25) as r:return r.read()
        body={'params':{'te':self.p.Te,'ne':1e17,'resolution':1000,'low_w':self.p.low_w,'up_w':self.p.upper_w,
            'max_ion_charge':2,'mode':'local','mode_version':2,'broadening':'local','broaden_convention':'physics','broaden_grid_step':.0002},
            'composition':[{'el':'B','pct':100}],'advanced':self.raw}
        provider=self.provider
        def routed(session,method,url,**kwargs):return provider(session,method,url,**kwargs)
        with patch.object(backend,'_launch',side_effect=launch),patch('requests.sessions.Session.request',new=routed):
            job=json.loads(http('/api/simulate/advanced',body))['job_id']
            view=json.loads(http('/api/jobs/'+job));result=json.loads(http('/api/jobs/'+job+'/result'))
            csv=http('/api/jobs/'+job+'/export?kind=csv');diagnostics=http('/api/jobs/'+job+'/export?kind=diagnostics')
            exported=json.loads(http('/api/jobs/'+job+'/export?kind=json'))
        self.assertEqual(view['status'],'completed');row=result['origin']['line_diagnostics'][0]
        self.assertEqual(row['stark_resolution_layer'],'DK1980');self.assertEqual(row['stark_method'],'DK1980')
        self.assertGreater(row['thin_fwhm_nm'],0);self.assertTrue(np.isfinite(result['series']['raw']['ys']).all())
        self.assertIn('nist-aki-complete',row['stark_atomic_quality']);self.assertIn('10.1016/0022-4073(80)90014-X',row['stark_model_doi'])
        progress=[item for item in self.events if item['event']=='progress'];messages=[item['message'] for item in progress]
        self.assertEqual([x['current'] for x in progress],sorted(x['current'] for x in progress))
        for text in ['Json抓取：B III','STARK-B：B III','NIST：B III，获取能级数据','获取完整E1跃迁Aki','获取电离阈值','修正半经验：B III']:
            self.assertTrue(any(text in message for message in messages),text)
        self.assertTrue(any('读取已校验缓存' in m for m in messages))
        self.assertEqual(len([c for c in self.calls if c['url']==atomic.ASD_LEVELS]),1)
        self.assertEqual(len([c for c in self.calls if c['url']==atomic.ASD_IE]),1)
        self.assertEqual(exported['origin']['line_diagnostics'][0]['stark_resolution_layer'],'DK1980')
        self.assertIn(b'DK1980',diagnostics);self.assertIn(b'nominal_thin',csv)
        evidence=EVIDENCE/'worker-api';evidence.mkdir(exist_ok=True)
        for name,data in [('result.json',result),('export.json',exported),('events.json',self.events),('view.json',view),('requests.json',self.calls)]:
            (evidence/name).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
        (evidence/'spectrum.csv').write_bytes(csv);(evidence/'diagnostics.csv').write_bytes(diagnostics)
        (evidence/'verification.json').write_text(json.dumps({'scope':'Captured NIST atomic data + constructed line-area fixture, actual API/worker/math/export, not live science','job_id':job,'stage_count':len(progress),'row_layer':row['stark_resolution_layer'],'fwhm_nm':row['thin_fwhm_nm'],'spectrum_points':len(result['series']['raw']['xs']),'finite':True}),encoding='utf-8')

    def test_transport_rejects_truncated_vamdc_header_instead_of_faking_complete(self):
        from simlibs_ui.advanced_stark import StarkTransport
        transport=StarkTransport(self.s,lambda:False,lambda *args:None,
            request=lambda *a,**kw:Response('<XSAMSData xmlns="http://vamdc.org/xml/xsams/1.0"/>','fixture'))
        from simLIBS import stark_vamdc
        with transport.stage('条件',30):
            with self.assertRaisesRegex(ValueError,'completeness header'):stark_vamdc.fetch_species('B',2,1e17)


if __name__=='__main__':unittest.main()
