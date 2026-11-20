"""Measured spectra from selected bytes only; bounded per-session upload cache."""
from collections import OrderedDict
import base64
import csv
import hashlib
import io
import json
import math
import posixpath
import threading
import time
import uuid
import zipfile
import sys
import xml.etree.ElementTree as ET

import numpy as np
from .spectrum_sif import decode as decode_sif, MAGIC
from .spectrum_avantes import decode as decode_avantes

MAX_BYTES=32_000_000
MAX_NODES=1_000_000
MAX_VALUES=4_000_000
MAX_RESPONSE=48_000_000
MAX_CELLS=4_000_000
MAX_CACHE=192_000_000
# Multi-file browsing: several documents stay cached side by side so the UI can
# overlay them. Oldest-inserted document is evicted first when any cap is hit.
MAX_DOCUMENTS=8
MAX_RAW=256_000_000
CACHE_TTL=21600
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def _xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('XLSX不允许DTD/实体')
    return ET.fromstring(data)


def _xlsx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries=z.infolist()
        if len(entries)>512 or sum(e.file_size for e in entries)>48_000_000:
            raise ValueError('XLSX展开大小/文件数超限')
        if any(e.file_size>24_000_000 or e.file_size>1000*max(1,e.compress_size) for e in entries):
            raise ValueError('XLSX压缩比或单文件过大')
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in _xml(z.read('xl/sharedStrings.xml')).findall('s:si',NS):
                shared.append(''.join(t.text or '' for t in si.iter('{'+NS['s']+'}t')))
        rels={r.attrib['Id']:r.attrib['Target'] for r in _xml(z.read('xl/_rels/workbook.xml.rels'))}
        tables=[];cells=0
        for sheet in _xml(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',NS):
            target=rels[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            path=posixpath.normpath('xl/'+target) if not target.startswith('/') else target.lstrip('/')
            if not path.startswith('xl/worksheets/'):raise ValueError('XLSX工作表目标非法')
            rows=[]
            for row in _xml(z.read(path)).findall('s:sheetData/s:row',NS):
                number=int(row.attrib.get('r',len(rows)+1))
                if number>1_000_002:raise ValueError('XLSX行数超限')
                values=[]
                for c in row.findall('s:c',NS):
                    col=0
                    for char in c.attrib.get('r','A'):
                        if not char.isalpha():break
                        col=col*26+ord(char.upper())-64
                    if not 1<=col<=128:raise ValueError('XLSX列数超限')
                    while len(values)<col:values.append('')
                    typ=c.attrib.get('t');v=c.find('s:v',NS)
                    text=v.text if v is not None and v.text is not None else ''
                    if typ=='s':text=shared[int(text)]
                    elif typ=='inlineStr':text=''.join(t.text or '' for t in c.iter('{'+NS['s']+'}t'))
                    elif typ=='e':text='Excel error: '+text
                    if c.find('s:f',NS) is not None and not text: text='Formula without cached value'
                    values[col-1]=text
                cells+=len(values)
                if cells>MAX_CELLS:raise ValueError('XLSX总单元格超限')
                rows.append((number,values))
            tables.append(dict(name=sheet.attrib['name'],rows=rows))
        if not tables:raise ValueError('XLSX没有工作表')
        return tables


def csv_rows(data):
    try:text=data.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:text=data.decode('gb18030')
        except UnicodeDecodeError:raise ValueError('CSV编码不是UTF-8或GB18030') from None
    sample=chr(10).join(line for line in text[:65536].splitlines() if line.strip() and not line.lstrip().startswith(('#','//')))
    try:delimiter=csv.Sniffer().sniff(sample,delimiters=',;\t').delimiter
    except csv.Error:delimiter=','
    rows=[];cells=0
    for i,row in enumerate(csv.reader(io.StringIO(text),delimiter=delimiter),1):
        if len(row)>128:raise ValueError('CSV列数超过128')
        cells+=len(row)
        if i>1_000_002 or cells>MAX_CELLS:raise ValueError('CSV行/单元格超限')
        rows.append((i,row))
    return rows,delimiter


def _number(value):
    try:out=float(value)
    except (TypeError,ValueError):return None
    return out if math.isfinite(out) else None


def _describe(table):
    rows=table['rows'];header=None;start=None;width=max((len(r) for _,r in rows),default=0)
    for line,row in rows:
        if sum(_number(v) is not None for v in row)>=2:start=line;break
        if row and not (row[0].strip().startswith(('#','//'))):header=row
    columns=[(header[i].strip() if header and i<len(header) and header[i].strip() else '列 '+str(i+1)) for i in range(width)]
    return dict(name=table['name'],columns=columns,recommended_start=start or 1,recommended_x=0,
                recommended_y=[1] if width>1 else [],preview=[dict(line=n,values=r) for n,r in rows[:12]])


def parse(data,name):
    if not data or len(data)>MAX_BYTES:raise ValueError('文件为空或超过32MB')
    if data.startswith(MAGIC):document=decode_sif(data)
    elif data[:3]==b'AVS' or name.lower().endswith(('.raw','.raw8','.roh','.trm','.abs','.ref','.drk')):
        document=decode_avantes(data)
    elif data[:2]==b'PK':
        document=dict(format='XLSX',tables=_xlsx(data))
    else:
        if any(v<9 or 13<v<32 for v in data[:4096]):raise ValueError('未知二进制格式；未按CSV猜读')
        rows,delimiter=csv_rows(data);document=dict(format='CSV',tables=[dict(name='CSV',rows=rows)],metadata=dict(delimiter=delimiter))
    document['name']=name.replace(chr(92),'/').split('/')[-1][:200]
    document['sha256']=hashlib.sha256(data).hexdigest();document['bytes']=len(data)
    return document


def _memory(value):
    if isinstance(value,np.ndarray):return int(value.nbytes)+128
    if isinstance(value,dict):return sys.getsizeof(value)+sum(_memory(k)+_memory(v) for k,v in value.items())
    if isinstance(value,(list,tuple)):return sys.getsizeof(value)+sum(_memory(v) for v in value)
    return sys.getsizeof(value)


def describe(document):
    return dict(name=document['name'],sha256=document['sha256'],bytes=document['bytes'],format=document['format'],
        metadata=document.get('metadata',{}),tables=[_describe(t) for t in document.get('tables',[])],
        frames=[dict(id=f['id'],label=f['label'],unit=f['unit'],nodes=len(f['x']),curves=list(f['curves']),metadata=f['metadata']) for f in document.get('frames',[])])


def select(document,options):
    if not isinstance(options,dict):raise ValueError('选择参数须为对象')
    if 'frames' in document:
        frame=next((f for f in document['frames'] if f['id']==str(options.get('frame','0'))),None)
        if frame is None:frame=document['frames'][0] if 'frame' not in options else None
        if frame is None:raise ValueError('帧/轨道不存在')
        names=options.get('curves',[next(iter(frame['curves']))])
        if not names or len(names)>16 or any(n not in frame['curves'] for n in names):raise ValueError('曲线选择非法')
        x=np.asarray(frame['x'],float);ys={n:np.asarray(frame['curves'][n],float) for n in names};unit=frame['unit'];selection=dict(frame=frame['id'],metadata=frame['metadata'])
    else:
        index=int(options.get('sheet',0))
        if not 0<=index<len(document['tables']):raise ValueError('工作表不存在')
        table=document['tables'][index];desc=_describe(table);start=int(options.get('start',desc['recommended_start']));xc=int(options.get('x',0));yc=options.get('y',[1]);unit=options.get('unit','nm')
        if unit not in ('nm','angstrom','um','pixel'):raise ValueError('轴单位须为nm/angstrom/um/pixel')
        if not isinstance(yc,list) or not 1<=len(yc)<=16 or xc in yc or len(set(yc))!=len(yc):raise ValueError('波长/强度列须不同且不重复')
        if min([xc]+yc)<0 or max([xc]+yc)>=len(desc['columns']):raise ValueError('所选列越界')
        values=[];skipped=[]
        for line,row in table['rows']:
            if line<start:continue
            if not any(str(v).strip() for v in row) or row[0].lstrip().startswith(('#','//')):skipped.append(line);continue
            nums=[_number(row[i]) if i<len(row) else None for i in [xc]+yc]
            if any(v is None for v in nums):raise ValueError(f'第{line}行所选列不是有限数值；可调整起始行/列，未静默删除')
            values.append(nums)
        if len(values)<2:raise ValueError('有效测量节点少于2')
        arr=np.asarray(values,float);x=arr[:,0];ys={str(i)+': '+desc['columns'][i]:arr[:,j+1] for j,i in enumerate(yc)}
        selection=dict(sheet=index,start=start,x_column=xc,y_columns=yc,skipped_blank_or_comment_rows=skipped[:100],skipped_count=len(skipped))
    if len(x)>MAX_NODES or len(x)*(len(ys)+1)>MAX_VALUES:raise ValueError('单谱超过1M节点或4M数值')
    factor={'nm':1.,'angstrom':.1,'um':1000.,'pixel':1.}[unit];x=x*factor
    output_unit='pixel' if unit=='pixel' else 'nm'
    if not np.isfinite(x).all() or any(not np.isfinite(y).all() for y in ys.values()):raise ValueError('轴/强度存在NaN/Inf')
    order=np.argsort(x,kind='stable');sorted_axis=not np.array_equal(order,np.arange(len(x)));x=x[order];ys={n:y[order] for n,y in ys.items()}
    duplicates=int(np.count_nonzero(np.diff(x)==0))
    if duplicates and options.get('duplicates','error')!='keep':raise ValueError(f'波长轴含{duplicates}个重复节点；选择“保留重复原值”或修正文件，不自动平均')
    if x[0]==x[-1]:raise ValueError('轴跨度为零')
    result=dict(name=document['name'],format=document['format'],sha256=document['sha256'],unit=output_unit,
        xs=x.tolist(),curves=[dict(id=n,label=n,ys=y.tolist()) for n,y in ys.items()],nodes=len(x),
        provenance=dict(selection=selection,original_unit=unit,unit_factor=factor,stable_sorted=sorted_axis,
                        duplicates_kept=duplicates,processing='none; negative values preserved; no normalization/dark subtraction/averaging'))
    encoded=json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(encoded)>MAX_RESPONSE:raise ValueError('所选数据JSON响应超过48MB；减少所选曲线')
    return result


class BrowserStore:
    """At most MAX_DOCUMENTS documents/MAX_RAW input bytes; bounded concurrency."""
    def __init__(self):
        self.documents=OrderedDict();self.lock=threading.RLock();self.gate=threading.BoundedSemaphore(2)
    def call(self,action,body,settings):
        if not isinstance(body,dict) or any(k in body for k in ('path','directory','filename_path')):raise ValueError('不接受任意文件路径')
        if not self.gate.acquire(blocking=False):raise ValueError('已有两个导入请求，请等待或取消')
        try:
            if action=='import':
                text=body.get('data','')
                if not isinstance(text,str) or len(text)>4*((MAX_BYTES+2)//3):raise ValueError('上传base64长度超限')
                try:data=base64.b64decode(text,validate=True)
                except (ValueError,TypeError):raise ValueError('上传不是有效base64') from None
                document=parse(data,str(body.get('name','selected-file')))
                document['_cache_bytes']=_memory(document)
                if document['_cache_bytes']>MAX_CACHE:raise ValueError('解析后内存超过192MB，减少文件规模')
                summary=describe(document);key=uuid.uuid4().hex
                with self.lock:
                    now=time.monotonic()
                    for old in [k for k,(stamp,d) in self.documents.items() if now-stamp>CACHE_TTL]:self.documents.pop(old)
                    while self.documents and (len(self.documents)>=MAX_DOCUMENTS or sum(d['bytes'] for _,d in self.documents.values())+len(data)>MAX_RAW or sum(d['_cache_bytes'] for _,d in self.documents.values())+document['_cache_bytes']>MAX_CACHE):self.documents.popitem(last=False)
                    self.documents[key]=(now,document)
                return dict(document=key,**summary)
            if action in ('select','process'):
                with self.lock:
                    item=self.documents.get(str(body.get('document','')))
                    if item is None:raise ValueError('导入缓存已过期，请重新选择文件')
                    document=item[1]
                measurement=select(document,body.get('options',{}))
                if action=='process':
                    from .spectrum_processing import process
                    result=process(measurement,str(body.get('curve','')),body.get('parameters',{}),body.get('reference_xs'))
                    if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode())>MAX_RESPONSE:
                        raise ValueError('处理结果响应超过48MB')
                    return result
                return measurement
            if action=='release':
                with self.lock:self.documents.pop(str(body.get('document','')),None)
                return dict(released=True)
            if action=='references':
                if body.get('source')=='nist':
                    if set(body) != {'source','element'}:raise ValueError('NIST仅接受元素符号，不接受URL或路径')
                    from .spectrum_nist import fetch
                    return fetch(str(body.get('element','')))
                from .spectrum_reference import configured,uploaded
                return uploaded(body) if 'data' in body else configured(settings['line_database'])
            raise ValueError('未知光谱浏览操作')
        finally:self.gate.release()
