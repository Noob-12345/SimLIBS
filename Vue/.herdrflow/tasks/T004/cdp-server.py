import os,sys
from pathlib import Path
from unittest.mock import patch
root=Path.cwd();sys.path[:0]=[str(root/'backend/web'),str(root/'backend')]
os.environ['SIMLIBS_SESSION_TOKEN']='browser-cdp-t004';os.environ['SIMLIBS_STATE_DIR']=str(root/'.herdrflow/tasks/T004/cdp-state');os.environ['PYTHONDONTWRITEBYTECODE']='1'
from simlibs_ui.settings import Settings
class LocalSettings:
    def get_settings(self):return Settings().to_dict()
    def engine_status(self,mode='local'):return dict(engine_label='T004 browser API',local=dict(ready=True,elements=['Fe','Mg','Si']))
    def default_params(self):return dict(local_capabilities=dict(ready=True,elements=['Fe','Mg','Si']))
    def list_jobs(self):return []
with patch('real_backend.RealBackend',LocalSettings):import server
http=server.ThreadingHTTPServer(('127.0.0.1',18524),server.Handler)
print('READY 18524',flush=True)
try:http.serve_forever()
finally:http.server_close()
