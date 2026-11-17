"""Read-only wavelength markers; no Aki/population/intensity qualification."""
import base64
import hashlib
import json
from pathlib import Path
import re
from .spectrum_browser import csv_rows,MAX_BYTES,_number


def markers(data,name,options=None):
    options=options or {};rows,delimiter=csv_rows(data)
    match=re.fullmatch(r'([A-Z][a-z]?)(I|II|III|IV|V|VI)\.csv',name)
    element=options.get('element') or (match[1][0].upper()+match[1][1:].lower() if match else '')
    species=options.get('species') or (match[2].upper() if match else '')
    headers={};result={}
    legacy=any(len(row)>7 and any('aki' in v.lower() for v in row) and any('configuration' in v.lower() for v in row) for _,row in rows)
    unit=options.get('unit') or ('angstrom' if legacy else None)
    if unit is None:raise ValueError('用户参考CSV须明确选择nm/angstrom/um单位')
    if unit not in ('nm','angstrom','um'):raise ValueError('参考波长单位须nm/angstrom/um')
    factor={'nm':1.,'angstrom':.1,'um':1000.}[unit]
    configured=options.get('fallback_column')==1
    columns={'aki':2,'energy':3,'configuration':4,'term':5,'j':6,'g':7} if legacy or configured else {}
    units={'aki':'10^8 s^-1','energy':'cm^-1'} if legacy or configured else {'aki':'','energy':''}
    header_names={}
    for _,values in rows:
        if any('wavelength' in v.lower() or 'unnamed' in v.lower() or v.strip().lower() in ('lambda','波长') for v in values):
            for i,value in enumerate(values):
                header_name=value.strip().lower();key=None
                if 'aki' in header_name:key='aki'
                elif 'energy' in header_name or 'levels' in header_name:key='energy'
                elif 'configuration' in header_name:key='configuration'
                elif header_name in ('term','terms'):key='term'
                elif header_name=='j':key='j'
                elif header_name=='g':key='g'
                if key:columns[key]=i;header_names[key]=value
            continue
        if any('108s' in v.replace(' ','') or '10^8' in v for v in values):units['aki']='10^8 s^-1'
        if any('cm' in v.lower() and ('level' in v.lower() or '-1' in v) for v in values):units['energy']='cm^-1'
    for key,label in header_names.items():
        lower=label.lower()
        if key=='energy' and ('cm' in lower):units['energy']='cm^-1'
        elif key=='energy' and re.search(r'(^|[^a-z])ev([^a-z]|$)',lower):units['energy']='eV'
        if key=='aki':
            if '10^8' in lower or '10⁸' in lower or '108s' in lower.replace(' ',''):units['aki']='10^8 s^-1'
            elif 's^-1' in lower or 's-1' in lower or lower.endswith('_s'):units['aki']='s^-1'
    def state(row,line):
        values={key:row[index].strip() if index<len(row) else '' for key,index in columns.items()}
        if any(len(v)>4096 for v in values.values()):raise ValueError('谱线详情单字段超过4096字符')
        return dict(line=line,**values,aki_unit=units['aki'],energy_unit=units['energy'],role='source row')
    for line,row in rows:
        if any('wavelength' in v.lower() or v.lower().strip() in ('lambda','波长') for v in row):
            for i,value in enumerate(row):
                value=value.lower().strip()
                if 'wavelength' in value or value in ('lambda','波长'):headers['x']=i
                elif value in ('element','元素'):headers['element']=i
                elif value in ('species','ion','离子'):headers['species']=i
            continue
        index=int(options.get('column',headers.get('x',options.get('fallback_column',1 if legacy else 0))))
        if index<0 or index>=len(row):continue
        value=_number(row[index])
        if value is None or value<=0:continue
        if any(i>=len(row) for key,i in headers.items() if key in ('element','species')):raise ValueError(f'参考CSV第{line}行元素/species列缺失')
        el=row[headers['element']].strip() if 'element' in headers else element
        ion=row[headers['species']].strip() if 'species' in headers else species
        if not el or not ion:raise ValueError('参考CSV须有element/species列、明确文件名FeI.csv，或填写元素/species')
        key=(el,ion);positions=result.setdefault(key,{})
        records=positions.setdefault(value*factor,[]);row_state=state(row,line)
        # Preserve source rows independently: adjacency and equal wavelengths
        # alone do not prove a transition or lower/upper pairing.
        records.append(dict(states=[row_state]))
        if sum(len(v) for v in result.values())>100_000:raise ValueError('参考线超过100000，未静默抽样')
    if not result:raise ValueError('参考CSV未找到正的真实波长位置')
    digest=hashlib.sha256(data).hexdigest()
    groups=[dict(id=hashlib.sha256((name+digest+el+ion).encode()).hexdigest()[:24],element=el,species=ion,
                 label=el+' '+ion,xs=sorted(values),source=name,sha256=digest,original_unit=unit,
                 unit='nm',count=len(values),positions=[dict(wavelength_nm=x,records=values[x]) for x in sorted(values)],
                 interpretation='position markers only; not identification or intensity') for (el,ion),values in result.items()]
    if len(json.dumps(groups,ensure_ascii=False).encode())>12_000_000:raise ValueError('参考详情响应超过12MB，未截断真实记录')
    return groups


def configured(directory):
    root=Path(directory);groups=[];issues=[];total=0
    if not root.is_dir():raise ValueError('当前谱线库目录不存在或不可读')
    for file in sorted(root.glob('*.csv')):
        if not re.fullmatch(r'[A-Z][a-z]?(I|II|III|IV|V|VI)',file.stem):continue
        try:
            if file.stat().st_size>MAX_BYTES:raise ValueError('文件超过32MB')
            current=markers(file.read_bytes(),file.name,{'unit':'angstrom','fallback_column':1})
            for group in current:group['unit_contract']='configured legacy Linedatabase wavelength column / Angstrom'
            groups.extend(current);total=sum(g['count'] for g in groups)
            if total>100_000:raise ValueError('当前库参考线总数超过100000')
        except (OSError,ValueError) as error:issues.append(dict(file=file.name,error=str(error)))
    if total>100_000:raise ValueError('当前库参考线总数超过100000，未截断')
    if not groups:raise ValueError('当前库没有可读取的谱线位置'+('：'+issues[0]['error'] if issues else ''))
    if len(json.dumps(groups,ensure_ascii=False).encode())>12_000_000:raise ValueError('当前库详情响应超过12MB')
    return dict(groups=groups,issues=issues,source='Current Settings.line_database (read only)',count=total)


def uploaded(body):
    text=body.get('data','')
    if not isinstance(text,str) or len(text)>4*((MAX_BYTES+2)//3):raise ValueError('参考上传超过32MB')
    try:data=base64.b64decode(text,validate=True)
    except (ValueError,TypeError):raise ValueError('参考上传不是有效base64') from None
    groups=markers(data,str(body.get('name','selected.csv')),body.get('options'))
    return dict(groups=groups,issues=[],source='User selected CSV bytes',count=sum(g['count'] for g in groups))
