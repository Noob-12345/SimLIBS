"""simLIBS Studio WPF —— Python 桥接进程（JSON-lines over stdio）。

由 C# 宿主（SimlibsStudio.exe）以子进程启动，stdin/stdout 按 UTF-8 JSON 行通信：

- 请求（C# → 桥）  ：{"id": 1, "cmd": "get_settings", ...}
- 响应（桥 → C#）  ：{"id": 1, "ok": true, "data": ...}
                     {"id": 1, "ok": false, "error": {"code": "...", "message": "..."}}
- 事件（桥 → C#）  ：{"event": "ready", "data": {...}}                      启动握手
                     {"event": "job_event", "job_id": "...", "data": {...}}  任务事件流
                     {"event": "bridge_log", "level": "...", "message": "..."} 桥内诊断

进程内直接复用 UI/web/real_backend.py 的 RealBackend（与 Web / Tk / Qt 版完全同源），
任务跑在 simlibs_ui.jobs.JobController 的 worker 子进程中。不改动 UI / CLI 目录任何文件。
设置持久化到 WPF/.wpf-settings.json（与 Qt 版 .cli-settings.json 互不影响），
代理保存到 WPF/.wpf-proxy.json（经环境变量传给 worker 子进程）。
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

WPF_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WPF_ROOT.parent
UI_ROOT = REPO_ROOT / 'UI'
WEB_DIR = UI_ROOT / 'web'
CLI_ROOT = REPO_ROOT / 'CLI'

for _p in (str(UI_ROOT), str(WEB_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend_api import ApiError  # noqa: E402  （主循环与命令层共用）

CANDIDATE_PYTHONS = (
    r'E:\Anaconda\envs\simLIBS\python.exe',
    r'D:\Anaconda3\envs\simLIBS\python.exe',
)


def discover_python() -> str:
    """默认解释器失效时（盘符迁移等）回退到可用解释器 / 当前解释器。"""
    for path in CANDIDATE_PYTHONS:
        if Path(path).is_file():
            return path
    return sys.executable


def _load_history_module():
    path = CLI_ROOT / 'simlibs_cli' / 'history.py'
    spec = importlib.util.spec_from_file_location('simlibs_history', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Bridge:
    """RealBackend / MockBackend 的 JSON-lines 封装。"""

    def __init__(self, log) -> None:
        self._log = log
        self.mock = ('--mock' in sys.argv[1:]
                     or os.environ.get('SIMLIBS_WEB_BACKEND', '').lower() == 'mock')
        self._emit = None            # 稍后注入
        self._sub_lock = threading.Lock()
        self._subs: dict[str, threading.Thread] = {}
        self._path = WPF_ROOT / '.wpf-settings.json'
        self._proxy_file = WPF_ROOT / '.wpf-proxy.json'
        self._inst = self._make_backend()
        self.apply_proxy_env()

    # ------------------------------------------------------------------
    # 后端构造（照抄 simlibs_cli/backend.py 的组合方式）
    # ------------------------------------------------------------------
    def _make_backend(self):
        if self.mock:
            from mock_backend import MockBackend
            return MockBackend()
        import threading
        from real_backend import RealBackend
        inst = RealBackend.__new__(RealBackend)   # 跳过 __init__，其余步骤照抄
        inst._lock = threading.Lock()
        inst._jobs = {}
        inst._settings_path = self._path
        inst._settings = self._load_settings(inst, fallback=True)
        inst._restore_session()
        inst._prewarm()
        return inst

    @staticmethod
    def _load_settings(inst, fallback: bool = False):
        from simlibs_ui.settings import Settings
        data: dict = {}
        try:
            data = json.loads(inst._settings_path.read_text(encoding='utf-8'))
        except Exception:
            pass
        try:
            return Settings(**data).validated()
        except Exception:
            pass
        if not fallback:
            return Settings().validated()
        try:
            rest = {k: v for k, v in data.items() if k != 'python'}
            return Settings(python=discover_python(), **rest).validated()
        except Exception:
            return Settings(python=discover_python()).validated()

    # ------------------------------------------------------------------
    # 代理（针对 NIST 间歇性 TLS 干扰的可选缓解）
    # ------------------------------------------------------------------
    def get_proxy(self) -> str:
        try:
            return json.loads(self._proxy_file.read_text(encoding='utf-8')).get('https', '')
        except Exception:
            return ''

    def set_proxy(self, value: str) -> None:
        value = (value or '').strip()
        if value:
            self._proxy_file.write_text(
                json.dumps({'https': value}, ensure_ascii=False), encoding='utf-8')
        else:
            self._proxy_file.unlink(missing_ok=True)
        self.apply_proxy_env()

    @staticmethod
    def apply_proxy_env() -> None:
        for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            os.environ.pop(k, None)
        try:
            proxy = json.loads((WPF_ROOT / '.wpf-proxy.json').read_text(encoding='utf-8')).get('https', '')
        except Exception:
            proxy = ''
        if proxy:
            os.environ['HTTP_PROXY'] = proxy
            os.environ['HTTPS_PROXY'] = proxy

    # ------------------------------------------------------------------
    # 显示降级：保峰抽样超预算时（如 Fe 200–700nm 8555 峰谷 > 6000），
    # 回退均匀抽样显示，meta 明确标注（完整 CSV 不受影响）。
    # ------------------------------------------------------------------
    def get_result(self, job_id: str, frame=None) -> dict:
        if frame is not None:
            try:
                return self._inst.get_result(job_id, frame)   # 扫描懒帧：按帧取全量
            except TypeError:
                return self._inst.get_result(job_id)          # Mock 后端无懒帧，整包返回
        try:
            return self._inst.get_result(job_id)
        except ValueError as exc:
            if '显示预算' not in str(exc) and '峰谷' not in str(exc):
                raise
            return self._get_result_degraded(job_id, str(exc))

    def _get_result_degraded(self, job_id: str, reason: str) -> dict:
        import real_backend
        import sampling
        import numpy as np

        original_indices = sampling.sample_indices
        original_single = real_backend.SINGLE_POINTS

        def uniform_indices(xs, ys, budget):
            n = len(xs)
            if n <= budget:
                return np.arange(n)
            step = max(1, n // budget)
            idx = np.arange(0, n, step)
            if idx[-1] != n - 1:
                idx = np.append(idx, n - 1)
            return idx

        sampling.sample_indices = uniform_indices
        real_backend.SINGLE_POINTS = 4000
        try:
            result = self._inst.get_result(job_id)
        finally:
            sampling.sample_indices = original_indices
            real_backend.SINGLE_POINTS = original_single
        meta = result.get('meta') or {}
        meta['points'] = (str(meta.get('points') or '') + ' · [显示抽样已降级：' + reason + '，弱峰可能未显示]')
        meta['preview_degraded'] = reason
        result['meta'] = meta
        return result

    def interpreter_label(self) -> str:
        try:
            return self._inst._settings.python
        except Exception:
            return discover_python()


# ======================================================================
# 命令实现（data 已解包；返回值放入响应 data）
# ======================================================================

def make_handlers(bridge: Bridge):
    inst = bridge._inst
    from backend_api import ApiError, SingleRequest, BatchRequest, ScanRequest, CommonParams

    def hello(data):
        try:
            engine = inst.engine_status()
        except Exception as exc:
            engine = {'engine_label': f'状态未知（{exc}）'}
        return {'mock': bridge.mock, 'pid': os.getpid(), 'protocol': 1,
                'python': sys.executable, 'interpreter': bridge.interpreter_label(),
                'engine': engine}

    def default_params(data):
        result = inst.default_params()
        if 'element_symbols' not in result:      # MockBackend 不带元素表，统一补齐
            from simlibs_ui.models import ELEMENTS
            result['element_symbols'] = sorted(ELEMENTS)
        return result

    def engine_status(data):
        try:
            return inst.engine_status((data or {}).get('mode') or 'local')
        except TypeError:
            return inst.engine_status()

    def get_settings(data):
        out = dict(inst.get_settings())
        out['proxy'] = bridge.get_proxy()
        return out

    def save_settings(data):
        proxy = (data or {}).pop('proxy', None)
        result = inst.save_settings(data or {})
        if proxy is not None:
            bridge.set_proxy(str(proxy))
            result = dict(inst.get_settings())
        result['proxy'] = bridge.get_proxy()
        return result

    def start_single(data):
        return {'job_id': inst.start_single(SingleRequest.from_api(data))}

    def start_batch(data):
        return {'job_id': inst.start_batch(BatchRequest.from_api(data))}

    def start_scan(data):
        return {'job_id': inst.start_scan(ScanRequest.from_api(data))}

    def cancel(data):
        return {'cancelled': bool(inst.cancel(data['job_id']))}

    def list_jobs(data):
        return {'jobs': inst.list_jobs()}

    def get_job(data):
        return inst.get_job(data['job_id'])

    def get_result(data):
        frame = data.get('frame')
        return bridge.get_result(data['job_id'], int(frame) if frame is not None else None)

    def subscribe(data):
        job_id = data['job_id']
        with bridge._sub_lock:
            if job_id in bridge._subs:
                return {'subscribed': True, 'already': True}
        queue = inst.subscribe(job_id)

        def pump():
            while True:
                kind, event = queue.get(timeout=0.25)
                if kind == 'close':
                    break
                if kind == 'event':
                    bridge._emit({'event': 'job_event', 'job_id': job_id,
                                  'data': event.to_dict()})

        thread = threading.Thread(target=pump, name=f'sub-{job_id[:8]}', daemon=True)
        with bridge._sub_lock:
            bridge._subs[job_id] = thread
        thread.start()
        return {'subscribed': True}

    def export(data):
        payload = inst.export(data['job_id'], data['kind'],
                              int(data['frame']) if data.get('frame') is not None else None)
        if isinstance(payload.payload, bytes):
            body = {'b64': base64.b64encode(payload.payload).decode('ascii'), 'text': None}
        else:
            body = {'b64': None, 'text': str(payload.payload)}
        body['media_type'] = payload.media_type
        body['filename'] = payload.filename
        return body

    def open_history(data):
        module = _load_history_module()
        return module.load_history(data['path'], int(data.get('budget', 6000)))

    return {
        'hello': hello, 'default_params': default_params, 'engine_status': engine_status,
        'get_settings': get_settings, 'save_settings': save_settings,
        'start_single': start_single, 'start_batch': start_batch, 'start_scan': start_scan,
        'cancel': cancel, 'list_jobs': list_jobs, 'get_job': get_job,
        'get_result': get_result, 'subscribe': subscribe, 'export': export,
        'open_history': open_history,
    }


# ======================================================================
# 主循环
# ======================================================================

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    out_lock = threading.Lock()

    def emit(obj) -> None:
        try:
            line = json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:
            line = json.dumps({'event': 'bridge_log', 'level': 'error',
                               'message': '序列化失败：' + repr(obj)[:200]})
        with out_lock:
            sys.stdout.write(line + '\n')
            sys.stdout.flush()

    def log(level: str, message: str) -> None:
        emit({'event': 'bridge_log', 'level': level, 'message': message})

    t0 = time.monotonic()
    try:
        bridge = Bridge(log)
    except Exception as exc:
        log('error', '后端初始化失败：' + repr(exc))
        traceback.print_exc()
        return 1
    bridge._emit = emit          # 事件泵线程由此向 C# 宿主推送
    handlers = make_handlers(bridge)
    log('info', f"桥接就绪 · mock={bridge.mock} · 初始化 {time.monotonic() - t0:.1f}s")
    emit({'event': 'ready', 'data': {
        'mock': bridge.mock, 'pid': os.getpid(), 'protocol': 1,
        'interpreter': bridge.interpreter_label()}})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except ValueError as exc:
            log('error', f'请求解析失败：{exc}')
            continue
        rid, cmd, data = request.get('id'), request.get('cmd', ''), request.get('data') or {}
        started = time.monotonic()
        try:
            handler = handlers.get(cmd)
            if handler is None:
                raise ApiError(400, f'未知命令：{cmd}', 'unknown_cmd')
            result = handler(data)
            if cmd not in ('subscribe',):
                log('debug', f'{cmd} ok · {time.monotonic() - started:.2f}s')
            emit({'id': rid, 'ok': True, 'data': result})
        except ApiError as exc:
            emit({'id': rid, 'ok': False,
                  'error': {'code': exc.code, 'message': exc.message}})
        except Exception as exc:
            log('error', f'{cmd} 失败：{exc!r}')
            traceback.print_exc()
            emit({'id': rid, 'ok': False,
                  'error': {'code': 'error', 'message': f'{type(exc).__name__}: {exc}'}})
    return 0


if __name__ == '__main__':
    sys.exit(main())
