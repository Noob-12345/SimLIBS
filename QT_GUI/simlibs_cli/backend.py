"""simLIBS Studio CLI —— 后端接入层。

进程内直接复用 UI/web/real_backend.py 的 RealBackend（协议见 backend_api.SimlibsBackend）：
- 任务跑在 simlibs_ui.jobs.JobController 的专属 worker 子进程中（Windows Job Object、
  go 启动门、协作取消、deadline 超时），与 Tk 桌面版 / Web 版完全同源；
- CLI 不启动 HTTP 服务，subscribe()/EventQueue 由 TUI 线程直接消费；
- 设置持久化到 CLI/.cli-settings.json（与 Web 的 .web-settings.json 互不影响）；
- 不改动 UI 目录任何现有程序文件；SIMLIBS_WEB_BACKEND=mock 时切换 MOCK 演示引擎。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = CLI_ROOT.parent / 'UI'
WEB_DIR = UI_ROOT / 'web'
for _p in (str(UI_ROOT), str(WEB_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CANDIDATE_PYTHONS = (
    r'E:\Anaconda\envs\simLIBS\python.exe',
    r'D:\Anaconda3\envs\simLIBS\python.exe',
)


def discover_python() -> str:
    """设置里默认解释器失效时（如盘符迁移）回退到可用解释器/当前解释器。"""
    for path in CANDIDATE_PYTHONS:
        if Path(path).is_file():
            return path
    return sys.executable


def create_backend():
    """按环境变量 / --mock 选择后端；默认真实引擎。"""
    argv = sys.argv[1:] if sys.argv else []
    import os
    if '--mock' in argv or os.environ.get('SIMLIBS_WEB_BACKEND', '').lower() == 'mock':
        from mock_backend import MockBackend  # noqa: F401  (协议一致，直接可用)
        return MockBackend()
    return CliBackend()


class CliBackend:
    """RealBackend 的 CLI 包装：独立设置文件 + 解释器回退（组合而非继承，
    避免 UI/web 目录内部导入顺序与本包 sys.path 注入互相纠缠）。"""

    def __init__(self) -> None:
        import threading
        from real_backend import RealBackend
        self.mock = False
        self._path = CLI_ROOT / '.cli-settings.json'
        inst = RealBackend.__new__(RealBackend)   # 仅跳过 __init__，其余步骤照抄
        inst._lock = threading.Lock()
        inst._jobs = {}
        inst._settings_path = self._path
        inst._settings = self._load_settings(inst, fallback=True)
        inst._restore_session()
        inst._prewarm()
        self._inst = inst
        self.apply_proxy_env()   # 启动即应用已保存的代理，worker 子进程继承

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
        # 默认解释器失效（盘符迁移等）→ 回退可用解释器，其余设置原样保留
        try:
            rest = {k: v for k, v in data.items() if k != 'python'}
            return Settings(python=discover_python(), **rest).validated()
        except Exception:
            return Settings(python=discover_python()).validated()

    def settings_path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # 网络代理（针对 NIST 间歇性 TLS 干扰的可选缓解；存 CLI/.cli-proxy.json，
    # 通过环境变量传递给 worker 子进程，requests 自动生效，不改动 UI 目录）
    # ------------------------------------------------------------------
    _PROXY_FILE = CLI_ROOT / '.cli-proxy.json'

    def get_proxy(self) -> str:
        try:
            return json.loads(self._PROXY_FILE.read_text(encoding='utf-8')).get('https', '')
        except Exception:
            return ''

    def set_proxy(self, value: str) -> None:
        value = (value or '').strip()
        if value:
            self._PROXY_FILE.write_text(
                json.dumps({'https': value}, ensure_ascii=False), encoding='utf-8')
        else:
            self._PROXY_FILE.unlink(missing_ok=True)
        self.apply_proxy_env()

    @staticmethod
    def apply_proxy_env() -> None:
        import os
        for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            os.environ.pop(k, None)
        try:
            proxy = json.loads((CLI_ROOT / '.cli-proxy.json').read_text(encoding='utf-8')).get('https', '')
        except Exception:
            proxy = ''
        if proxy:
            os.environ['HTTP_PROXY'] = proxy
            os.environ['HTTPS_PROXY'] = proxy

    # ------------------------------------------------------------------
    # 显示降级：峰谷点数超过预览预算时（如 Fe 200–700nm 有 8555 个峰谷 > 6000），
    # 保峰抽样按设计直接报错。模拟本身成功、完整 CSV 都在，CLI 端回退为均匀抽样
    # 显示并在 meta 明确标注"显示抽样已降级"，弱峰可能未在预览中显示。
    # ------------------------------------------------------------------
    def get_result(self, job_id: str, frame: int | None = None) -> dict:
        if frame is not None:
            return self._inst.get_result(job_id, frame)   # 扫描懒帧：按帧取全量
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

    # 协议转发 -----------------------------------------------------------
    def __getattr__(self, name):
        return getattr(self._inst, name)

    def save_settings(self, settings: dict) -> dict:
        merged = self._inst.get_settings()
        s = self._inst._SET_MAP
        for key, value in (settings or {}).items():
            their = s.get(key, key)
            if their in merged and value is not None:
                merged[their] = value
        if not Path(merged.get('python', '')).is_file():
            merged['python'] = discover_python()
        return self._inst.save_settings(merged)
