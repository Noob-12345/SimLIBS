"""CSV模板明确列语义与确定行/重复计划；Ne、Te仍是元素。"""
import csv
import hashlib
import io
from dataclasses import replace
from .models import ELEMENTS,composition,integer,Parameters,MAX_CELLS

PARAMETER_COLUMNS={'Te[eV]':'Te','Ne[cm^-3]':'Ne','R':'resolution','low_w[nm]':'low_w','upper_w[nm]':'upper_w',
                   'grid_step[nm]':'broaden_grid_step','max_ion_charge':'max_ion_charge',
                   'T_h[K]':'local_temperature_K','doppler_mode':'local_temperature_mode','intensity_scale':'intensity_scale',
                   'broaden':'local_broadening_enabled','resample':'resample','step[nm]':'step'}


def parse_template(text,parameters,repeats=1,name_column='name'):
    if not isinstance(text,str) or len(text)>2_000_000:raise ValueError('模板须为≤2MB的CSV文本')
    repeats=integer(repeats,'每行重复次数',1)
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames:raise ValueError('模板缺少表头')
    headers=[str(h).strip() for h in reader.fieldnames]
    if len(set(headers))!=len(headers):raise ValueError('模板重复列名')
    reader.fieldnames=headers
    if name_column not in headers and name_column=='name' and 'samples' in headers:name_column='samples'
    names={el.lower():el for el in ELEMENTS};element_columns={};overrides={}
    for header in headers:
        if header==name_column or header.startswith('Unnamed:'):continue
        if header in PARAMETER_COLUMNS:overrides[header]=PARAMETER_COLUMNS[header];continue
        el=names.get(header.removesuffix('_at%').lower())
        if not el:raise ValueError(f'未知模板列 {header}；参数使用Te[eV]/Ne[cm^-3]/R，裸Ne/Te是元素')
        if el in element_columns.values():raise ValueError('模板映射后元素列重复')
        element_columns[header]=el
    if not element_columns:raise ValueError('模板至少有一个组成列')
    entries=[];row_count=0
    for row_number,row in enumerate(reader,2):
        if all(not str(v or '').strip() for v in row.values()):continue
        if None in row:raise ValueError(f'第{row_number}行列数量超出表头')
        try:
            elements,pcts=composition(tuple(element_columns.values()),[row[c] for c in element_columns])
            values={attr:row[col] for col,attr in overrides.items()}
            if values.get('local_temperature_mode')=='linked' and values.get('local_temperature_K')=='':values.pop('local_temperature_K')
            if any(not str(value).strip() for value in values.values()):raise ValueError('参数覆盖列不能为空')
            for key in ('local_broadening_enabled','resample'):
                if key in values:
                    text=values[key].strip().lower()
                    if text not in ('true','false','1','0'):raise ValueError(key+'须为true/false或1/0')
                    values[key]=text in ('true','1')
            if 'local_temperature_K' in values:
                if values.get('local_temperature_mode')=='linked':raise ValueError('T_h[K]独立温度与linked冲突；选择manual')
                values['local_temperature_mode']='manual'
            actual=replace(parameters,elements=elements,percentages=pcts,**values).validated()
            name=str(row.get(name_column) or '').strip() if name_column in headers else f'row-{row_number-1}'
            if not name:raise ValueError('样本名称不能为空')
        except (ValueError,TypeError) as error:raise ValueError(f'模板第{row_number}行：{error}') from error
        row_count+=1
        for repetition in range(1,repeats+1):
            entries.append({'name':name,'template_row':row_number,'repetition':repetition,'parameters':actual.to_dict()})
        if len(entries)>5000:raise ValueError('模板总计划超过5000样本')
    if not entries:raise ValueError('模板没有有效数据行')
    grids={(e['parameters']['low_w'],e['parameters']['upper_w'],e['parameters']['step'] if e['parameters']['resample'] else e['parameters']['broaden_grid_step']) for e in entries}
    if len(grids)!=1:raise ValueError('模板波段/输出网格不一致，不能打包为统一训练数据')
    if sum(Parameters.from_dict(row['parameters']).points for row in entries)>MAX_CELLS:raise ValueError('模板总网格超过5000000个单元')
    return {'entries':entries,'rows':row_count,'repeats':repeats,'sample_count':len(entries),
            'elements':list(element_columns.values()),'name_column':name_column,'sha256':hashlib.sha256(text.encode()).hexdigest(),
            'parameter_columns':list(overrides),'order':'CSV行优先，行内重复顺序','source_csv':text}
