"""Finite-level LTE homogeneous slab; intrinsic transport precedes instrument response."""
from dataclasses import replace
import math
import os
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import voigt_profile
from scipy.signal import fftconvolve
from .offline_database import load_library, preflight
from .offline_engine import ion_fractions, CM_TO_EV, K, C, H, E, U_MASS
from .storage import now, write_csv

VERSION = 'finite-lte-slab-1'

def options(raw):
    if not isinstance(raw, dict): raise ValueError('高级参数须为对象')
    out = {}
    for name in ('self_absorption', 'matrix'):
        value = raw.get(name, True)
        if type(value) is not bool: raise ValueError(name+'须为布尔值')
        out[name] = value
    for name, default, low, high in [('column_cm2',1e16,0,1e24),('te_factor',1,1e-4,1e4),('ne_factor',1,1e-4,1e4),('intrinsic_gaussian_nm',.01,0,10),('intrinsic_lorentz_nm',.002,0,10),('temperature_K',10000,0,1e8),('grid_refinement',1,1,4)]:
        value=raw.get(name,default)
        if isinstance(value,bool):raise ValueError(name+'须为数值')
        try:value=float(value)
        except (TypeError,ValueError):raise ValueError(name+'须为数值') from None
        if not math.isfinite(value) or not low<=value<=high:raise ValueError(f'{name}须在{low}至{high}之间')
        out[name]=value
    response=raw.get('responses',{})
    if not isinstance(response,dict):raise ValueError('元素响应须为对象')
    out['responses']={}
    for el,value in response.items():
        if isinstance(value,bool):raise ValueError('元素响应须为有限非负数')
        try:value=float(value)
        except (TypeError,ValueError):raise ValueError('元素响应须为有限非负数') from None
        if not math.isfinite(value) or not 0<=value<=1e6:raise ValueError('元素响应须在0至1e6之间')
        out['responses'][el]=value
    return out

def effective(p, raw):
    o=options(raw)
    if p.webscraping!='local':raise ValueError('高级模型仅使用真实本地原子线表')
    if (p.upper_w-p.low_w)/((p.upper_w+p.low_w)/2)>.05:raise ValueError('高级窄带仪器近似要求相对波段跨度≤5%，请缩小波长范围')
    if set(o['responses'])-set(p.elements):raise ValueError('响应系数含组成之外的元素')
    weights=[pct/100*(o['responses'].get(el,1) if o['matrix'] else 1) for el,pct in zip(p.elements,p.percentages)]
    scale=sum(weights)
    if scale<=0:raise ValueError('有效组成不能全为零，请增大至少一个有含量元素的响应')
    q=replace(p,Te=p.Te*(o['te_factor'] if o['matrix'] else 1),Ne=p.Ne*(o['ne_factor'] if o['matrix'] else 1),percentages=tuple(100*w/scale for w in weights),local_broadening_enabled=True,local_temperature_mode='manual',local_temperature_K=o['temperature_K']).validated()
    if not .01<=q.Te<=100 or not 1e10<=q.Ne<=1e23:raise ValueError('有效Te须为0.01–100 eV，Ne须为1e10–1e23 cm^-3')
    if o['intrinsic_gaussian_nm']==o['intrinsic_lorentz_nm']==o['temperature_K']==0:raise ValueError('内禀线宽不能为零；请设置温度或内禀Gaussian/Lorentz宽度')
    return q,o,scale

def escape_factor(tau):
    tau=np.asarray(tau,dtype=float)
    result=np.ones_like(tau)
    np.divide(-np.expm1(-tau),tau,out=result,where=tau!=0)
    return result

def simulate(p,s,raw,cancelled=lambda:False,emit=None):
    def check():
        if cancelled():raise InterruptedError('高级模拟已取消')
    def progress(value,message):
        check()
        if emit:emit('progress',current=value,total=100,message=message,deadline=180)
    q,o,scale=effective(p,raw);preflight(q,s.line_database)
    progress(5,'读取真实原子线表与有限能级布居')
    library=load_library(s.line_database,{el for el,pct in zip(p.elements,p.percentages) if pct>0})
    ref=(q.low_w+q.upper_w)/2;instrument_sigma=ref/q.resolution/(2*math.sqrt(2*math.log(2)))
    padding=8*instrument_sigma
    if q.low_w-padding<=0:raise ValueError('仪器宽度超出有效正波长范围，请提高R或调整波段')
    lines=[];populations={};coverage={}
    for el,pct,nominal_pct in zip(q.elements,q.percentages,p.percentages):
        if nominal_pct<=0:continue
        check();states=library['elements'][el];meta=library['metadata']['elements'][el]
        fractions,log_u=ion_fractions(states,meta,q.Te,q.Ne);populations[el]=fractions
        nominal_fractions,nominal_u=ion_fractions(states,meta,p.Te,p.Ne)
        coverage[el]={str(charge):{'lines':len(state['transitions']),'levels':len(state['levels']),'excluded':state['excluded']} for charge,state in states.items()}
        for charge,state in states.items():
            if charge>q.max_ion_charge:continue
            for line in state['transitions']:
                center=line['wavelength_nm'];thermal=center*math.sqrt(8*K*o['temperature_K']*math.log(2)/(float(meta['atomic_mass_u'])*U_MASS*C*C))
                gaussian=math.hypot(o['intrinsic_gaussian_nm'],thermal);gamma=o['intrinsic_lorentz_nm']/2
                sigma=gaussian/(2*math.sqrt(2*math.log(2)))
                if not gamma and not q.low_w-padding-8*sigma<=center<=q.upper_w+padding+8*sigma:continue
                fraction=pct/100*fractions[charge]
                lower=fraction*math.exp(math.log(line['g_lower'])-line['lower_cm']*CM_TO_EV/q.Te-log_u[charge])
                upper=fraction*math.exp(math.log(line['g_upper'])-line['upper_cm']*CM_TO_EV/q.Te-log_u[charge])
                # N[cm^-2] -> m^-2. Response yield scales the emitting column, not a post-hoc intensity.
                column=o['column_cm2']*1e4*scale
                nominal_upper=o['column_cm2']*1e4*nominal_pct/100*nominal_fractions[charge]*math.exp(math.log(line['g_upper'])-line['upper_cm']*CM_TO_EV/p.Te-nominal_u[charge])
                lines.append(dict(line,element=el,charge=charge,sigma_nm=sigma,gamma_nm=gamma,N_lower_m2=column*lower,N_upper_m2=column*upper,N_nominal_upper_m2=nominal_upper,file=state['file']))
    if not lines:raise ValueError('该窗口没有可用本地发射线，请调整波段或元素')
    widths=[.5346*(2*l['gamma_nm'])+math.sqrt(.2166*(2*l['gamma_nm'])**2+(2.354820045*l['sigma_nm'])**2) for l in lines]
    output_step=q.step if q.resample else q.broaden_grid_step
    step=min(min(widths)/8,output_step/2,instrument_sigma/3)/o['grid_refinement']
    points=int(math.ceil((q.upper_w-q.low_w+2*padding)/step))+1
    channels=sorted({l['element']+' '+('I' if l['charge']==0 else 'II') for l in lines})
    if points>200000 or points*(len(channels)*3+8)>5000000 or points*len(lines)>30000000:
        raise ValueError('高级内禀网格/工作量超限；请缩小波段、减少元素或增大物理内禀线宽，不会自动粗采样')
    count=int(math.ceil((q.upper_w-q.low_w)/output_step))+1
    if count>200000:raise ValueError('输出超过200000节点，请增大输出步长')
    axis=np.linspace(q.low_w-padding,q.upper_w+padding,points);dx=float(axis[1]-axis[0])
    thin={key:np.zeros(points) for key in channels};nominal=np.zeros(points);tau=np.zeros(points)
    for index,line in enumerate(lines):
        check();center=line['wavelength_nm'];profile=voigt_profile(axis-center,line['sigma_nm'],line['gamma_nm'])
        key=line['element']+' '+('I' if line['charge']==0 else 'II')
        # nu0 comes from the level gap. Tabulated (possibly air) centers are only positions.
        nu0=(line['upper_cm']-line['lower_cm'])*CM_TO_EV*E/H
        lambda0=C/nu0
        # phi_nu = phi_lambda[nm^-1] * lambda0[m]^2 / (c * 1e-9).
        # A lambda0^2/(8 pi) * Ndiff[m^-2] * phi_nu[Hz^-1] is dimensionless.
        n_diff=line['g_upper']/line['g_lower']*line['N_lower_m2']*(-math.expm1(-(line['upper_cm']-line['lower_cm'])*CM_TO_EV/q.Te))
        coefficient=line['Aki_s']*lambda0**4/(8*math.pi*C*1e-9)*n_diff
        line_tau=coefficient*profile;tau+=line_tau
        emission=line['N_upper_m2']*line['Aki_s']/(4*math.pi)*profile
        thin[key]+=emission
        nominal+=line['N_nominal_upper_m2']*line['Aki_s']/(4*math.pi)*profile
        line['nu0_Hz']=nu0
        line['tau_peak_sampled']=float(line_tau.max());line['tau_coefficient_nm']=coefficient
        progress(10+65*(index+1)/len(lines),f'内禀传输谱线 {index+1}/{len(lines)}')
    beta=escape_factor(tau) if o['self_absorption'] else np.ones(points)
    # Gaussian response is applied only AFTER mixed opacity, with 8 sigma padding.
    radius=int(math.ceil(padding/dx));kernel_axis=np.arange(-radius,radius+1)*dx
    kernel=np.exp(-.5*(kernel_axis/instrument_sigma)**2);kernel/=kernel.sum()
    target=np.linspace(q.low_w,q.upper_w,count);corrected={};reference={}
    for key,values in thin.items():
        check()
        reference[key]=np.maximum(0,np.interp(target,axis,fftconvolve(values,kernel,mode='same')))
        corrected[key]=np.maximum(0,np.interp(target,axis,fftconvolve(values*beta,kernel,mode='same')))
    total=np.sum(list(corrected.values()),axis=0);thin_total=np.sum(list(reference.values()),axis=0)
    if not np.isfinite(total).all() or not np.isfinite(tau).all():raise ValueError('高级模型产生非有限值，请检查输入范围')
    corrected_frame=pd.DataFrame({'Wavelength (nm)':target,**corrected,'Sum(calc)':total})
    main=pd.DataFrame({'wavelength':target,'intensity':total})
    origin={'kind':'simulation','mode':'advanced','mode_version':2,'label':'高级本地 · 有限能级LTE均匀slab / 参数化基体（未标定）','parameters':q.to_dict(),'requested_parameters':p.to_dict(),'advanced':o,'model_version':VERSION,'network_used':False,'actual_resolution':q.resolution,'intensity_scale':'photon','intensity_units':'model photon radiance / (s m^2 sr nm); not calibrated detector counts','spectrum_style':'continuous','created_at':now(),'library':library['signature'],'atomic_sources':{el:library['metadata']['elements'][el] for el in populations},'coverage':coverage,'ion_fractions':populations,'matrix':{'yield_scale':scale,'effective_composition':dict(zip(q.elements,q.percentages)),'effective_Te_eV':q.Te,'effective_Ne_cm3':q.Ne,'effective_column_cm2':o['column_cm2']*scale},'grid':{'internal_points':points,'internal_step_nm':dx,'output_points':count,'output_step_nm':float(target[1]-target[0]),'instrument_reference_nm':ref,'instrument_FWHM_nm':ref/q.resolution,'padding_nm':padding,'min_intrinsic_FWHM_nm':min(widths)},'diagnostics':{'tau_max':float(tau.max()),'beta_min':float(beta.min()),'line_count':len(lines),'thin_integral':float(np.trapezoid(thin_total,target)),'corrected_integral':float(np.trapezoid(total,target))},'assumptions':['finite observed levels and I/II Saha; no invented higher stages','uniform isothermal LTE slab, no background/scattering/continuum or population feedback','column and Ne are independent prescribed conditions; background electrons not modeled','tabulated wavelength retained; per-line narrow-profile frequency-wavelength Jacobian; energy gap used for LTE stimulated emission','instrument Gaussian uses window midpoint; span<=5%; transfer precedes convolution','parameterized matrix response is not universal uncalibrated material prediction','no gradients or claimed self-reversal; no complete collisional/Stark data','Gaussian convolution padding 8 sigma; Voigt wings evaluated on padded grid; finite database coverage']}
    if os.environ.get('SIMLIBS_TASK_DIR'):
        directory=Path(os.environ['SIMLIBS_TASK_DIR'])
        nominal_output=np.maximum(0,np.interp(target,axis,fftconvolve(nominal,kernel,mode='same')))
        reference_path=directory/'advanced-reference.csv';write_csv(reference_path,pd.DataFrame({'wavelength':target,'intensity':thin_total,'nominal_intensity':nominal_output,**reference}))
        diagnostic_path=directory/'advanced-opacity.csv';write_csv(diagnostic_path,pd.DataFrame({'wavelength':axis,'tau':tau,'beta':beta}))
        line_path=directory/'advanced-lines.csv';write_csv(line_path,pd.DataFrame(lines))
        origin.update(thin_reference=str(reference_path),opacity_table=str(diagnostic_path),line_table=str(line_path))
    progress(95,'仪器卷积与真实数据保存')
    return {'raw':main,'interpolated':main.copy(),'ion':corrected_frame,'ion_interpolated':corrected_frame.copy()},origin
