"""零网络的有限能级 LTE / I-II Saha 相对光子光谱。"""
import math
import os
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import logsumexp,voigt_profile
from .offline_database import load_library
from .mode_engine import grid_for,finish_frames
from .storage import now,write_csv
from .models import MAX_CELLS

H=6.62607015e-34;K=1.380649e-23;ME=9.1093837139e-31;E=1.602176634e-19;C=299792458.;U_MASS=1.66053906892e-27
CM_TO_EV=H*C*100/E


def partition(levels,temperature_eV):
    if not levels:raise ValueError('缺少真实能级，无法计算分区函数')
    return float(logsumexp([math.log(v['g'])-v['energy_cm']*CM_TO_EV/temperature_eV for v in levels]))


def ion_fractions(states,meta,te,ne):
    if 0 not in states or 1 not in states or not states[0]['levels'] or not states[1]['levels']:
        raise ValueError('本地I/II能级不完整，不能捏造Saha态分配')
    ip=float(meta['first_ionization_eV'])
    if not math.isfinite(ip) or ip<=0:raise ValueError('缺少有限正的第一电离能')
    log_u=[partition(states[q]['levels'],te) for q in (0,1)]
    log_ratio=math.log(2)+1.5*(math.log(2*math.pi*ME*E/(H*H))+math.log(te))-math.log(ne)-math.log(1e6)+log_u[1]-log_u[0]-ip/te
    normalization=float(np.logaddexp(0,log_ratio))
    return [math.exp(-normalization),math.exp(log_ratio-normalization)],log_u


def local_simulate(p,s,cancelled=lambda:False,emit=None):
    if not p.local_broadening_enabled:
        from .offline_lines import simulate_lines
        return simulate_lines(p,s,cancelled)
    library=load_library(s.line_database,{el for el,pct in zip(p.elements,p.percentages) if pct>0});axis=grid_for(p,p.broaden_grid_step)
    pairs=[(el,pct) for el,pct in zip(p.elements,p.percentages) if pct>0]
    temperature=p.effective_temperature_K
    if len(axis)*(len(pairs)*2+2)>MAX_CELLS:raise ValueError('本地通道超过5000000单元，请缩小网格')
    data={'Wavelength (nm)':axis};line_records=[];populations={};coverage={}
    for el,pct in pairs:
        if cancelled():raise InterruptedError('本地模拟已取消')
        if el not in library['elements']:raise ValueError(f'本地库不支持元素 {el}；不向NIST回退')
        meta=library['metadata']['elements'].get(el)
        if not meta:raise ValueError(f'{el}缺少静态原子元数据，请补充有来源的metadata')
        states=library['elements'][el];fractions,log_u=ion_fractions(states,meta,p.Te,p.Ne)
        populations[el]={'I':fractions[0],'II':fractions[1]};coverage[el]={str(q):{'valid_lines':len(v['transitions']),'levels':len(v['levels']),'excluded':v['excluded'],'sha256':v['sha256']} for q,v in states.items()}
        mass=float(meta['atomic_mass_u'])*U_MASS
        if not math.isfinite(mass) or mass<=0:raise ValueError(f'{el}缺少有限正的原子质量')
        for q,state in sorted(states.items()):
            if q>p.max_ion_charge:continue
            output=np.zeros(len(axis),dtype=float)
            for transition in state['transitions']:
                if cancelled():raise InterruptedError('本地展宽已取消')
                center=transition['wavelength_nm']
                log_area=math.log(pct/100)+math.log(fractions[q]) if fractions[q]>0 else -math.inf
                log_area+=math.log(transition['g_upper'])-transition['upper_cm']*CM_TO_EV/p.Te-log_u[q]+math.log(transition['Aki_s'])
                area=math.exp(log_area)
                fwhm=center/p.resolution
                thermal=center*math.sqrt(8*K*temperature*math.log(2)/(mass*C*C)) if temperature else 0
                combined=math.sqrt(fwhm*fwhm+p.local_gaussian_nm**2+thermal**2)
                if not math.isfinite(combined) or combined<=0:raise ValueError('展宽产生非法宽度')
                sigma=combined/(2*math.sqrt(2*math.log(2)));gamma=p.local_lorentz_nm/2
                # Gaussian windows truncate at 8 sigma; Lorentz wings evaluated on every actual target node.
                lo,hi=(0,len(axis)) if gamma else (np.searchsorted(axis,center-8*sigma),np.searchsorted(axis,center+8*sigma))
                if hi<=lo:continue
                output[lo:hi]+=area*voigt_profile(axis[lo:hi]-center,sigma,gamma)
                line_records.append(dict(transition,element=el,charge=q,area_photon=area,gaussian_fwhm_nm=combined,thermal_fwhm_nm=thermal,lorentz_fwhm_nm=p.local_lorentz_nm,file=state['file']))
            data[el+' '+('I' if q==0 else 'II')]=output
    ion=pd.DataFrame(data);ions=[c for c in ion if c!='Wavelength (nm)'];ion['Sum(calc)']=ion[ions].sum(axis=1)
    if not np.isfinite(ion.to_numpy()).all():raise ValueError('本地物理计算得到非有限结果')
    frames=finish_frames(p,ion)
    origin={'kind':'simulation','label':'离线本地有限能级 LTE + I/II Saha · 相对photon',
            'mode':'local','mode_version':2,'class':'simlibs_ui.offline_engine.local_simulate','parameters':p.to_dict(),
            'computation_location':'offline-python','data_provider':'user Linedatabase CSV + sourced static atomic metadata',
            'line_strength_location':'offline LTE/Saha','broadening':'local','actual_resolution':p.resolution,'requested_resolution':p.resolution,
            'actual_Ne':p.Ne,'intensity_scale':'photon','intensity_units':'a.u. (relative photon emission weights)',
            'library':library['signature'],'atomic_sources':{el:library['metadata']['elements'][el] for el,_ in pairs},
            'ion_fractions':populations,'coverage':coverage,'created_at':now(),'network_used':False,
            'local_broadening_enabled':True,'spectrum_style':'continuous',
            'thermal_model_version':2,'thermal_temperature_mode':p.local_temperature_mode,'effective_heavy_temperature_K':temperature,
            'broadening_params':{'convention':'physics','grid_step':p.broaden_grid_step,'gaussian_FWHM_nm':p.local_gaussian_nm,
                                 'lorentz_FWHM_nm':p.local_lorentz_nm,'heavy_particle_temperature_mode':p.local_temperature_mode,'heavy_particle_temperature_K':temperature},
            'assumptions':['optically thin LTE','finite observed-level partition, dedup energy/g','I-II normalized Saha only; unavailable III/higher not invented','max charge filters emitted lines, not the available I-II equilibrium','no original Intensity ranking used','instrument Gaussian FWHM=lambda/R','single-temperature LTE: T_h=Te*e/k_B' if p.local_temperature_mode=='linked' else 'independent heavy-particle temperature; K=0 disables thermal Doppler','absolute calibration and Stark coefficients not provided'],
            'interpolation':'shared linear' if p.resample else 'none; direct target grid','line_table_rows':len(line_records)}
    if os.environ.get('SIMLIBS_TASK_DIR'):
        path=Path(os.environ['SIMLIBS_TASK_DIR'])/'local_line_table.csv';write_csv(path,pd.DataFrame(line_records));origin['line_table']=str(path)
    return frames,origin
