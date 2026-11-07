"""专属任务进程入口。先等待父进程确认所有权，再做任何慢操作。"""
import json
import os
from pathlib import Path
import sys
import time
import traceback
from .models import Parameters
from .settings import Settings
from .storage import read_history, save_result, write_json


def execute(request, emit, cancelled):
    kind = request['kind']
    settings = Settings(**request['settings']).validated()
    directory = Path(request['directory'])
    if kind == 'advanced':
        from .advanced import simulate
        p = Parameters.from_dict(request['parameters'])
        frames, origin = simulate(p, settings, request['advanced'], cancelled, emit)
        if cancelled(): return None
        return save_result(directory / 'result', frames, origin)
    if kind == 'single':
        from .adapter import simulate
        p = Parameters.from_dict(request['parameters'])
        emit('progress', message='正在计算离线 LTE/Saha 光谱' if p.webscraping=='local' else '正在请求真实 NIST 光谱', deadline=p.deadline(settings))
        frames, origin = simulate(p, settings, cancelled=cancelled, emit=emit)
        if cancelled():
            return None
        return save_result(directory / 'result', frames, origin)
    if kind == 'history':
        frames, origin = read_history(request['path'])
        return save_result(directory / 'result', frames, origin)
    if kind == 'compositions':
        from .storage import read_compositions
        df = read_compositions(request['path'], request.get('name_column', 'name'))
        if len(df) > 5000:
            raise ValueError('组成 CSV 最多 5000 行，请拆分文件')
        path = directory / 'compositions.json'
        # 缺失数据保留空字符串供 UI 校验，绝不作为 0 提交。
        write_json(path, {'kind': 'compositions', 'columns': list(df), 'records': df.fillna('').to_dict('records'), 'path': request['path']})
        return str(path)
    if kind=='resume':
        from .batch_pipeline import load_checkpoint
        from .models import BatchSpec
        from .operations import batch
        import pandas as pd
        plan,_=load_checkpoint(request['checkpoint_path'],settings)
        p=Parameters.from_dict(plan['parameters'])
        return batch(p,settings,BatchSpec(**plan['spec']),pd.DataFrame(),directory/'result',emit,cancelled,resume_checkpoint=request['checkpoint_path'])
    if kind in ('batch', 'scan'):
        from .operations import batch, scan
        from .models import BatchSpec, ScanSpec
        p = Parameters.from_dict(request['parameters'])
        if kind == 'batch':
            import pandas as pd
            return batch(p, settings, BatchSpec(**request['spec']), pd.DataFrame(request['compositions']), directory / 'result', emit, cancelled,planned=request.get('template_plan'))
        return scan(p, settings, ScanSpec(**request['spec']), directory / 'result', emit, cancelled)
    if kind == 'export':
        from .operations import export_result
        emit('progress', message='正在后台导出完整数据/图像', deadline=600)
        export_result(request['manifest'], request['target'], request['format'], view=request.get('view', 'interpolated'),
                      title=request.get('title', 'Simulated LIBS'), color=request.get('color', '#2563eb'),
                      normalize=request.get('normalize', False), cancelled=cancelled)
        path = directory / 'export.json'
        write_json(path, {'kind': 'export', 'target': request['target'], 'format': request['format']})
        return str(path)
    raise ValueError(f'未知任务：{kind}')


def main():
    request_path = Path(sys.argv[1]).resolve()
    directory = request_path.parent
    request = json.loads(request_path.read_text(encoding='utf-8'))
    events = directory / 'events.jsonl'
    def emit(event, **payload):
        with events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(job_id=request['job_id'], event=event, **payload), ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
    cancelled = lambda: (directory / 'cancel').exists()
    # 启动门：父进程将 worker 纳入 Windows Job Object 后才创建 go 文件。
    limit = time.monotonic() + 10
    while not (directory / 'go').exists():
        if cancelled() or time.monotonic() > limit:
            return 2
        time.sleep(.02)
    os.environ['SIMLIBS_TASK_DIR'] = str(directory)
    try:
        path = execute(request, emit, cancelled)
        emit('cancelled' if cancelled() else 'success', path=path)
    except Exception as exc:
        if isinstance(exc, InterruptedError) and cancelled():
            emit('cancelled')
            return 0
        code = getattr(exc, 'code', 'task_error')
        write_json(directory / 'error.json', {'error': str(exc), 'code': code, 'traceback': traceback.format_exc()})
        emit('error', message=str(exc), code=code, log=str(directory / 'error.json'))
        return 1
    return 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
