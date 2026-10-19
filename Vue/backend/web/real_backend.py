"""simLIBS Web UI —— 使用 simlibs_ui 共享计算后台的真实接口适配。

复用现有任务体系：
- simlibs_ui.jobs.JobController：专属 worker 子进程、Windows Job Object 所有权、
  go 启动门、cancel 协作取消 + 0.8s 宽限树清理、deadline 超时、events.jsonl；
- simlibs_ui.worker.execute：真实 adapter.simulate / operations.batch / operations.scan；
- simlibs_ui.storage.save_result：结果 manifest（含来源证据：源 SHA256、NIST URL、
  实际 Ne、驱动版本），写入 Web 共享任务目录（output/.jobs/<task-id>/）。

Web 层职责仅两件事：把 events.jsonl 映射为 Web JobEvent 流；把 manifest 转译为
前端结果契约（xs/ys/yi、扫描帧缓存、批量摘要）。预览端点返回 501——真实引擎
不提供合成谱，前端将以明确标注的本地示意图占位。
"""
from __future__ import annotations

import os
import json
import math
import platform
import re
import socket
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from backend_api import (
    TERMINAL_STATUSES, ApiError, EventQueue, ExportPayload, JobEvent,
    CommonParams, SingleRequest, BatchRequest, ScanRequest,
)

from simlibs_ui.settings import Settings
from simlibs_ui.models import Parameters, ELEMENTS, intensity_scale_from_origin
from sampling import file_series, SINGLE_POINTS, SCAN_POINTS

AXIS_MAP = {'te': 'Te', 'ne': 'Ne', 'r': 'R'}
FRAME_PREVIEW_POINTS = SCAN_POINTS


class RealBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        state = Path(os.environ.get('SIMLIBS_STATE_DIR', str(UI_ROOT.parent / '.backend-state')))
        state.mkdir(parents=True, exist_ok=True)
        self._settings_path = state / '.web-settings.json'
        self._settings = self._load_settings()
        self._restore_session()
        # 预热：提前导入 adapter（pandas/selenium 等重依赖），
        # 避免首次打开页面时引擎状态接口阻塞数秒。
        threading.Thread(target=self._prewarm, daemon=True).start()

    def shutdown(self):
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.get('controller') and job['status'] not in TERMINAL_STATUSES:
                self.cancel(job['job_id'])
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if all(job['status'] in TERMINAL_STATUSES for job in jobs): break
            time.sleep(.05)
        self._persist_session()

    def _prewarm(self) -> None:
        try:
            import simlibs_ui.adapter  # noqa: F401
        except Exception:
            pass

    def _restore_session(self):
        """安全重启后保留已终结任务；只读本项目原有产物，不恢复活动进程。"""
        try:records=json.loads((self._settings_path.parent/'.web-session.json').read_text(encoding='utf-8')).get('jobs',[])
        except (OSError,ValueError,AttributeError):records=[]
        for record in reversed(records):
            jid=record.get('job_id','')
            if not re.fullmatch('[0-9a-f]{32}',jid):continue
            if record.get('status') not in TERMINAL_STATUSES:
                record=dict(record,status='failed',error='服务中断；已完成checkpoint可手动续跑')
            path=Path(record.get('result_path') or record.get('expected_result_path') or str(Path(self._settings.output)/'.jobs'/jid/'result'/'manifest.json'))
            manifest=None
            if record['status']=='completed':
                try:manifest=json.loads(path.read_text(encoding='utf-8'))
                except (OSError,ValueError):continue
            self._jobs[jid]=dict(record,manifest=manifest,result_path=str(path) if manifest else None,
                                 events=[JobEvent(**event) for event in record.get('events', [])],subs=[],controller=None,t0=time.monotonic())
        for checkpoint in (Path(self._settings.output)/'.jobs').glob('*/result/checkpoint.json'):
            jid=checkpoint.parents[1].name
            if jid in self._jobs or not re.fullmatch('[0-9a-f]{32}',jid):continue
            try:
                cp=json.loads(checkpoint.read_text(encoding='utf-8'));m=json.loads((checkpoint.parent/'manifest.json').read_text(encoding='utf-8'))
                status='completed' if cp.get('status')=='completed' and not m.get('partial') else 'failed'
                self._jobs[jid]={'job_id':jid,'kind':'批量模拟','status':status,'summary':f'恢复checkpoint · {m["completed"]}/{m["requested"]}',
                    'progress':m['completed']/m['requested']*100,'duration':'-','error':m.get('error') or ('服务中断；可手动续跑' if status=='failed' else None),
                    'created':datetime.fromtimestamp(checkpoint.stat().st_mtime).strftime('%m-%d %H:%M'),'manifest':m if status=='completed' else None,
                    'result_path':str(checkpoint.parent/'manifest.json'),'events':[],'subs':[],'controller':None,'t0':time.monotonic()}
            except (OSError,ValueError,KeyError):continue

    def _persist_session(self):
        from simlibs_ui.storage import write_json
        with self._lock:
            records=[{key:job.get(key) for key in ('job_id','kind','status','summary','progress','duration','error','created','resume_from','result_path','expected_result_path','created_at')} | {'events': [e.to_dict() for e in job.get('events', [])]} for job in reversed(list(self._jobs.values()))]
        write_json(self._settings_path.parent/'.web-session.json',{'jobs':records})

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------
    def _load_settings(self) -> Settings:
        data: Dict[str, Any] = {}
        try:
            data = json.loads(self._settings_path.read_text(encoding='utf-8'))
        except Exception:
            pass
        try:
            from simlibs_ui.library_settings import load_service_settings
            return load_service_settings(data)
        except Exception:
            return Settings().validated()

    # 前端字段名 → Settings 字段名
    _SET_MAP = {'page_load': 'page_timeout', 'output_dir': 'output'}

    def get_settings(self) -> Dict[str, Any]:
        s = self._settings
        return {
            'connect_timeout': s.connect_timeout, 'read_timeout': s.read_timeout,
            'page_load': s.page_timeout, 'static_deadline': s.static_deadline,
            'dynamic_deadline': s.dynamic_deadline, 'tls_verify': s.tls_verify,
            'python': s.python, 'chrome': s.chrome, 'driver': s.driver,
            'output_dir': s.output, 'source': s.source,
            'line_database_override': s.line_database_override,
            'line_database': s.line_database,
            'default_line_database': Settings().line_database,
        }

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(settings, dict):
            raise ApiError(400, '设置须为对象', 'validation')
        with self._lock:
            if 'settings_rollback' in settings:
                undo = getattr(self, '_settings_undo', None)
                if set(settings) != {'settings_rollback'} or not undo or settings['settings_rollback'] != undo[0] or self._settings is not undo[2]:
                    raise ApiError(409, '设置已变化，不能恢复过期保存', 'conflict')
                from simlibs_ui.storage import write_json
                write_json(self._settings_path, undo[1].to_dict())
                self._settings = undo[1]
                self._settings_undo = None
                return self.get_settings()
            previous = self._settings
            current = self._settings.to_dict()
            for key, value in settings.items():
                their = self._SET_MAP.get(key, key)
                if their in current and their not in ('source', 'line_database', 'line_database_override', 'python'):
                    current[their] = value
            try:
                candidate = Settings(**current).validated()
                if 'line_database_override' in settings:
                    from simlibs_ui.library_settings import with_library_override
                    candidate = with_library_override(candidate, settings['line_database_override'])
            except (ValueError, TypeError, OSError) as exc:
                raise ApiError(400, str(exc), 'validation') from exc
            from simlibs_ui.storage import write_json
            write_json(self._settings_path, candidate.to_dict())
            self._settings = candidate
            # Restore exactly the server-owned prior snapshot, including unavailable
            # custom media. A token cannot validate/bypass an arbitrary user path.
            token = uuid.uuid4().hex
            self._settings_undo = (token, previous, candidate)
            return dict(self.get_settings(), settings_rollback=token)

    # ------------------------------------------------------------------
    # 引擎状态 / 默认参数 / 预览
    # ------------------------------------------------------------------
    def api_version(self) -> str:
        return '1'

    def engine_status(self, mode='local') -> Dict[str, Any]:
        with self._lock:
            running = sum(1 for j in self._jobs.values() if j['status'] in ('queued', 'running'))
        s = self._settings
        if mode=='local':
            from simlibs_ui.offline_database import capabilities
            return {'engine':'simlibs','engine_label':'离线本地 · LTE/Saha','python':platform.python_version(),
                    'nist':'本地模式：禁用网络探针','nist_ok':False,'chrome':'本地无需Chrome','jobs_running':running,
                    'local':capabilities(s.line_database),'network_used':False}
        nist_ok, nist_label = self._probe_nist()
        try:
            from simlibs_ui.adapter import chrome_version
            chrome_label = 'Chrome ' + chrome_version(s)
        except Exception:
            chrome_label = '未检测到'
        driver_label = s.driver if s.driver else '启动任务时自动获取匹配版本'
        return {
            'engine': 'simlibs', 'engine_label': '真实引擎 · simLIBS',
            'api_version': self.api_version(), 'python': platform.python_version(),
            'nist': nist_label, 'nist_ok': nist_ok,
            'chrome': chrome_label, 'driver': driver_label,
            'jobs_running': running,
        }

    @staticmethod
    def _probe_nist():
        t0 = time.monotonic()
        try:
            with socket.create_connection(('physics.nist.gov', 443), timeout=2.5):
                ms = (time.monotonic() - t0) * 1000
                return True, f'TCP 可达 · {ms:.0f} ms'
        except OSError:
            return False, '不可达（检查网络/代理）'

    def default_params(self) -> Dict[str, Any]:
        p = Parameters(elements=('Fe',),percentages=(100,),low_w=200,upper_w=500,max_ion_charge=2,broadening='local',broaden_convention='physics')
        return {
            'params': {
                'te': p.Te, 'ne': p.Ne, 'resolution': p.resolution,
                'low_w': p.low_w, 'up_w': p.upper_w, 'max_ion_charge': p.max_ion_charge,
                'mode': 'local', 'mode_version':2, 'headless': p.headless, 'resample': p.resample,
                'intensity_scale': p.intensity_scale,
                'broadening': p.broadening, 'broaden_convention': p.broaden_convention,
                'broaden_grid_step': .01,
                'broaden_center_decimals': p.broaden_center_decimals,
                'broaden_min_rel_int': p.broaden_min_rel_int,
                'local_temperature_mode':'linked','local_temperature_K':0,
                'local_broadening_enabled':False,
            },
            'composition': [{'el': e, 'pct': pct} for e, pct in zip(p.elements, p.percentages)],
            'element_symbols': sorted(ELEMENTS),
            'local_capabilities':self.engine_status('local')['local'],
            'title': 'Fe 100% · 离线本地 LTE/Saha',
        }

    def preview(self, params: CommonParams, elements: List[str]) -> Dict[str, Any]:
        # 真实引擎不做合成预览（防止冒充 NIST 数据）；前端回退为明确标注的示意图。
        raise ApiError(501, '真实引擎不提供运行前预览；运行任务后显示真实光谱', 'unavailable')

    # ------------------------------------------------------------------
    # 任务启动
    # ------------------------------------------------------------------
    @staticmethod
    def _to_parameters(params: CommonParams, composition) -> Parameters:
        return Parameters(
            Te=params.te, Ne=params.ne, resolution=params.resolution,
            low_w=params.low_w, upper_w=params.up_w,
            max_ion_charge=params.max_ion_charge, webscraping=params.mode,
            mode_version=params.mode_version,
            headless=params.headless,
            elements=tuple(c.el for c in composition),
            percentages=tuple(float(c.pct) for c in composition),
            step=float(params.resample_step), resample=params.resample,
            intensity_scale=params.intensity_scale,
            broadening=params.broadening,
            broaden_convention=params.broaden_convention,
            broaden_grid_step=params.broaden_grid_step,
            broaden_center_decimals=params.broaden_center_decimals,
            broaden_min_rel_int=params.broaden_min_rel_int,
            local_gaussian_nm=params.local_gaussian_nm,local_lorentz_nm=params.local_lorentz_nm,local_temperature_K=params.local_temperature_K,local_temperature_mode=params.local_temperature_mode,local_broadening_enabled=params.local_broadening_enabled,
        )

    def start_single(self, req: SingleRequest) -> str:
        settings = self._settings
        p = self._to_parameters(req.params, req.composition)
        self._validate_local(p, settings=settings)
        payload = {'parameters': p.to_dict()}
        summary = (f"{req.params.summary()} · "
                   + " / ".join(f"{it.el} {it.pct:g}%" for it in req.composition))
        return self._launch('单次模拟', 'single', payload, summary, settings=settings)

    def start_advanced(self, body):
        from simlibs_ui.advanced import effective
        req=SingleRequest.from_api(body)
        p=self._to_parameters(req.params, req.composition)
        try:
            # The paper engine has its own Stark/I-II-III coverage contract;
            # ordinary local-library preflight cannot validate these inputs.
            _,config,_=effective(p,body.get('advanced',{}))
        except (ValueError,TypeError) as error:raise ApiError(400,str(error),'validation') from error
        label = '高级NIST逐线自吸收' if config.get('model') == 'nist' else '高级论文 Eq.7 · Stark逐线自吸收'
        return self._launch('高级模拟','advanced',{'parameters':p.to_dict(),'advanced':config},label+' / 参数化基体（未标定）')

    def start_batch(self, req: BatchRequest) -> str:
        settings = self._settings
        p = self._to_parameters(req.params, req.compositions[0].items)
        rows = []
        for comp in req.compositions:
            row = {'name': comp.name}
            for it in comp.items:
                row[it.el] = float(it.pct)
            rows.append(row)
        elements = sorted({item.el for comp in req.compositions for item in comp.items})
        rows = [dict({el: 0.0 for el in elements}, **row) for row in rows]
        spec = {
            'size': req.n_samples, 'seed': req.seed, 'batch_size': req.batch_size,
            'Te_min': req.te_range[0], 'Te_max': req.te_range[1],
            'Ne_min': 10 ** req.ne_range[0], 'Ne_max': 10 ** req.ne_range[1],
        }
        payload = {'parameters': p.to_dict(), 'spec': spec, 'compositions': rows}
        if req.template_plan is not None:payload['template_plan']=req.template_plan
        self.validate_batch(req, settings=settings)
        summary = f'{req.n_samples} 样本 · seed={req.seed} · {req.params.summary()}'
        return self._launch('批量模拟', 'batch', payload, summary, settings=settings)

    def resume(self,job_id):
        from simlibs_ui.batch_pipeline import load_checkpoint
        with self._lock:
            job=self._jobs.get(job_id)
            if not job:raise ApiError(404,'原任务不存在','not_found')
            if job['status'] not in TERMINAL_STATUSES:raise ApiError(409,'活动任务不能续跑','conflict')
            active=self.__dict__.setdefault('_resume_active',{})
            if job_id in active:raise ApiError(409,'该任务正在续跑','conflict')
            active[job_id]=None
        settings = self._settings
        path=Path(job.get('expected_result_path') or job.get('result_path') or str(Path(settings.output)/'.jobs'/job_id/'result'/'manifest.json')).parent/'checkpoint.json'
        try:
            if not path.is_file():raise ApiError(409,'旧任务没有确定计划/checkpoint，不能伪造恢复','no_checkpoint')
            plan,records=load_checkpoint(path,settings)
            if json.loads(path.read_text(encoding='utf-8')).get('status')=='completed':raise ApiError(409,'完整任务已成功，无需续跑','conflict')
            jid=self._launch('批量模拟','resume',{'checkpoint_path':str(path)},f'续跑 {job_id} · 已完成{len(records)}/{len(plan["entries"])}',settings=settings)
            with self._lock:
                self._jobs[jid]['resume_from']=job_id
                if self._jobs[jid]['status'] in TERMINAL_STATUSES:active.pop(job_id,None)
                else:active[job_id]=jid
            self._persist_session()
            return jid
        except Exception as error:
            with self._lock:active.pop(job_id,None)
            if isinstance(error,(ValueError,OSError,KeyError)):raise ApiError(409,f'checkpoint校验失败：{error}','checkpoint') from error
            raise

    def validate_batch(self,req,settings=None):
        if req.params.mode!='local':return
        settings = settings or self._settings
        from simlibs_ui.offline_database import capabilities
        report=capabilities(settings.line_database)
        if req.template_plan:
            for entry in req.template_plan['entries']:self._validate_local(Parameters.from_dict(entry['parameters']),report,settings)
        else:
            for comp in req.compositions:self._validate_local(self._to_parameters(req.params,comp.items),report,settings)

    def _validate_local(self,p,report=None,settings=None):
        if p.webscraping!='local':return
        from simlibs_ui.offline_database import preflight
        try:preflight(p,(settings or self._settings).line_database,report)
        except (OSError,ValueError,KeyError,TypeError) as error:raise ApiError(400,str(error),'validation') from error

    def start_scan(self, req: ScanRequest) -> str:
        settings = self._settings
        p = self._to_parameters(req.params, req.composition)
        self._validate_local(p, settings=settings)
        axis = AXIS_MAP[req.axis]
        # Web 契约的 Ne 轴以 10^ 指数表达；真实扫描使用绝对 Ne。
        start = 10 ** req.start if req.axis == 'ne' else req.start
        stop = 10 ** req.end if req.axis == 'ne' else req.end
        spec = {'axis': axis, 'start': start, 'stop': stop, 'count': req.frames, 'step': None}
        comp_txt = " / ".join(f"{it.el} {it.pct:g}%" for it in req.composition)
        payload = {'parameters': p.to_dict(), 'spec': spec}
        summary = f'{axis} {req.start:g}→{req.end:g} · {req.frames} 帧 · {req.params.summary()} · {comp_txt}'
        return self._launch('扫描动画', 'scan', payload, summary, settings=settings)

    def _launch(self, kind_label: str, worker_kind: str, payload: Dict[str, Any], summary: str, *, settings=None) -> str:
        from simlibs_ui.jobs import JobController
        controller = JobController(settings or self._settings)
        try:
            job_id = controller.start(worker_kind, **payload)
        except ValueError as exc:
            raise ApiError(400, str(exc), 'validation')
        except Exception as exc:
            raise ApiError(500, f'任务启动失败：{exc}')
        job = {
            'job_id': job_id, 'kind': kind_label, 'status': 'queued', 'summary': summary,
            'progress': 0.0, 'duration': '-', 'error': None,
            'created': datetime.now().strftime('%m-%d %H:%M'), 'created_at': datetime.now().isoformat(),
            'expected_result_path': str(controller.directory/'result'/'manifest.json'),
            'events': [], 'subs': [], 'controller': controller,
            't0': time.monotonic(), 'result_path': None, 'manifest': None,
        }
        with self._lock:
            self._jobs[job_id] = job
        self._persist_session()
        self._emit(job_id, 'log', message=f'[worker] 已提交真实引擎（{worker_kind}）· 专属子进程 + Job Object', level='info')
        threading.Thread(target=self._poll_loop, args=(job_id,), daemon=True).start()
        return job_id

    # ------------------------------------------------------------------
    # 事件：events.jsonl → Web JobEvent
    # ------------------------------------------------------------------
    def _emit(self, jid: str, ev_type: str, message: str = '', level: str = 'info',
              status: Optional[str] = None, progress: Optional[float] = None,
              final: bool = False) -> None:
        with self._lock:
            job = self._jobs[jid]
            ev = JobEvent(seq=len(job['events']), ts=datetime.now().strftime('%H:%M:%S'),
                          job_id=jid, type=ev_type, message=message, level=level,
                          status=status, progress=progress, final=final)
            job['events'].append(ev)
            for q in list(job['subs']):
                q.push(ev)
            if status:
                job['status'] = status
            if progress is not None:
                job['progress'] = progress
        try:
            print(f'[{ev.ts}] {jid} {ev.type} {status or ""} {message}', flush=True)
        except Exception:
            pass

    def _poll_loop(self, job_id: str) -> None:
        job = self._jobs[job_id]
        controller = job['controller']
        while True:
            try:
                messages = controller.poll()
            except Exception as exc:
                self._finish(job_id, 'failed', error=f'任务轮询异常：{exc}')
                return
            for m in messages:
                event = m.get('event')
                if event == 'progress':
                    current, total = m.get('current'), m.get('total')
                    pct = None
                    if isinstance(current, (int, float)) and isinstance(total, (int, float)) and total:
                        pct = round(current / total * 100, 1)
                    self._emit(job_id, 'log', message=m.get('message', ''), level='info', progress=pct)
                    if pct is not None:
                        self._emit(job_id, 'progress', progress=pct)
                elif event == 'success':
                    with self._lock:
                        job['result_path'] = m.get('path')
                elif event == 'error':
                    self._emit(job_id, 'log', message=f"[error] {m.get('message', '')}", level='error')
                elif event == 'cancelled':
                    with self._lock:
                        job['result_path'] = m.get('path') or job['result_path']
                elif event == 'finished':
                    state = m.get('state')
                    if state == 'SUCCEEDED':
                        self._finish_success(job_id)
                    elif state == 'CANCELLED':
                        self._finish(job_id, 'cancelled')
                    else:
                        self._finish(job_id, 'failed', error=m.get('message') or controller.error)
                    return
            if job['status'] in TERMINAL_STATUSES:
                return
            time.sleep(0.12)

    def _finish_success(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            controller = job['controller']
            job['manifest'] = controller.last_result
            job['result_path'] = controller.result_path or job['result_path']
            job['duration'] = f'{time.monotonic() - job["t0"]:.1f} s'
            origin = (job['manifest'] or {}).get('origin') or {}
        # 数据路径证据先于完成日志：实际 R 警告与展宽/计算位置
        if origin.get('resolution_warning'):
            self._emit(job_id, 'log', message=f"[warn] {origin['resolution_warning']}", level='warn')
        if origin.get('broadening') == 'local':
            params = origin.get('broadening_params') or {}
            self._emit(job_id, 'log',
                       message=(f"[done] 本地展宽 · 线表 {origin.get('line_table_rows', '?')} 行 · "
                                f"合成网格 {params.get('grid_step')} nm · 约定 {params.get('convention')}"),
                       level='ok', progress=100)
        self._emit(job_id, 'log',
                   message=f'[done] manifest 就绪 · {job["result_path"]}（完整来源证据）',
                   level='ok', progress=100)
        self._emit(job_id, 'progress', progress=100)
        self._finish(job_id, 'completed')

    def _finish(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job['status'] in TERMINAL_STATUSES:
                return
            job['duration'] = f'{time.monotonic() - job["t0"]:.1f} s'
            if error:
                job['error'] = error
        if status == 'cancelled':
            self._emit(job_id, 'log', message='[ui] 已取消 · 保留上一次成功结果', level='warn')
        self._emit(job_id, 'status', status=status, final=True)
        with self._lock:
            active=self.__dict__.get('_resume_active',{})
            for origin,child in list(active.items()):
                if child==job_id:active.pop(origin,None)
        self._persist_session()

    # ------------------------------------------------------------------
    # 查询 / 取消
    # ------------------------------------------------------------------
    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job['status'] in TERMINAL_STATUSES:
                return False
        try:
            job['controller'].cancel()
        except Exception:
            return False
        self._emit(job_id, 'log', message='[ui] 已发送协作取消标记 · 0.8 秒宽限后清理任务进程树（含浏览器）', level='warn')
        return True

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = [self._job_view(j) for j in self._jobs.values()]
        return list(reversed(jobs))

    def _job_view(self, job: Dict[str, Any]) -> Dict[str, Any]:
        view={k:job.get(k) for k in ('job_id','kind','status','summary','progress','duration','error','created','created_at','resume_from')}
        if job.get('kind') == '高级模拟' and job.get('status') == 'failed':
            error_file = self._advanced_file(job, 'stark-error.json') or self._advanced_file(job, 'error.json')
            if error_file and error_file.stat().st_size <= 65536:
                try:
                    failure = json.loads(error_file.read_text(encoding='utf-8'))
                    if isinstance(failure.get('code'), str):
                        view['error_code'] = failure['code']
                except (OSError, ValueError, AttributeError):
                    pass
            summary = self._advanced_file(job, 'missing-stark.json')
            artifact = self._advanced_file(job, 'missing-stark.csv')
            if summary and artifact and summary.stat().st_size <= 4_000_000 and view.get('error_code', 'missing_stark') == 'missing_stark':
                try:
                    data = json.loads(summary.read_text(encoding='utf-8'))
                    if data.get('code') == 'missing_stark' and isinstance(data.get('count'), int):
                        view['stark_missing'] = {'count': data['count'], 'available': True}
                        if isinstance(data.get('matched_count'), int):
                            view['stark_matched'] = {'count': data['matched_count'], 'available': bool(data['matched_count']) and self._advanced_file(job, 'matched-stark.csv') is not None}
                except (OSError, ValueError, AttributeError):
                    pass
        path=Path(job.get('expected_result_path') or job.get('result_path') or str(Path(self._settings.output)/'.jobs'/job['job_id']/'result'/'manifest.json')).parent/'checkpoint.json'
        if path.is_file():
            try:
                checkpoint=json.loads(path.read_text(encoding='utf-8'));plan=json.loads(Path(checkpoint['plan_path']).read_text(encoding='utf-8'))
                view.update(resumable=job['status'] in TERMINAL_STATUSES and checkpoint.get('status')!='completed',completed_samples=len(checkpoint['samples']),total_samples=len(plan['entries']))
            except (OSError,ValueError,KeyError):view.update(resumable=False,resume_reason='checkpoint/计划损坏，原结果保留')
        else:view.update(resumable=False,resume_reason='无确定计划的旧任务仅保留已有结果')
        return view

    @staticmethod
    def _advanced_file(job, name):
        # Only fixed files belonging to this already-authorized job; never a client path.
        if name not in ('missing-stark.json', 'missing-stark.csv', 'matched-stark.csv', 'matched-stark.json',
                        'advanced-lines.csv', 'advanced-lines.json', 'stark-error.json', 'error.json'):
            return None
        manifest = job.get('expected_result_path') or job.get('result_path')
        if not manifest:
            return None
        root = Path(manifest).resolve().parent.parent
        file = root/name
        return file if file.is_file() and file.resolve().parent == root else None

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ApiError(404, f'任务不存在：{job_id}', 'not_found')
            view = self._job_view(job)
            view['events'] = [ev.to_dict() for ev in job['events']]
        return view

    def subscribe(self, job_id: str) -> EventQueue:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ApiError(404, f'任务不存在：{job_id}', 'not_found')
            q = EventQueue()
            job.setdefault('subs', []).append(q)
        return q

    # ------------------------------------------------------------------
    # 结果转译：manifest → 前端契约
    # ------------------------------------------------------------------
    def get_result(self, job_id: str, frame: Optional[int] = None, sample: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise ApiError(404, f'任务不存在：{job_id}', 'not_found')
        if job['status'] != 'completed' or not job.get('manifest'):
            raise ApiError(409, f'任务尚未成功完成（当前 {job["status"]}）', 'no_result')
        manifest = job['manifest']
        kind = manifest.get('kind')
        if kind == 'spectrum':
            return self._single_result(job, manifest)
        if kind == 'scan':
            if frame is not None:
                paths=manifest.get('frames') or []
                if not 0<=frame<len(paths):raise ApiError(400,'扫描帧号越界','validation')
                fm=json.loads(Path(paths[frame]).read_text(encoding='utf-8'))
                data=self._single_result(job,fm)
                return dict(data,value=(manifest.get('completed_values') or [])[frame],frame=frame)
            return self._scan_result(job, manifest)
        if kind == 'batch':
            if sample is not None:
                paths = manifest.get('samples') or []
                if not 0 <= sample < len(paths): raise ApiError(400, '样本号越界', 'validation')
                return self._single_result(job, json.loads(Path(paths[sample]).read_text(encoding='utf-8')))
            return self._batch_result(job, manifest)
        raise ApiError(500, f'未知结果类型：{kind}')

    @staticmethod
    def _interp_preview(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
        preview = manifest.get('preview') or {}
        return preview.get('interpolated') or preview.get('raw') or []

    def _single_result(self, job: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
        series = file_series(manifest, SINGLE_POINTS)
        main = series.get('interpolated') or series['raw']
        xs, ys = main['xs'], main['ys']
        origin = manifest.get('origin') or {}
        counts = manifest.get('counts') or {}
        rows = ' · '.join(f"{k} {v:,}" for k, v in counts.items())
        meta = {
            'source': origin.get('label', '真实 NIST / SimulatedLIBS 模拟'),
            'rows': rows or None,
            'points': f'{main["label"]}：显示 {len(xs):,}/{main["total_points"]:,} 实际CSV节点（完整）',
            'duration': job.get('duration'),
            'sha256': ((origin.get('source_sha256') or '')[:4] + '…') or None,
            'ne_actual': origin.get('actual_Ne'),
            'nist_url': origin.get('nist_url'),
            'ion_total': origin.get('ion_total'),
            'intensity_scale':intensity_scale_from_origin(origin),
            'intensity_units':'a.u. (relative flux)',
            'ions':[s['label'] for s in series['ions']],
            # 数据抓取模式重塑证据（2026-10-03）
            'computation_location': origin.get('computation_location'),
            'broadening': origin.get('broadening'),
            'broadening_params': origin.get('broadening_params'),
            'actual_resolution': origin.get('actual_resolution'),
            'requested_resolution':origin.get('requested_resolution') or (origin.get('parameters') or {}).get('resolution'),
            'initial_server_resolution':origin.get('initial_server_resolution'),
            'mode_version':origin.get('mode_version',1),'mode':origin.get('mode'),
            'resolution_warning': origin.get('resolution_warning'),
            'line_table_rows': origin.get('line_table_rows'),
            'spectrum_style':origin.get('spectrum_style','continuous'),'local_broadening_enabled':origin.get('local_broadening_enabled'),
        }
        result = {'kind': 'single', 'xs': xs, 'ys': ys, 'yi': [], 'series': series, 'meta': meta, 'origin': origin, 'manifest': manifest}
        if origin.get('mode')=='advanced':
            import pandas as pd
            if origin.get('nist_line_table') and Path(origin['nist_line_table']).is_file():
                sticks = pd.read_csv(origin['nist_line_table'], float_precision='round_trip')
                result['origin'] = dict(result['origin'], nist_line_sticks=sticks.to_dict(orient='records'))
            if origin.get('thin_reference') and Path(origin['thin_reference']).is_file():
                reference=pd.read_csv(origin['thin_reference'],float_precision='round_trip')
                if {'wavelength', 'intensity', 'nominal_intensity'} <= set(reference):
                    result['comparison']={'xs':reference['wavelength'].tolist(),'thin':reference['intensity'].tolist(),'nominal':reference['nominal_intensity'].tolist()}
            # Optional paper metadata (e.g. unreported Stark temperature) is
            # exported as an empty CSV cell and must round-trip to JSON null.
            typed_lines = self._advanced_file(job, 'advanced-lines.json')
            if typed_lines:
                result['origin'] = dict(result['origin'], line_diagnostics=json.loads(typed_lines.read_text(encoding='utf-8')))
            elif origin.get('line_table') and Path(origin['line_table']).is_file():
                diagnostics=pd.read_csv(origin['line_table'],float_precision='round_trip').astype(object)
                diagnostics=diagnostics.where(pd.notna(diagnostics),None)
                result['origin']=dict(result['origin'],line_diagnostics=diagnostics.to_dict(orient='records'))
        return result

    def _scan_result(self, job: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
        axis = str(manifest.get('axis', 'Te')).lower()
        values = manifest.get('completed_values') or []
        frames_out = []
        paths = manifest.get('frames') or []
        if len(values) != len(paths):
            raise ApiError(500, '扫描帧与参数数量不一致')
        for value, frame_path in zip(values, paths):
            fm = json.loads(Path(frame_path).read_text(encoding='utf-8'))
            # Web 契约：Ne 轴以 10^ 指数表达
            display = math.log10(float(value)) if axis == 'ne' else float(value)
            frames_out.append({
                'value': display, 'loaded':False,'actual_resolution':(fm.get('origin') or {}).get('actual_resolution'),
                'intensity_scale':intensity_scale_from_origin(fm.get('origin')),
            })
        p = manifest.get('parameters') or {}
        params_summary = (f"Te={p.get('Te', 0):g} eV · Ne={p.get('Ne', 0):.3g} · "
                          f"R{p.get('resolution', 0)} · {p.get('low_w', 0):g}–{p.get('upper_w', 0):g} nm")
        return {'kind': 'scan', 'axis': axis, 'unit': {'te': ' eV', 'ne': '×10^x cm⁻³', 'r': ''}[axis],
                'manifest': manifest, 'frames': frames_out, 'params_summary': params_summary,'lazy_frames':True,'job_id':job.get('job_id'),
                'intensity_scale':frames_out[0]['intensity_scale'] if frames_out else 'unknown','intensity_units':'a.u. (relative flux)'}

    def _batch_result(self, job: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
        import pandas as pd
        samples = []
        for path in manifest.get('samples') or []:
            item = json.loads(Path(path).read_text(encoding='utf-8'))
            origin = item.get('origin') or {}; p = origin.get('parameters') or {}
            samples.append({'name': origin.get('sample_name', ''), 'parameters': p,
                            'composition': [{'el': el, 'pct': pct} for el, pct in zip(p.get('elements', []), p.get('percentages', []))]})
        wide = {'cols': [], 'rows': [], 'note': '批量宽表'}
        dataset = manifest.get('dataset')
        if dataset and Path(dataset).is_file():
            try:
                df = pd.read_csv(dataset, nrows=3)
                cols = list(df.columns)
                meta_cols = [c for c in cols if c in ('name', 'Te[eV]', 'Ne[cm^-3]')] or cols[-3:]
                elements = [c for c in cols if c not in meta_cols][:2]
                show = elements + ['…'] + meta_cols
                wide['cols'] = [c if c == '…' else str(c) for c in show]
                wide['rows'] = [
                    [('…' if c == '…' else (f'{float(df.iloc[i][c]):.4g}' if c not in ('name',) else str(df.iloc[i][c])))
                     for c in show]
                    for i in range(min(3, len(df)))
                ]
                wide['note'] = f'宽表共 {len(cols):,} 列 · 仅展示首尾（完整数据见数据集导出）'
            except Exception:
                pass
        return {
            'kind': 'batch',
            'intensity_scale':(manifest.get('parameters') or {}).get('intensity_scale','unknown'),
            'intensity_units':'a.u. (relative flux)',
            'summary': {'total': manifest.get('requested', 0), 'completed': manifest.get('completed', 0),
                        'failed': 0, 'partial': bool(manifest.get('partial'))},
            'samples': samples, 'wide': wide, 'manifest': manifest,
            'training_package': ({k: v for k, v in manifest['training_package'].items()
                                  if k not in ('archive', 'manifest')}
                                 if not manifest.get('partial') and manifest.get('training_package')
                                 else {'available': False, 'reason': '此任务没有完整训练包；重新运行批量模拟后可下载'}),
            'actual_parameters_available':bool(manifest.get('actual_parameters')),'template_csv_available':bool(manifest.get('template_csv')),
        }

    # ------------------------------------------------------------------
    # 导出（复用 simlibs_ui.operations.export_result：全量数据 / 真实 PNG/GIF）
    # ------------------------------------------------------------------
    def export(self, job_id: str, kind: str, frame: Optional[int] = None) -> ExportPayload:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise ApiError(404, f'任务不存在：{job_id}', 'not_found')
        if kind in ('stark-missing', 'stark-matched'):
            name = 'missing-stark.csv' if kind == 'stark-missing' else 'matched-stark.csv'
            path = self._advanced_file(job, name) if job.get('kind') == '高级模拟' and job.get('status') == 'failed' else None
            if not path:
                raise ApiError(409, '此失败任务没有对应Stark诊断清单', 'no_result')
            return ExportPayload(path.read_bytes(), 'text/csv; charset=utf-8', f'{job_id}_{name.replace("-", "_")}')
        if kind == 'stark-report':
            report = self._advanced_file(job, 'stark-error.json') if job.get('kind') == '高级模拟' and job.get('status') == 'failed' else None
            if not report:
                raise ApiError(409, '此失败任务没有Stark报告', 'no_result')
            payload = {'error': json.loads(report.read_text(encoding='utf-8'))}
            for key, name in (('missing', 'missing-stark.json'), ('matched', 'matched-stark.json')):
                file = self._advanced_file(job, name)
                if file and payload['error'].get('code') == 'missing_stark':
                    payload[key] = json.loads(file.read_text(encoding='utf-8'))
            return ExportPayload(json.dumps(payload, ensure_ascii=False, allow_nan=False), 'application/json', f'{job_id}_stark_report.json')
        if job['status'] != 'completed' or not job.get('result_path'):
            raise ApiError(409, '只有成功完成的任务才能导出', 'no_result')
        manifest, result_path = job['manifest'], job['result_path']
        if kind == 'diagnostics':
            path = self._advanced_file(job, 'advanced-lines.csv') if manifest.get('origin', {}).get('mode') == 'advanced' else None
            if not path:
                raise ApiError(409, '此历史结果没有逐线诊断表', 'no_result')
            return ExportPayload(path.read_bytes(), 'text/csv; charset=utf-8', f'{job_id}_line_diagnostics.csv')
        if manifest.get('origin',{}).get('mode')=='advanced' and kind in ('csv','json','png'):
            import pandas as pd
            import io
            result=self._single_result(job,manifest)
            if kind=='json':
                if manifest['origin'].get('opacity_table') and Path(manifest['origin']['opacity_table']).is_file():
                    result['opacity']=pd.read_csv(manifest['origin']['opacity_table'],float_precision='round_trip').to_dict(orient='list')
                return ExportPayload(json.dumps(result,ensure_ascii=False,allow_nan=False),'application/json',f'{job_id}_advanced.json')
            if 'comparison' not in result:
                # Earliest saved advanced results may have no three-spectrum files.
                if kind == 'csv':
                    return ExportPayload(pd.DataFrame({'wavelength': result['xs'], 'intensity': result['ys']}).to_csv(index=False), 'text/csv; charset=utf-8', f'{job_id}_advanced.csv')
                from simlibs_ui.operations import export_result
                from tempfile import TemporaryDirectory
                with TemporaryDirectory() as temporary:
                    target = Path(temporary)/'saved.png'
                    export_result(result_path, target, 'png')
                    return ExportPayload(target.read_bytes(), 'image/png', f'{job_id}_advanced.png')
            if kind=='csv':
                data={'wavelength':result['xs'],'corrected':result['ys'],'matrix_thin':result['comparison']['thin'],'nominal_thin':result['comparison']['nominal']}
                for curve in result['series']['elements']['interpolated']['curves']:data[curve['label']+'_corrected']=curve['ys']
                return ExportPayload(pd.DataFrame(data).to_csv(index=False),'text/csv; charset=utf-8',f'{job_id}_advanced.csv')
            from matplotlib.figure import Figure
            fig=Figure(figsize=(10,5),dpi=140);ax=fig.subplots()
            sticks = manifest['origin'].get('spectrum_style') == 'sticks'
            draw = lambda ys, label, color=None: ax.vlines(result['xs'], 0, ys, label=label, color=color) if sticks else ax.plot(result['xs'], ys, label=label, color=color)
            draw(result['ys'], 'Total', '#317aa3')
            for index, curve in enumerate(result['series']['elements']['interpolated']['curves']):
                draw(curve['ys'], curve['label'], f'C{(index+1)%10}')
            advanced_version=manifest['origin'].get('model_version')
            title=('NIST: fixed element view / shared relative photon scale' if str(advanced_version).startswith('nist-lines-')
                   else 'Paper Eq.7 / Stark per-line self-absorption: shared scale'
                   if advanced_version=='paper-eq7-stark-sa-1' else 'Saved advanced model: shared scale')
            ax.set(xlabel='Wavelength / nm',ylabel=manifest['origin'].get('intensity_units','Model photon intensity per nm; uncalibrated'),title=title);ax.legend();fig.tight_layout()
            stream=io.BytesIO();fig.savefig(stream,format='png');return ExportPayload(stream.getvalue(),'image/png',f'{job_id}_advanced.png')
        if kind in ('parameters','template'):
            key='actual_parameters' if kind=='parameters' else 'template_csv';path=manifest.get(key)
            if not path or manifest.get('partial'):raise ApiError(409,'此任务没有完整实际参数CSV','no_result')
            return ExportPayload(Path(path).read_bytes(),'text/csv; charset=utf-8',f'{job_id}_{key}.csv')
        if kind == 'training':
            package = manifest.get('training_package') or {}
            archive = Path(package.get('archive', ''))
            if manifest.get('partial') or not package.get('available') or not archive.is_file():
                raise ApiError(409, '此任务没有完整训练包；重新运行批量模拟后可下载', 'no_result')
            return ExportPayload(archive.read_bytes(), 'application/zip', f'{job_id}_training.zip')
        from simlibs_ui.operations import export_result
        export_dir = Path(result_path).parent / 'exports'
        export_dir.mkdir(parents=True, exist_ok=True)
        tmp = export_dir / f'{uuid.uuid4().hex[:8]}.out'
        try:
            if kind == 'csv':
                export_result(result_path, tmp, 'interpolated')
                return ExportPayload(tmp.read_bytes(), 'text/csv; charset=utf-8', f'{job_id}_interpolated.csv')
            if kind == 'json':
                export_result(result_path, tmp, 'json')
                return ExportPayload(tmp.read_bytes(), 'application/json; charset=utf-8', f'{job_id}_manifest.json')
            if kind == 'dataset':
                export_result(result_path, tmp, 'dataset')
                return ExportPayload(tmp.read_bytes(), 'text/csv; charset=utf-8', f'{job_id}_dataset.csv')
            if kind == 'png':
                target_manifest = result_path
                name = f'{job_id}_spectrum.png'
                if manifest.get('kind') == 'scan':
                    frames = manifest.get('frames') or []
                    if frame is None or not (0 <= frame < len(frames)):
                        raise ApiError(400, f'扫描导出 PNG 需要有效帧号（0–{len(frames) - 1}）', 'validation')
                    target_manifest = frames[frame]
                    name = f'{job_id}_frame_{frame:04d}.png'
                export_result(target_manifest, tmp, 'png', view='interpolated',
                              title=self._chart_title(manifest), color='#0891b2', normalize=False)
                return ExportPayload(tmp.read_bytes(), 'image/png', name)
            if kind == 'gif':
                if manifest.get('kind') != 'scan':
                    raise ApiError(400, 'GIF 只支持扫描任务', 'validation')
                export_result(result_path, tmp, 'gif', title=self._chart_title(manifest), color='#0891b2')
                return ExportPayload(tmp.read_bytes(), 'image/gif', f'{job_id}_scan.gif')
            raise ApiError(400, f'未知导出类型：{kind}', 'validation')
        finally:
            tmp.unlink(missing_ok=True)
            Path(str(tmp) + '.json').unlink(missing_ok=True)

    @staticmethod
    def _chart_title(manifest: Dict[str, Any]) -> str:
        p = manifest.get('parameters') or (manifest.get('origin') or {}).get('parameters') or {}
        elements = p.get('elements') or []
        return (f"{', '.join(elements)} · Te={p.get('Te', 0):g} eV · "
                f"Ne={p.get('Ne', 0):.3g} cm^-3 · simLIBS")
