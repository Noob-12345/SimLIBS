"""确定批量计划、逐样本checkpoint及新目录续跑；不覆盖原任务。"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import shutil
import numpy as np
import pandas as pd
from .models import Parameters,MAX_CELLS
from .storage import validate_compositions,save_result,read_manifest,write_json,write_csv,now,diagnostic_scope

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_version(settings,entries):
    root=Path(__file__).parent
    version={'algorithm':{name:file_sha(root/name) for name in ('models.py','adapter.py','mode_engine.py','offline_engine.py','offline_database.py','batch_pipeline.py','batch_template.py','operations.py','storage.py','training.py')}}
    if any(e['parameters']['webscraping']=='local' for e in entries):
        from .offline_database import library_signature
        version['library']=library_signature(settings.line_database)
    if any(e['parameters']['webscraping']!='local' for e in entries):version['source_library']=file_sha(Path(settings.source)/'simLIBS'/'simulation.py')
    return version


def make_plan(p,s,spec,compositions,planned=None):
    p=p.validated();spec=spec.validated(p,check_cells=planned is None)
    if planned is None:
        df=validate_compositions(compositions);elements=[c for c in df if c!='name'];rng=random.Random(spec.seed);entries=[]
        for _ in range(spec.size):
            row=df.iloc[rng.randrange(len(df))]
            actual=replace(p,elements=tuple(elements),percentages=tuple(float(row[e]) for e in elements),
                           Te=rng.uniform(spec.Te_min,spec.Te_max),Ne=rng.uniform(spec.Ne_min,spec.Ne_max)).validated()
            entries.append({'name':str(row['name']),'parameters':actual.to_dict()})
    else:
        entries=planned['entries']
        if len(entries)!=spec.size:raise ValueError('模板计划数与样本总数不一致')
        for entry in entries:Parameters.from_dict(entry['parameters'])
    if sum(Parameters.from_dict(e['parameters']).points for e in entries)>MAX_CELLS:raise ValueError('计划超过5000000个光谱单元')
    plan={'schema':1,'parameters':p.to_dict(),'spec':spec.__dict__,'entries':entries,
          'template':None if planned is None else {k:v for k,v in planned.items() if k!='entries'},'source_version':source_version(s,entries)}
    plan['hash']=digest(plan)
    return plan


def load_checkpoint(path,settings):
    checkpoint=read_manifest(path);plan=read_manifest(checkpoint['plan_path']);original_hash=plan['hash']
    candidate={k:v for k,v in plan.items() if k!='hash'}
    if digest(candidate)!=original_hash or checkpoint['plan_hash']!=original_hash:raise ValueError('计划/checkpoint哈希不匹配')
    if source_version(settings,plan['entries'])!=plan['source_version']:raise ValueError('库/算法版本已改变，不能混用原进度')
    samples=checkpoint['samples']
    if [r['index'] for r in samples]!=list(range(len(samples))) or len(samples)>len(plan['entries']):raise ValueError('checkpoint样本顺序损坏')
    for record in samples:
        if record['parameter_hash']!=digest(plan['entries'][record['index']]['parameters']):raise ValueError('样本参数与确定计划不符')
        for filename,expected in record['hashes'].items():
            if file_sha(filename)!=expected:raise ValueError('已完成样本/来源文件被修改，拒绝续跑')
        sample=read_manifest(record['manifest'])
        if digest(sample['origin']['parameters'])!=record['parameter_hash']:raise ValueError('样本实际参数不符')
    return plan,samples


def run_batch(p,s,spec,compositions,directory,emit,cancelled,simulator=None,planned=None,resume_checkpoint=None):
    p,s=p.validated(),s.validated();directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    if resume_checkpoint:plan,records=load_checkpoint(resume_checkpoint,s);records=[dict(r) for r in records]
    else:plan=make_plan(p,s,spec,compositions,planned);records=[]
    write_json(directory/'plan.json',plan)
    checkpoint={'schema':1,'plan_hash':plan['hash'],'plan_path':str(directory/'plan.json'),'samples':records,'status':'running'}
    entries=plan['entries'];elements=sorted({el for entry in entries for el in entry['parameters']['elements']})
    manifest={'kind':'batch','requested':len(entries),'completed':len(records),'partial':True,'parameters':plan['parameters'],
              'spec':plan['spec'],'samples':[r['manifest'] for r in records],'created_at':now(),'checkpoint':str(directory/'checkpoint.json'),
              'plan_hash':plan['hash'],'resume_from':resume_checkpoint,'resumable':True,
              'origin':{'kind':'simulation','label':'确定顺序模板/批量 · '+('离线本地' if p.webscraping=='local' else 'NIST在线')}}
    grid=None;rows=[]
    def collect(sample_path,index):
        nonlocal grid
        sample=read_manifest(sample_path);frame=pd.read_csv(sample['files']['interpolated'],float_precision='round_trip')
        axis=frame['wavelength'].to_numpy(float)
        if grid is None:grid=axis
        elif not np.array_equal(grid,axis):raise ValueError('批量网格不一致，不能伪装统一训练数据')
        params=sample['origin']['parameters'];labels=dict(zip(params['elements'],params['percentages']))
        rows.append(frame['intensity'].tolist()+[labels.get(el,0) for el in elements]+[entries[index]['name'],params['Te'],params['Ne']])
    for record in records:collect(record['manifest'],record['index'])
    def persist():
        manifest['completed']=len(records);manifest['samples']=[r['manifest'] for r in records]
        manifest['preview']=[dict({el:row[len(grid)+i] for i,el in enumerate(elements)},name=row[-3],**{'Te[eV]':row[-2],'Ne[cm^-3]':row[-1]}) for row in rows[:100]] if rows else []
        write_json(directory/'checkpoint.json',checkpoint);write_json(directory/'manifest.json',manifest)
    persist()
    try:
        if simulator is None:
            from .adapter import simulate
        else:simulate=simulator
        for index in range(len(records),len(entries)):
            if cancelled():break
            entry=entries[index];actual=Parameters.from_dict(entry['parameters'])
            emit('progress',message=f'样本 {index+1}/{len(entries)} · {entry["name"]}',current=index,total=len(entries),deadline=actual.deadline(s))
            sample_dir=directory/f'sample_{index+1:04d}'
            with diagnostic_scope(sample_dir):
                frames,origin=simulate(actual,s) if simulator is not None else simulate(actual,s,cancelled=cancelled,emit=emit)
            if simulator is None and actual.webscraping=='local' and origin.get('library')!=plan['source_version']['library']:
                raise ValueError('本地库在执行期间改变，拒绝将不同版本混入确定计划')
            origin.update(sample_name=entry['name'],template_row=entry.get('template_row'),repetition=entry.get('repetition'),plan_hash=plan['hash'])
            # Adapter line tables are written in the worker directory. Freeze each
            # sample's evidence before the next simulation overwrites that file.
            if origin.get('line_table'):
                sample_dir.mkdir(parents=True,exist_ok=True)
                source=Path(origin['line_table']);target=sample_dir/source.name
                if source.resolve()!=target.resolve():shutil.copyfile(source,target)
                origin['line_table']=str(target)
            path=save_result(sample_dir,frames,origin)
            collect(path,index)
            # Preserve HTML / official JS / response CSV as well as line tables.
            files=[str(file) for file in sample_dir.rglob('*') if file.is_file()]
            records.append({'index':index,'manifest':path,'parameter_hash':digest(entry['parameters']),'hashes':{filename:file_sha(filename) for filename in files}})
            persist();emit('progress',message=f'已完成 {len(records)}/{len(entries)}',current=len(records),total=len(entries))
        manifest['partial']=len(records)!=len(entries) or cancelled()
        checkpoint['status']='cancelled' if cancelled() else 'partial' if manifest['partial'] else 'packing'
        if rows:
            data=pd.DataFrame(rows,columns=[str(float(w)) for w in grid]+elements+['name','Te[eV]','Ne[cm^-3]'])
            target=directory/('dataset.partial.csv' if manifest['partial'] else 'dataset.csv');write_csv(target,data);manifest['dataset']=str(target)
        persist()
        if not manifest['partial']:
            from .training import build_training_package
            emit('progress',message='打包完整训练结果',deadline=600)
            manifest['training_package']=build_training_package(directory,manifest,cancelled)
            checkpoint['status']='completed';manifest['resumable']=False
        persist()
    except Exception as error:
        manifest['partial']=True;manifest['error']=str(error);manifest.pop('training_package',None)
        checkpoint['status']='failed';checkpoint['error']=str(error);persist();raise
    return str(directory/'manifest.json')
