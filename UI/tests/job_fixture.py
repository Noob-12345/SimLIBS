"""受控慢/错误进程，用于测量真实子进程和 Tk 心跳。禁止联网。"""
import json
from pathlib import Path
import subprocess
import sys
import time

path = Path(sys.argv[1])
request = json.loads(path.read_text(encoding='utf-8'))
directory = path.parent
while not (directory / 'go').exists():
    time.sleep(.01)
def emit(event, **payload):
    with (directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(job_id=request['job_id'], event=event, **payload)) + '\n')
emit('progress', deadline=request.get('deadline', 20), message='controlled worker')
if request.get('child'):
    child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(300)'])
    (directory / 'child.pid').write_text(str(child.pid))
time.sleep(request.get('delay', .1))
if request.get('error'):
    emit('error', message='controlled failure')
    raise SystemExit(1)
manifest = directory / 'manifest.json'
manifest.write_text(json.dumps({'kind': 'fixture', 'value': 7}))
emit('success', path=str(manifest))
