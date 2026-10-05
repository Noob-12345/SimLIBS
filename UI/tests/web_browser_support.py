"""现成隔离 Chrome + 本地静态/假传输测试；不下载驱动或访问 NIST。"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
from pathlib import Path
import tempfile
import threading
import unittest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from simlibs_ui.settings import Settings, UI_ROOT
from simlibs_ui.adapter import chrome_version, driver_version


class BrowserCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.received = []
        cls.reply_status = None
        cls.reply_result = None
        cls.params_reply=None;cls.get_paths=[]
        from simlibs_ui.offline_database import capabilities
        cls.local_capabilities=capabilities(Settings().line_database)
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,directory=str(UI_ROOT/'web'/'static'),**kwargs)
            def log_message(self,*args): pass
            def send_json(self,data,status=200):
                body=json.dumps(data,ensure_ascii=False).encode('utf-8')
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                path=self.path.split('?')[0]
                cls.get_paths.append(self.path)
                if path=='/api/status':return self.send_json({'engine':'simlibs','engine_label':'TEST offline','python':'3.10','nist_ok':False,'chrome':'TEST'})
                if path=='/api/params':return self.send_json(cls.params_reply or {'params':{'te':1.,'ne':1e17,'resolution':1000,'low_w':650,'up_w':660,'max_ion_charge':2,'mode':'client','mode_version':2,'headless':True,'resample':False},'composition':[{'el':'W','pct':50},{'el':'Fe','pct':25},{'el':'Mo','pct':25}],'local_capabilities':cls.local_capabilities})
                if path=='/api/settings':return self.send_json({})
                if path=='/api/jobs':return self.send_json({'jobs':[]})
                if path=='/api/preview':return self.send_json({'error':{'message':'test: no synthetic scientific preview'}},501)
                if path.endswith('/events'):
                    event={'seq':0,'type':'status','status':cls.reply_status or 'failed','final':True,'job_id':'fixture'}
                    data=('data: '+json.dumps(event)+'\n\n').encode()
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                if path.endswith('/result'):return self.send_json(cls.reply_result or {})
                return super().do_GET()
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                cls.received.append((self.path,data))
                if self.path=='/api/templates/validate':
                    import sys
                    sys.path.insert(0,str(UI_ROOT/'web'))
                    from backend_api import BatchRequest,ApiError
                    try:
                        plan=BatchRequest.from_api(data).template_plan
                        return self.send_json({k:v for k,v in plan.items() if k not in ('entries','source_csv')})
                    except ApiError as error:return self.send_json({'error':{'message':str(error)}},400)
                if cls.reply_status:return self.send_json({'job_id':'fixture'})
                return self.send_json({'error':{'message':'offline test transport; no worker started'}},400)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        browser=chrome_version(Settings())
        drivers=[p for p in (UI_ROOT/'.driver-cache').rglob('chromedriver.exe') if driver_version(p).split('.')[:3]==browser.split('.')[:3]]
        if not drivers:raise RuntimeError('离线浏览器测试需要现有匹配驱动，不自动下载')
        options=Options()
        for flag in ['--headless=new','--disable-background-networking','--no-first-run','--disable-sync','--disable-extensions']:
            options.add_argument(flag)
        options.add_argument('--user-data-dir='+str(Path(cls.temp.name)/'isolated-profile'))
        cls.service=Service(str(drivers[0]))
        try:cls.driver=webdriver.Chrome(service=cls.service,options=options)
        except Exception:
            cls.service.stop();cls.server.shutdown();cls.server.server_close();cls.temp.cleanup();raise
        cls.driver.set_page_load_timeout(20)
        cls.url=f'http://127.0.0.1:{cls.server.server_port}/'

    @classmethod
    def tearDownClass(cls):
        try:cls.driver.quit()
        finally:
            cls.service.stop();cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()

    def setUp(self):
        type(self).received.clear();type(self).reply_status=None;type(self).reply_result=None
        self.driver.set_window_size(1366,768)
        self.driver.get(self.url)
        self.js("themePreference={mode:'dark',preset:'violet'};applyTheme();")
        WebDriverWait(self.driver,10).until(lambda d:d.execute_script("return typeof state!=='undefined' && state.previewUnsupported"))

    def js(self,code,*args):
        return self.driver.execute_script(code,*args)
