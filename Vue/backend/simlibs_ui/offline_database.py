"""用户谱线库的只读解析：按真实数据行配对，不删除 Unnamed 实际列。"""
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re


def library_signature(directory):
    root=Path(directory).resolve()
    files=sorted(root.glob('*.csv'))
    metadata=root/'simlibs-atomic-metadata.json'
    if metadata.is_file():files.append(metadata)
    if not files:raise ValueError('本地谱线库没有CSV')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {'root':str(root),'files':hashes,'sha256':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()}


def number(value,label,line):
    text=str(value).strip()
    if not text:return None
    try:n=float(text)
    except ValueError:raise ValueError(f'原始库第{line}行{label}不是有效数值：{text}') from None
    if not math.isfinite(n) or n<0:raise ValueError(f'原始库第{line}行{label}必须有限且非负')
    return n


def parse_file(path):
    path=Path(path);raw=path.read_bytes()
    for encoding in ('utf-8-sig','gb18030','cp1252'):
        try:text=raw.decode(encoding);break
        except UnicodeDecodeError:continue
    rows=list(csv.reader(io.StringIO(text)))
    records=[];levels={};excluded=[];pending=None
    indices={'wavelength':1,'aki':2,'energy':3,'g':7}
    for line,row in enumerate(rows,1):
        if not row or all(not str(v).strip() for v in row):continue
        if any('wavelength' in str(v).lower() for v in row):
            for key,tokens in {'wavelength':('wavelength',),'aki':('aki',),'energy':('energy','levels'),'g':('g',)}.items():
                for i,v in enumerate(row):
                    if str(v).strip().lower() in tokens or any(t!='g' and t in str(v).lower() for t in tokens):indices[key]=i;break
            continue
        if any('unnamed' in str(v).lower() for v in row) or any('cm' in str(v).lower() and 'level' in str(v).lower() for v in row):continue
        if len(row)<8:excluded.append({'rows':[line],'reason':'少于8个实际物理列'});pending=None;continue
        wave=number(row[indices['wavelength']],'波长Å',line)
        energy=number(row[indices['energy']],'能级cm^-1',line)
        weight=number(row[indices['g']],'g',line)
        aki=number(row[indices['aki']],'Aki',line)
        if energy is not None and weight is not None and weight>0:
            if not weight.is_integer():raise ValueError(f'第{line}行g应为正整数')
            levels[(energy,weight)]={'energy_cm':energy,'g':weight,'rows':levels.get((energy,weight),{}).get('rows',[])+[line]}
        if wave is None or wave<=0 or energy is None or weight is None or weight<=0:
            excluded.append({'rows':[line],'reason':'缺少波长/能级/正g'});pending=None;continue
        current={'line':line,'wave_A':wave,'energy_cm':energy,'g':weight,'aki_1e8':aki}
        if pending is None:pending=current;continue
        if not math.isclose(pending['wave_A'],wave,rel_tol=1e-9,abs_tol=1e-7):
            excluded.append({'rows':[pending['line']],'reason':'波长不匹配的孤立能级行'});pending=current;continue
        pair=[pending,current];pending=None
        low,upper=sorted(pair,key=lambda v:v['energy_cm']);delta=upper['energy_cm']-low['energy_cm']
        if delta<=0 or not math.isclose(1e8/wave,delta,rel_tol=.003):
            excluded.append({'rows':[v['line'] for v in pair],'reason':'上下能级差与Å波长不一致'});continue
        if any(v['aki_1e8'] is None or v['aki_1e8']<=0 for v in pair):
            excluded.append({'rows':[v['line'] for v in pair],'reason':'缺失/零Aki，不造发射系数'});continue
        if not math.isclose(low['aki_1e8'],upper['aki_1e8'],rel_tol=1e-9):
            excluded.append({'rows':[v['line'] for v in pair],'reason':'成对Aki不一致'});continue
        records.append({'wavelength_nm':wave*.1,'Aki_s':upper['aki_1e8']*1e8,'lower_cm':low['energy_cm'],
                        'upper_cm':upper['energy_cm'],'g_upper':upper['g'],'g_lower':low['g'],'rows':[v['line'] for v in pair]})
    if pending:excluded.append({'rows':[pending['line']],'reason':'未配对能级行'})
    return {'file':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'encoding':encoding,'levels':list(levels.values()),'transitions':records,'excluded':excluded}


def load_library(directory,elements=None):
    root=Path(directory).resolve();parsed={}
    for path in sorted(root.glob('*.csv')):
        match=re.fullmatch(r'([A-Z][a-z]?)(II|I)',path.stem)
        if match and (elements is None or match[1] in elements):parsed.setdefault(match[1],{})[len(match[2])-1]=parse_file(path)
    if not parsed:raise ValueError('本地库不支持所请求元素；没有可识别的I/II本地谱线文件')
    metadata_path=root/'simlibs-atomic-metadata.json'
    metadata=json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.is_file() else {'elements':{}}
    return {'elements':parsed,'metadata':metadata,'signature':library_signature(root)}


def inspect_library(directory):
    """Partial or broken libraries are diagnostics, never a status/params 500."""
    root=Path(directory).resolve();parsed={};issues={};global_error=None
    files=list(root.glob('*.csv')) if root.is_dir() else []
    if not root.is_dir():global_error=f'本地目录不存在：{root}'
    elif not files:global_error=f'本地目录没有CSV：{root}'
    for path in files:
        match=re.fullmatch(r'([A-Z][a-z]?)(II|I)',path.stem)
        if not match:continue
        el=match[1];q=len(match[2])-1;parsed.setdefault(el,{})
        try:parsed[el][q]=parse_file(path)
        except (OSError,ValueError,IndexError) as error:issues.setdefault(el,[]).append(f'{path.name}损坏：{error}')
    try:
        metadata=json.loads((root/'simlibs-atomic-metadata.json').read_text(encoding='utf-8'))
        if not isinstance(metadata,dict) or not isinstance(metadata.get('elements'),dict):raise ValueError('elements须为对象')
    except (OSError,ValueError) as error:
        metadata={'elements':{}};global_error=(global_error+'；' if global_error else '')+f'静态元数据缺失/损坏：{error}'
    for el,states in parsed.items():
        errors=issues.setdefault(el,[])
        for q in (0,1):
            if q not in states or not states[q]['levels']:errors.append(f'{el}{"I" if q==0 else "II"}缺少必要能级/文件')
        if not any(state['transitions'] for state in states.values()):errors.append('没有可用Aki成对发射谱线')
        try:
            meta=metadata['elements'][el]
            for key in ('atomic_mass_u','first_ionization_eV'):
                value=meta[key]
                if isinstance(value,bool) or not math.isfinite(float(value)) or float(value)<=0:raise ValueError(key+'须为有限正数')
            if not isinstance(meta.get('source_url'),str) or not meta['source_url'].startswith('https://'):raise ValueError('缺少HTTPS原子属性来源')
            if not re.fullmatch('[0-9a-fA-F]{64}',str(meta.get('response_sha256',''))):raise ValueError('缺少来源响应SHA256')
        except (KeyError,TypeError,ValueError) as error:errors.append('必要原子质量/电离能缺失或非法：'+str(error))
    issues={el:errors for el,errors in issues.items() if errors}
    stages={el:[q for q,state in states.items() if state['transitions']] for el,states in parsed.items()}
    elements=sorted(el for el in parsed if el not in issues)
    try:signature=library_signature(root)['sha256']
    except (OSError,ValueError):signature=None
    report={'root':str(root),'ready':bool(elements),'elements':elements,'csv_count':len(files),'stages':stages,
            'excluded':{el:sum(len(s['excluded']) for s in states.values()) for el,states in parsed.items()},
            'signature':signature,'issues':issues,'error':global_error or ('；'.join(el+': '+','.join(errors) for el,errors in issues.items()) if issues else None),
            'limitations':'有限已知能级/谱线的LTE与I↔II Saha近似；缺III谱线/分区数据不制造曲线；缺Aki已排除；不声称完整原子数据库'}
    if not elements and not report['error']:report['error']='没有可用的I/II谱线、能级和静态元数据'
    return report


def capabilities(directory):return inspect_library(directory)


def preflight(parameters,directory,report=None):
    report=report if report is not None else inspect_library(directory)
    errors=[]
    for el,pct in zip(parameters.elements,parameters.percentages):
        if pct<=0:continue
        if el not in report['elements']:errors.append(el+': '+'；'.join(report['issues'].get(el,[report['error'] or '本地库不支持此元素'])))
        elif not any(q<=parameters.max_ion_charge for q in report['stages'][el]):errors.append(el+': 所选离子范围没有可用发射线')
    if errors:raise ValueError('离线预检失败（'+report['root']+'）：'+'；'.join(errors)+'；不会向NIST回退')
    return report
