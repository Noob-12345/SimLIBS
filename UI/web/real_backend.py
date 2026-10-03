"""simLIBS Web UI —— 真实后端（包装现有 simlibs_ui 包，不修改其任何文件）。

复用现有任务体系：
- simlibs_ui.jobs.JobController：专属 worker 子进程、Windows Job Object 所有权、
  go 启动门、cancel 协作取消 + 0.8s 宽限树清理、deadline 超时、events.jsonl；
- simlibs_ui.worker.execute：真实 adapter.simulate / operations.batch / operations.scan；
- simlibs_ui.storage.save_result：结果 manifest（含来源证据：源 SHA256、NIST URL、
  实际 Ne、驱动版本），与 Tk 桌面版完全同源（output/.jobs/<task-id>/）。

Web 层职责仅两件事：把 events.jsonl 映射为 Web JobEvent 流；把 manifest 转译为
前端结果契约（xs/ys/yi、扫描帧缓存、批量摘要）。预览端点返回 501——真实引擎
不提供合成谱，前端将以明确标注的本地示意图占位。
"""
from __future__ import annotations

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
        self._settings_path = Path(__file__).resolve().parent / '.web-settings.json'
        self._settings = self._load_settings()
        self._restore_session()
        # 预热：提前导入 adapter（pandas/selenium 等重依赖），
        # 避免首次打开页面时引擎状态接口阻塞数秒。
        threading.Thread(target=self._prewarm, daemon=True).start()

    def _prewarm(self) -> None:
        try:
            import simlibs_ui.adapter  # noqa: F401
        except Exception:
            pass

    def _restore_session(self):
        """安全重启后保留已终结任务；只读本项目原有产物，不恢复活动进程。"""
        try:records=json.loads((self._settings_path.parent/'.web-session.json').read_text(encoding='utf-8')).get('jobs',[])
        except (OSError,ValueError,AttributeError):return
        for record in reversed(records):
            jid=record.get('job_id','')
            if not re.fullmatch('[0-9a-f]{32}',jid) or record.get('status') not in TERMINAL_STATUSES:continue
            path=Path(self._settings.output)/'.jobs'/jid/'result'/'manifest.json'
            manifest=None
            if record['status']=='completed':
                try:manifest=json.loads(path.read_text(encoding='utf-8'))
                except (OSError,ValueError):continue
            self._jobs[jid]=dict(record,manifest=manifest,result_path=str(path) if manifest else None,
                                 events=[],subs=[],controller=None,t0=time.monotonic())

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
            return Settings(**data).validated()
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
        }

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        current = self._settings.to_dict()
        for key, value in (settings or {}).items():
            their = self._SET_MAP.get(key, key)
            if their in current:
                current[their] = value
        try:
            self._settings = Settings(**current).validated()
        except (ValueError, TypeError) as exc:
            raise ApiError(400, str(exc), 'validation')
        self._settings_path.write_text(
            json.dumps(self._settings.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
        return self.get_settings()

    # ------------------------------------------------------------------
    # 引擎状态 / 默认参数 / 预览
    # ------------------------------------------------------------------
    def api_version(self) -> str:
        return '1'

    def engine_status(self) -> Dict[str, Any]:
        with self._lock:
            running = sum(1 for j in self._jobs.values() if j['status'] in ('queued', 'running'))
        s = self._settings
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
        p = Parameters()   # H 窄波段（源 UI 已验证参数）
        return {
            'params': {
                'te': p.Te, 'ne': p.Ne, 'resolution': p.resolution,
                'low_w': p.low_w, 'up_w': p.upper_w, 'max_ion_charge': p.max_ion_charge,
                'mode': p.webscraping, 'headless': p.headless, 'resample': p.resample,
                'intensity_scale': p.intensity_scale,
                'broadening': p.broadening, 'broaden_convention': p.broaden_convention,
                'broaden_grid_step': p.broaden_grid_step,
                'broaden_center_decimals': p.broaden_center_decimals,
                'broaden_min_rel_int': p.broaden_min_rel_int,
            },
            'composition': [{'el': e, 'pct': pct} for e, pct in zip(p.elements, p.percentages)],
            'element_symbols': sorted(ELEMENTS),
            'title': 'H 100% · 已验证参数（真实引擎）',
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
        )

    def start_single(self, req: SingleRequest) -> str:
        p = self._to_parameters(req.params, req.composition)
        payload = {'parameters': p.to_dict()}
        summary = (f"{req.params.summary()} · "
                   + " / ".join(f"{it.el} {it.pct:g}%" for it in req.composition))
        return self._launch('单次模拟', 'single', payload, summary)

    def start_batch(self, req: BatchRequest) -> str:
        p = self._to_parameters(req.params, req.compositions[0].items)
        rows = []
        for comp in req.compositions:
            row = {'name': comp.name}
            for it in comp.items:
                row[it.el] = float(it.pct)
            rows.append(row)
        spec = {
            'size': req.n_samples, 'seed': req.seed,
            'Te_min': req.te_range[0], 'Te_max': req.te_range[1],
            'Ne_min': 10 ** req.ne_range[0], 'Ne_max': 10 ** req.ne_range[1],
        }
        payload = {'parameters': p.to_dict(), 'spec': spec, 'compositions': rows}
        summary = f'{req.n_samples} 样本 · seed={req.seed} · {req.params.summary()}'
        return self._launch('批量 dataset', 'batch', payload, summary)

    def start_scan(self, req: ScanRequest) -> str:
        p = self._to_parameters(req.params, req.composition)
        axis = AXIS_MAP[req.axis]
        # Web 契约的 Ne 轴以 10^ 指数表达；真实扫描使用绝对 Ne。
        start = 10 ** req.start if req.axis == 'ne' else req.start
        stop = 10 ** req.end if req.axis == 'ne' else req.end
        spec = {'axis': axis, 'start': start, 'stop': stop, 'count': req.frames, 'step': None}
        comp_txt = " / ".join(f"{it.el} {it.pct:g}%" for it in req.composition)
        payload = {'parameters': p.to_dict(), 'spec': spec}
        summary = f'{axis} {req.start:g}→{req.end:g} · {req.frames} 帧 · {req.params.summary()} · {comp_txt}'
        return self._launch('扫描动画', 'scan', payload, summary)

    def _launch(self, kind_label: str, worker_kind: str, payload: Dict[str, Any], summary: str) -> str:
        from simlibs_ui.jobs import JobController
        controller = JobController(self._settings)
        try:
            job_id = controller.start(worker_kind, **payload)
        except ValueError as exc:
            raise ApiError(400, str(exc), 'validation')
        except Exception as exc:
            raise ApiError(500, f'任务启动失败：{exc}')
        job = {
            'job_id': job_id, 'kind': kind_label, 'status': 'queued', 'summary': summary,
            'progress': 0.0, 'duration': '-', 'error': None,
            'created': datetime.now().strftime('%m-%d %H:%M'),
            'events': [], 'subs': [], 'controller': controller,
            't0': time.monotonic(), 'result_path': None, 'manifest': None,
        }
        with self._lock:
            self._jobs[job_id] = job
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
                   message=f'[done] manifest 就绪 · {job["result_path"]}（来源证据与 Tk 桌面版同源）',
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
        return {k: job.get(k) for k in
                ('job_id', 'kind', 'status', 'summary', 'progress', 'duration', 'error', 'created')}

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
    def get_result(self, job_id: str) -> Dict[str, Any]:
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
            return self._scan_result(job, manifest)
        if kind == 'batch':
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
            'points': f'{main["label"]}：{len(xs):,}/{main["total_points"]:,} CSV点（保峰预算 {SINGLE_POINTS}）',
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
            'resolution_warning': origin.get('resolution_warning'),
            'line_table_rows': origin.get('line_table_rows'),
        }
        return {'kind': 'single', 'xs': xs, 'ys': ys, 'yi': [], 'series': series, 'meta': meta}

    def _scan_result(self, job: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
        axis = str(manifest.get('axis', 'Te')).lower()
        values = manifest.get('completed_values') or []
        frames_out = []
        paths = manifest.get('frames') or []
        if len(values) != len(paths):
            raise ApiError(500, '扫描帧与参数数量不一致')
        for value, frame_path in zip(values, paths):
            fm = json.loads(Path(frame_path).read_text(encoding='utf-8'))
            series = file_series(fm, FRAME_PREVIEW_POINTS)
            main = series.get('interpolated') or series['raw']
            # Web 契约：Ne 轴以 10^ 指数表达
            display = math.log10(float(value)) if axis == 'ne' else float(value)
            frames_out.append({
                'value': display, 'xs': main['xs'], 'ys': main['ys'], 'yi': [], 'series': series,
                'intensity_scale':intensity_scale_from_origin(fm.get('origin')),
            })
        p = manifest.get('parameters') or {}
        params_summary = (f"Te={p.get('Te', 0):g} eV · Ne={p.get('Ne', 0):.3g} · "
                          f"R{p.get('resolution', 0)} · {p.get('low_w', 0):g}–{p.get('upper_w', 0):g} nm")
        return {'kind': 'scan', 'axis': axis, 'unit': {'te': ' eV', 'ne': '×10^x cm⁻³', 'r': ''}[axis],
                'frames': frames_out, 'params_summary': params_summary,
                'intensity_scale':frames_out[0]['intensity_scale'] if frames_out else 'unknown','intensity_units':'a.u. (relative flux)'}

    def _batch_result(self, job: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
        import pandas as pd
        samples = []
        for row in (manifest.get('preview') or [])[:12]:
            elements = [k for k in row if k not in ('name', 'Te[eV]', 'Ne[cm^-3]')]
            samples.append({
                'name': str(row.get('name', '')),
                'te': round(float(row.get('Te[eV]', 0)), 3),
                'ne': float(row.get('Ne[cm^-3]', 0)),
                'composition': [{'el': e, 'pct': float(row[e])} for e in elements],
            })
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
            'samples': samples, 'wide': wide,
        }

    # ------------------------------------------------------------------
    # 导出（复用 simlibs_ui.operations.export_result：全量数据 / 真实 PNG/GIF）
    # ------------------------------------------------------------------
    def export(self, job_id: str, kind: str, frame: Optional[int] = None) -> ExportPayload:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise ApiError(404, f'任务不存在：{job_id}', 'not_found')
        if job['status'] != 'completed' or not job.get('result_path'):
            raise ApiError(409, '只有成功完成的任务才能导出', 'no_result')
        manifest, result_path = job['manifest'], job['result_path']
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
