"""仅两次真实NIST请求；经正在运行的8517 HTTP/API/worker，PNG及两尺度对照GIF。"""
from pathlib import Path
import json
import math
import sys
import time
from urllib.request import Request,urlopen
from urllib.parse import urlsplit,parse_qs

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
from PIL import Image
from simlibs_ui.storage import write_json,read_manifest
from simlibs_ui.operations import export_result
from simlibs_ui.plotting import figure_for

OUT=Path(__file__).parent/'scientific'
OUT.mkdir(parents=True,exist_ok=True)
REPORT={'requests':[],'purpose':'real photon/energy comparison; no post-hoc physical conversion'}
def api(path,body=None):
    request=Request('http://127.0.0.1:8517'+path,None if body is None else json.dumps(body).encode(),{'Content-Type':'application/json'})
    with urlopen(request,timeout=120) as response:return response.read()
def get(path):return json.loads(api(path))
def peak(df,w):
    selected=df.loc[(df['wavelength']>=w-2)&(df['wavelength']<=w+2),'intensity']
    assert len(selected)
    return float(selected.max())
try:
    for scale,number in [('photon','2'),('energy','1')]:
        print('Starting real scale:',scale,flush=True)
        params=dict(te=1.,ne=1e17,resolution=1000,low_w=400.,up_w=700.,max_ion_charge=3,mode='static',headless=True,resample=False,intensity_scale=scale)
        started=time.monotonic()
        jid=json.loads(api('/api/simulate/single',dict(params=params,composition=[dict(el='H',pct=100.)],title='H multi-line flux verification')))['job_id']
        deadline=started+90
        while True:
            job=get('/api/jobs/'+jid)
            if job['status'] in ('completed','failed','cancelled'):break
            if time.monotonic()>deadline:raise RuntimeError('science verification exceeded deadline')
            time.sleep(.1)
        assert job['status']=='completed',job
        result=get('/api/jobs/'+jid+'/result')
        manifest=json.loads(api('/api/jobs/'+jid+'/export?kind=json'))
        origin=manifest['origin']
        assert origin['intensity_scale']==scale and result['meta']['intensity_scale']==scale
        assert parse_qs(urlsplit(origin['nist_url']).query)['int_scale']==[number]
        raw=pd.read_csv(manifest['files']['raw']);interpolated=pd.read_csv(manifest['files']['interpolated'])
        assert len(raw) and len(interpolated) and np.isfinite(raw.to_numpy()).all() and np.isfinite(interpolated.to_numpy()).all()
        assert len(result['xs'])<=6000 and len(result['xs'])>1500
        for kind,suffix in [('csv','csv'),('json','json'),('png','png')]:
            (OUT/(scale+'.'+suffix)).write_bytes(api('/api/jobs/'+jid+'/export?kind='+kind))
        with Image.open(OUT/(scale+'.png')) as image:assert image.format=='PNG'
        figure=figure_for(manifest,'interpolated','flux verification','#ef4444',False)
        label=figure.axes[0].get_ylabel();assert scale.capitalize()+' flux [a.u.]'==label;figure.clear()
        entry={'scale':scale,'int_scale':int(number),'job_id':jid,'elapsed':time.monotonic()-started,
               'manifest':str(Path(manifest['files']['raw']).parent/'manifest.json'), 'rows':{'raw':len(raw),'interpolated':len(interpolated),'web_display':len(result['xs'])},
               'ratios_to_656':{str(w):peak(raw,w)/peak(raw,656.28) for w in [410.17,434.05,486.13]},'origin':origin,'png_axis':label}
        REPORT['requests'].append(entry);write_json(OUT/'checks.json',REPORT)
        print(json.dumps(entry,ensure_ascii=False),flush=True)
    first,second=REPORT['requests']
    change=second['ratios_to_656']['410.17']/first['ratios_to_656']['410.17']
    assert not math.isclose(change,1,rel_tol=.01),'different scale must alter relative line weighting'
    REPORT['energy_vs_photon_ratio_change_410_to_656']=change
    # 只复用以上两次真实结果，做通量对照GIF；不是新Te/Ne/R扫描，不造新科学帧。
    comparison={'kind':'scan','axis':'int_scale','parameters':dict(elements=['H'],Te=1.,Ne=1e17),
                'values':[2,1],'completed_values':[2,1],'frames':[entry['manifest'] for entry in REPORT['requests']],
                'partial':False,'purpose':'comparison of two already completed real scale requests; not a parameter scan job'}
    write_json(OUT/'comparison.json',comparison)
    export_result(OUT/'comparison.json',OUT/'photon-energy-comparison.gif','gif',title='Real NIST photon / energy comparison')
    with Image.open(OUT/'photon-energy-comparison.gif') as gif:
        assert gif.n_frames==2
        for index in range(2):gif.seek(index);gif.load()
        REPORT['gif_frames']=gif.n_frames
    REPORT['all_success']=True;write_json(OUT/'checks.json',REPORT)
    print('SCIENCE_VALIDATION_SUCCESS; two real requests; two PNGs; GIF2',flush=True)
except Exception as exc:
    REPORT['error']=str(exc);write_json(OUT/'checks.json',REPORT);raise
