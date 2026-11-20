"""Migrated peakfilling/Wavelet_peakfinding algorithms, not a simulation.

Source: user's ElementsDetectionApplication, source SHA256 in processing-source.json.
Only alternating peak stripping and CWT ridge/local-maximum correction are used.
Negative edges, integral stopping and pre-correction dedup semantics are retained.
Drift correction (2026-11-20) migrates drift_correction.py polynomial
recalibration; matched pairs come from greedy nearest-neighbour matching of
detected peaks against reference positions supplied by the caller.
"""
import math
import numpy as np
from .spectrum_cwt import cwt
from .spectrum_drift import SOURCE_SHA256 as DRIFT_SOURCE_SHA256, fit_drift_correction, match_peaks_to_reference

MAX_PROCESS_NODES=200_000
MAX_WORK=50_000_000
MAX_REFERENCE_POSITIONS=100_000


def integer(value,name,low,high):
    if isinstance(value,bool):raise ValueError(name+'须为整数')
    try:out=int(value)
    except (TypeError,ValueError,OverflowError):raise ValueError(name+'须为整数') from None
    if out!=float(value) or not low<=out<=high:raise ValueError(f'{name}须为{low}–{high}整数')
    return out


def parameters(raw,n):
    if not isinstance(raw,dict):raise ValueError('处理参数须为对象')
    mode=raw.get('mode','both')
    if mode not in ('background','peaks','both'):raise ValueError('步骤须为background/peaks/both')
    drift_correction=raw.get('drift_correction',False)
    if not isinstance(drift_correction,bool):raise ValueError('drift_correction须为布尔值')
    defaults=dict(order=6,max_iter=1000,epsilon=1e-4,neighbor=2,min_length=2,window=3,wavelet='mexh',scales=list(range(1,8)),threshold=200.,max_degree=3,tolerance=0.5)
    # Unused-key injection mirrors which stages actually run: the background
    # stage never runs in peaks mode (drift or not), and the CWT stage never
    # runs in background mode unless drift needs its peakfinding.
    unused_bg=mode=='peaks'
    unused_cwt=mode=='background' and not drift_correction
    unused=(('order','max_iter','epsilon') if unused_bg else ())+(('neighbor','min_length','window','wavelet','scales','threshold') if unused_cwt else ())
    raw={**raw,**{key:defaults[key] for key in unused}}
    result=dict(mode=mode,drift_correction=drift_correction,order=integer(raw.get('order',6),'order',1,100),max_iter=integer(raw.get('max_iter',1000),'max_iter',1,5000),
                neighbor=integer(raw.get('neighbor',2),'neighbor',1,64),min_length=integer(raw.get('min_length',2),'min_length',1,64),
                window=integer(raw.get('window',3),'window',0,128),wavelet=raw.get('wavelet','mexh'))
    for name,default in [('epsilon',1e-4),('threshold',200.)]:
        value=float(raw.get(name,default))
        if not math.isfinite(value) or value<0:raise ValueError(name+'须为有限非负数')
        result[name]=value
    if result['wavelet'] not in ('mexh','morl','gaus1','gaus2'):raise ValueError('小波名称不支持')
    scales=raw.get('scales',list(range(1,8)))
    if not isinstance(scales,list) or not 1<=len(scales)<=32:raise ValueError('尺度数量须为1–32')
    result['scales']=sorted(set(integer(v,'scale',1,64) for v in scales))
    if result['min_length']>len(result['scales']):raise ValueError('脊线长度不能超过尺度数')
    if drift_correction:
        result['max_degree']=integer(raw.get('max_degree',3),'max_degree',1,3)
        tolerance=float(raw.get('tolerance',0.5))
        if not math.isfinite(tolerance) or not 0.01<=tolerance<=10:raise ValueError('tolerance须为0.01–10nm的有限数值')
        result['tolerance']=tolerance
    else:
        result['max_degree']=defaults['max_degree'];result['tolerance']=defaults['tolerance']
    run_background=mode in ('background','both')
    peaks_needed=mode in ('peaks','both') or drift_correction
    if run_background and (n<2*result['order']+1 or n*result['max_iter']>MAX_WORK):raise ValueError('背景节点/阶数/迭代工作量超限（最多50M节点代数）')
    if peaks_needed and (n*len(scales)>4_000_000 or n*sum(16*v+1 for v in scales)>MAX_WORK):raise ValueError('CWT节点×核工作量超限，未自动抽样')
    return result


def reference_positions(raw):
    """Validate the caller-supplied theoretical positions for drift matching."""
    if raw is None:raise ValueError('漂移校正需要参考谱线位置；请先加载谱线位置参考并勾选显示')
    if not isinstance(raw,list) or not 2<=len(raw)<=MAX_REFERENCE_POSITIONS:raise ValueError('参考谱线位置须为2–100000个数值')
    values=np.asarray(raw,float)
    if not np.isfinite(values).all():raise ValueError('参考谱线位置存在非有限数值')
    return np.unique(values)


def background(values,x,order,epsilon,max_iter):
    current=np.asarray(values,dtype=float).copy();history=[];tiny=np.finfo(float).eps
    for iteration in range(1,max_iter+1):
        step=1 if iteration%2 else order;previous=current
        current=np.empty_like(previous);current[:step]=previous[:step]/2;current[-step:]=previous[-step:]/2
        neighbours=(previous[:-2*step]+previous[2*step:])/2
        current[step:-step]=np.where(previous[step:-step]>neighbours,neighbours,previous[step:-step])
        old_area=float(np.trapezoid(previous,x));area=float(np.trapezoid(current,x))
        change=abs(area-old_area)/max(abs(old_area),tiny)
        if not np.isfinite(current).all() or not all(math.isfinite(v) for v in (old_area,area,change)):
            raise ValueError('背景面积或变化率溢出，未返回无效背景')
        history.append(dict(iteration=iteration,step=step,previous_area=old_area,area=area,change_rate=change))
        if change<=epsilon:break
    return current,history


def ridge_peaks(signal,coefficients,neighbor,min_length,threshold,window):
    if not np.isfinite(coefficients).all():raise ValueError('CWT系数非有限，不能解释为0峰')
    maxima=np.zeros_like(coefficients,dtype=bool)
    maxima[:,1:-1]=(coefficients[:,1:-1]>coefficients[:,:-2])&(coefficients[:,1:-1]>coefficients[:,2:])
    ridges=[];scales,n=maxima.shape
    for point in np.where(maxima[-1])[0]:
        ridge=[(scales-1,int(point))];previous=int(point)
        for scale in range(scales-2,-1,-1):
            choices=[j for j in range(max(1,previous-neighbor),min(n-1,previous+neighbor+1)) if maxima[scale,j]]
            if not choices:break
            previous=min(choices,key=lambda j:abs(j-previous));ridge.append((scale,previous))
        if len(ridge)>=min_length and max(coefficients[s,j] for s,j in ridge)>threshold:ridges.append(ridge)
    seen=[];indices=[]
    for ridge in ridges:
        _,pos=min(ridge,key=lambda item:item[0])
        if pos in seen:continue
        seen.append(pos);left=max(0,pos-window);right=min(n-1,pos+window)
        indices.append(int(np.argmax(signal[left:right+1])+left))
    return indices,ridges


def process(measurement,curve,raw,reference_xs=None):
    selected=next((c for c in measurement['curves'] if c['id']==curve),None)
    if selected is None:raise ValueError('请选择当前数据中的一条原始曲线')
    x=np.asarray(measurement['xs'],float);y=np.asarray(selected['ys'],float)
    if not 3<=len(x)<=MAX_PROCESS_NODES or len(x)!=len(y):raise ValueError('处理仅支持3–200000节点，未抽样')
    if not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('处理输入必须有限')
    if not (np.diff(x)>0).all():raise ValueError('处理要求严格递增轴；重复轴仍可原始浏览，不能静默平均')
    p=parameters(raw,len(x));baseline=corrected=None;history=[];signal=y
    if p['mode'] in ('background','both'):
        baseline,history=background(y,x,p['order'],p['epsilon'],p['max_iter']);corrected=y-baseline;signal=corrected
    indices=[];ridges=[]
    peaks_needed=p['mode'] in ('peaks','both') or p['drift_correction']
    if peaks_needed:
        coefficients=cwt(signal,p['scales'],p['wavelet']);indices,ridges=ridge_peaks(signal,coefficients,p['neighbor'],p['min_length'],p['threshold'],p['window'])
    drift_model=None;corrected_xs=None
    if p['drift_correction']:
        if measurement['unit']!='nm':raise ValueError('漂移校正需要nm轴；pixel轴没有nm参考，不能校正')
        reference=reference_positions(reference_xs)
        exp_matched,theo_matched=match_peaks_to_reference(x[indices],reference,p['tolerance'])
        model=fit_drift_correction(exp_matched,theo_matched,p['max_degree'])
        drift_model=dict(degree=model.degree,coefficients=[float(c) for c in model.coefficients],
            matched_line_count=model.n_line,exp_wl=[float(v) for v in model.exp_wl],theo_wl=[float(v) for v in model.theo_wl],
            tolerance=p['tolerance'],max_degree=p['max_degree'])
        corrected_xs=model.correct(x)
        if not np.isfinite(corrected_xs).all():raise ValueError('校正波长非有限，保留原谱')
        if len(x)>1 and not (np.diff(corrected_xs)>0).all():raise ValueError('校正后波长轴非严格递增（过拟合或匹配错误）；保留原谱')
    result=dict(algorithm='alternating peak stripping + integrated real CWT ridge (source migration)',
        curve=curve,parameters=p,source=dict(sha256=measurement['sha256'],selection=measurement['provenance']['selection'],unit=measurement['unit']),
        background=baseline.tolist() if baseline is not None else None,corrected=corrected.tolist() if corrected is not None else None,
        iterations=len(history),converged=bool(history and history[-1]['change_rate']<=p['epsilon']),
        iteration_limit_reached=bool(history and len(history)==p['max_iter'] and history[-1]['change_rate']>p['epsilon']),
        last_change=history[-1]['change_rate'] if history else None,
        peaks=[dict(index=i,x=float(x[i]),intensity=float(signal[i]),original_intensity=float(y[i]),
                    **({'corrected_x':float(corrected_xs[i])} if corrected_xs is not None else {})) for i in indices],
        ridge_count=len(ridges),
        drift_model=drift_model,corrected_xs=corrected_xs.tolist() if corrected_xs is not None else None,
        note='Scales/neighbour/window use original sample indices, not nm; nonuniform axis not resampled; integral convergence is not pointwise convergence; no normalization/clipping'+('' if not p['drift_correction'] else '; drift matching is greedy nearest-neighbour within tolerance (new code), corrected axis shown as-is; hover readout x stays original'),
        source_hashes=dict(peakfilling='54a2f552ef6cbc4b35af4807a515f70776be4bf718ccfb65d00a3fbac68e8476',wavelet='977c3948dc2db65cb212677623c984e5d805ab5507a01f892a0d1fff7af745ab',drift_correction=DRIFT_SOURCE_SHA256))
    if any(a is not None and not np.isfinite(a).all() for a in (baseline,corrected)):raise ValueError('处理结果非有限，保留原谱')
    if any(not all(math.isfinite(p[key]) for key in ('x','intensity','original_intensity')) for p in result['peaks']):
        raise ValueError('峰结果非有限，保留原谱')
    return result
