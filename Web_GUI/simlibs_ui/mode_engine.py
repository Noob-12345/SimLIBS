"""v2 客户端：NIST 分段未展宽线表，在统一目标网格上本地合成。"""
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import time
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests
from .models import MAX_CELLS
from . import nist_recon
from .storage import clean_spectrum, now, write_csv, valid_ion_column


@dataclass(frozen=True)
class BandRequest:
    core_low: float
    core_high: float
    request_low: float
    request_high: float


def build_bands(low,high):
    if not math.isfinite(low+high) or not 0<low<high:
        raise ValueError('分段波长范围无效')
    return [BandRequest(low+i*500,min(low+(i+1)*500,high),max(low,low+i*500-2),min(high,low+(i+1)*500+2))
            for i in range(math.ceil((high-low)/500))]


def grid_for(p,step):
    n=int(round((p.upper_w-p.low_w)/step))+1
    if not 2<=n<=200000:raise ValueError('目标网格须为2–200000个实际节点')
    return np.linspace(p.low_w,p.upper_w,n)


def finish_frames(p,ion):
    """所有实际贡献与总谱使用同一线性重采样，不改变 raw CSV。"""
    ion=clean_spectrum(ion,ion=True)
    contributions=[c for c in ion if valid_ion_column(c)]
    if (ion[contributions+['Sum(calc)']].to_numpy()<0).any():raise ValueError('计算离子贡献和总谱须非负')
    raw=clean_spectrum(ion[['Wavelength (nm)','Sum(calc)']].rename(columns={'Wavelength (nm)':'wavelength','Sum(calc)':'intensity'}))
    interpolated=raw.copy()
    frames={'raw':raw,'interpolated':interpolated,'ion':clean_spectrum(ion,ion=True)}
    if p.resample:
        axis=grid_for(p,p.step)
        x=ion['Wavelength (nm)'].to_numpy(float)
        data={'Wavelength (nm)':axis}
        for col in ion:
            if col!='Wavelength (nm)':data[col]=np.interp(axis,x,ion[col].to_numpy(float),left=0,right=0)
        frames['ion_interpolated']=clean_spectrum(pd.DataFrame(data),ion=True)
        frames['interpolated']=clean_spectrum(frames['ion_interpolated'][['Wavelength (nm)','Sum(calc)']].rename(columns={'Wavelength (nm)':'wavelength','Sum(calc)':'intensity'}))
    return frames


def client_simulate(p,s,cancelled=lambda:False,emit=None,request_get=None):
    request_get=request_get or requests.get
    elements,percentages=p.request_composition()
    fields={'composition':';'.join(f'{e}:{v}' for e,v in zip(elements,percentages)),
            'spectra':','.join(f'{e}0-{p.max_ion_charge}' for e in elements),'limits_type':0,'show_av':3,'unit':1,
            'resolution':p.resolution,'temp':p.Te,'eden':f'{p.Ne:.15g}','maxcharge':p.max_ion_charge,
            'min_rel_int':p.broaden_min_rel_int,'int_scale':1 if p.intensity_scale=='energy' else 2,'libs':1}
    bands=build_bands(p.low_w,p.upper_w);tables=[];evidence=[]
    def check():
        if cancelled():raise InterruptedError('客户端线表任务已取消')
    def pause(seconds):
        stop=time.monotonic()+seconds
        while time.monotonic()<stop:check();time.sleep(max(0,min(.05,stop-time.monotonic())))
    for band in bands:
        check();end=time.monotonic()+s.static_deadline
        if emit:emit('progress',message=f'客户端线表 {band.core_low:g}–{band.core_high:g} nm',deadline=s.static_deadline)
        url='https://physics.nist.gov/cgi-bin/ASD/lines1.pl?'+urlencode(dict(fields,low_w=f'{band.request_low:g}',upp_w=f'{band.request_high:g}'))
        for attempt in range(1,4):
            check()
            remaining=end-time.monotonic()
            if remaining<=0:raise TimeoutError('当前线表段已超过期限')
            try:
                response=request_get(url,timeout=(min(s.connect_timeout,remaining),min(s.read_timeout,remaining)),verify=s.tls_verify)
                response.raise_for_status();check()
                if time.monotonic()>end:raise TimeoutError('线表响应超过本段期限')
                table=nist_recon.parse_nist_matrix(response.text,'dataSticksArray')
                if not np.isfinite(table.to_numpy(float)).all():raise ValueError('线表包含非有限值')
                nist_recon.line_strengths(table)
                tables.append(table)
                evidence.append(dict(band.__dict__,url=url,attempts=attempt,response_sha256=hashlib.sha256(response.text.encode()).hexdigest()))
                break
            except (requests.RequestException,TimeoutError) as error:
                if attempt==3 or end-time.monotonic()<1:raise RuntimeError(f'线表段请求失败：{band}') from error
                pause(min(1,end-time.monotonic()))
    check();table=nist_recon.merge_core_sticks(tables,bands)
    axis=grid_for(p,p.broaden_grid_step)
    if len(axis)*(len(nist_recon.ion_columns(table))+2)>MAX_CELLS:
        raise ValueError('合成离子通道超过5000000个单元，请缩小范围/离子阶数')
    render_r=p.resolution*(2*math.sqrt(math.log(2)) if p.broaden_convention=='physics' else 1)
    ion=nist_recon.render_ion_sticks(table,axis,render_r,center_decimals=p.broaden_center_decimals)
    check();frames=finish_frames(p,ion)
    source_file=Path(s.source)/'simLIBS'/'simulation.py'
    origin={'kind':'simulation','label':'NIST 线强 + Python 分段合并/统一展宽（客户端 v2）',
            'class':'simlibs_ui.mode_engine.client_simulate','source_file':str(source_file),
            'source_sha256':hashlib.sha256(source_file.read_bytes()).hexdigest(),'parameters':p.to_dict(),
            'mode_version':2,'mode':'client','data_provider':'NIST calculated dataSticksArray',
            'computation_location':'client-python','line_strength_location':'NIST server','broadening':'local',
            'requested_resolution':p.resolution,'actual_resolution':p.resolution,'actual_Ne':fields['eden'],
            'nist_url':evidence[0]['url'],'bands':evidence,'created_at':now(),'tls_verify':s.tls_verify,
            'retry_policy':{'attempts_per_band':3,'wait_seconds':1,'deadline_per_band':s.static_deadline},
            'intensity_scale':p.intensity_scale,'intensity_units':'a.u. (relative flux)',
            'broadening_params':{'convention':p.broaden_convention,'grid_step':p.broaden_grid_step,'render_resolution':render_r,'min_rel_int':p.broaden_min_rel_int},
            'interpolation':'linear on shared requested grid; outside source zero' if p.resample else 'none; direct synthesis on target grid',
            'line_table_rows':len(table)}
    if os.environ.get('SIMLIBS_TASK_DIR'):
        path=Path(os.environ['SIMLIBS_TASK_DIR'])/'line_table.csv';write_csv(path,table);origin['line_table']=str(path)
    return frames,origin


# Interpose solely to observe the official function's returned graph title: its
# local R may be lowered while the global resolution remains the requested R.
RECALC_OBSERVER = r"""
if(typeof lte_spectrum_js!=='function')throw new Error('Official lte_spectrum_js unavailable');
const original=lte_spectrum_js;
window.__simlibsRecalculated=null;
window.lte_spectrum_js=function(...args){
  const result=original.apply(this,args);
  const match=String(result[2]).match(/Resolution\s*=\s*([\d.eE+-]+)/);
  window.__simlibsRecalculated={effective_r:match?Number(match[1]):null,requested_r:Number(args[8]),
    rows:result[0].length-1,title:result[2],warning:document.getElementById('max_res_warning')?.textContent||'',
    global_r:typeof resolution==='number'?resolution:null};
  return result;
};
return true;
"""


def browser_sources(driver,url,directory=None):
    """Capture the actual response bodies loaded by this Chrome session, without extra physics requests."""
    import base64,json
    found={}
    for item in driver.get_log('performance'):
        event=json.loads(item['message'])['message']
        if event['method']!='Network.responseReceived':continue
        response=event['params']['response'];address=response['url']
        key='official_js' if address.endswith('/LIBS/js/saha_lte.js') else 'nist_response' if address==url else None
        if key:
            content=driver.execute_cdp_cmd('Network.getResponseBody',{'requestId':event['params']['requestId']})
            body=base64.b64decode(content['body']) if content.get('base64Encoded') else content['body'].encode('utf-8')
            found[key]={'url':address,'sha256':hashlib.sha256(body).hexdigest(),'status':response['status'],'encoding':'decoded browser response body'}
            if directory:
                target=directory/('official-saha-lte.js' if key=='official_js' else 'nist-server-response.html')
                target.write_bytes(body);found[key]['path']=str(target)
    if 'official_js' not in found or 'nist_response' not in found:raise RuntimeError('未捕获当前官方页面/JS响应，不发布缺失来源的新版结果')
    return found
