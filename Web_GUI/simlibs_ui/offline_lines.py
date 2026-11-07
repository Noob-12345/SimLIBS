"""Exact line weights and conservative grid deposition, with no broadening kernel."""
import math,os
from pathlib import Path
import numpy as np
import pandas as pd
from .offline_database import load_library
from .offline_engine import ion_fractions,CM_TO_EV
from .mode_engine import grid_for
from .models import MAX_CELLS,MAX_POINTS
from .storage import now,write_csv

def simulate_lines(p,s,cancelled):
    pairs=[(el,pct) for el,pct in zip(p.elements,p.percentages) if pct>0]
    library=load_library(s.line_database,{el for el,_ in pairs});records=[];populations={};coverage={};columns=[]
    for el,pct in pairs:
        if cancelled():raise InterruptedError('离散线谱已取消')
        if el not in library['elements']:raise ValueError(f'本地库不支持元素 {el}')
        states=library['elements'][el];fractions,log_u=ion_fractions(states,library['metadata']['elements'][el],p.Te,p.Ne)
        populations[el]={'I':fractions[0],'II':fractions[1]}
        coverage[el]={str(q):{'valid_lines':len(state['transitions']),'levels':len(state['levels']),'excluded':state['excluded'],'sha256':state['sha256']} for q,state in states.items()}
        for q,state in sorted(states.items()):
            if q>p.max_ion_charge:continue
            label=el+' '+('I' if q==0 else 'II');columns.append(label)
            for line in state['transitions']:
                if cancelled():raise InterruptedError('离散线谱已取消')
                center=line['wavelength_nm']
                if not p.low_w<=center<=p.upper_w:continue
                area=math.exp(math.log(pct/100)+math.log(fractions[q])+math.log(line['g_upper'])-line['upper_cm']*CM_TO_EV/p.Te-log_u[q]+math.log(line['Aki_s'])) if fractions[q]>0 else 0.
                records.append(dict(line,element=el,charge=q,ion=label,area_photon=area,file=state['file']))
    axis=np.array(sorted({p.low_w,p.upper_w}|{row['wavelength_nm'] for row in records}),float)
    grid=grid_for(p,p.step if p.resample else p.broaden_grid_step)
    if len(axis)>MAX_POINTS or max(len(axis),len(grid))*(len(columns)+2)>MAX_CELLS:raise ValueError('离散谱通道/点数超过资源上限')
    raw={c:np.zeros(len(axis)) for c in columns};sampled={c:np.zeros(len(grid)) for c in columns}
    for row in records:
        if cancelled():raise InterruptedError('离散线网格投影已取消')
        index=int(np.searchsorted(axis,row['wavelength_nm']));raw[row['ion']][index]+=row['area_photon']
        right=min(len(grid)-1,int(np.searchsorted(grid,row['wavelength_nm'])))
        target=right-1 if right>0 and row['wavelength_nm']-grid[right-1]<=grid[right]-row['wavelength_nm'] else right
        sampled[row['ion']][target]+=row['area_photon']
    def frame(x,channels):
        ion=pd.DataFrame({'Wavelength (nm)':x,**channels});ion['Sum(calc)']=ion[columns].sum(axis=1)
        if not np.isfinite(ion.to_numpy()).all():raise ValueError('线权重产生非有限值')
        total=ion[['Wavelength (nm)','Sum(calc)']].rename(columns={'Wavelength (nm)':'wavelength','Sum(calc)':'intensity'})
        return ion,total
    ion,total=frame(axis,raw);grid_ion,grid_total=frame(grid,sampled)
    origin={'kind':'simulation','label':'离线本地 · 未展宽线谱','mode':'local','mode_version':2,'parameters':p.to_dict(),
       'class':'simlibs_ui.offline_lines.simulate_lines','computation_location':'offline-python','line_strength_location':'offline LTE/Saha',
       'data_provider':'user Linedatabase CSV + sourced static atomic metadata','network_used':False,'broadening':'none',
       'local_broadening_enabled':False,'spectrum_style':'sticks','actual_resolution':None,'requested_resolution':p.resolution,
       'resolution_applied':False,'effective_heavy_temperature_K':None,'thermal_temperature_mode':p.local_temperature_mode,
       'intensity_scale':'photon','intensity_units':'a.u. (relative photon line weights, no convolution)',
       'raw_representation':'exact transition wavelengths; coincident weights summed; zero boundary markers',
       'sampling':'nearest target node accumulation preserving each ion line weight; no profile interpolation',
       'interpolation':'none; requested uniform grid deposition','grid_step':p.step if p.resample else p.broaden_grid_step,
       'actual_Ne':p.Ne,'library':library['signature'],'ion_fractions':populations,'coverage':coverage,
       'atomic_sources':{el:library['metadata']['elements'][el] for el,_ in pairs},'line_table_rows':len(records),'created_at':now(),
       'assumptions':['optically thin finite-level LTE/I-II Saha','no unavailable III or missing Aki invented','instrument/thermal/additional widths not applied']}
    if os.environ.get('SIMLIBS_TASK_DIR'):
        path=Path(os.environ['SIMLIBS_TASK_DIR'])/'local_line_table.csv';write_csv(path,pd.DataFrame(records));origin['line_table']=str(path)
    return {'raw':total,'interpolated':grid_total,'ion':ion,'ion_interpolated':grid_ion},origin
