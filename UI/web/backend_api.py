"""simLIBS Web UI —— 前端 ↔ 后端 接口契约。

本文件只定义接口与数据契约（校验规则沿用同级 UI README 的约定），零第三方依赖。
真实程序接入时：实现 `SimlibsBackend` 协议（包装现有 simlibs_ui 包，只调用不修改），
然后在 server.py 的 create_backend() 中替换一行即可，前端与路由零改动。

需要 Python 3.8+（建议使用现有 D:\\Anaconda3\\envs\\simLIBS\\python.exe 3.10）。
"""
from __future__ import annotations

import math
import queue
from pathlib import Path
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple
_ui_root=str(Path(__file__).resolve().parents[1])
if _ui_root not in sys.path:sys.path.insert(0,_ui_root)
from simlibs_ui.models import ELEMENTS

API_VERSION = "1"

# ---- 契约常量（与 UI README 一致）----
SUM_TOL = 1e-6              # 配比总和 100% 的绝对浮点容差
MAX_SINGLE_POINTS = 200_000     # 单谱点数上限
MAX_PREVIEW_POINTS = MAX_SINGLE_POINTS  # all actual nodes; generation ceiling, no display budget
MAX_SCAN_FRAMES = 200           # 扫描帧数上限
MAX_BATCH_SAMPLES = 5_000       # 批量样本数上限
MAX_BATCH_CELLS = 5_000_000     # 批量光谱单元上限
DEFAULT_RESAMPLE_STEP = 0.005   # static 默认网格 [nm]

TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class ApiError(Exception):
    """业务错误；status 用于 HTTP 状态码。"""

    def __init__(self, status: int, message: str, code: str = "error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code

    def to_dict(self) -> Dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


# ======================================================================
# 校验工具
# ======================================================================

def _finite(value: Any, name: str) -> float:
    # 不把 NaN/无穷/空串“悄悄”转换；与源 UI 的契约一致
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, f"{name} 必须是数字", "validation")
    try:v = float(value)
    except OverflowError:raise ApiError(400,f'{name} 超出有限数值范围','validation') from None
    if not math.isfinite(v):
        raise ApiError(400, f"{name} 必须是有限数值", "validation")
    return v


def _positive(value: Any, name: str) -> float:
    v = _finite(value, name)
    if v <= 0:
        raise ApiError(400, f"{name} 必须大于 0", "validation")
    return v


def _int(value: Any, name: str, minimum: Optional[int] = None) -> int:
    if isinstance(value, bool):
        raise ApiError(400, f"{name} 必须是整数", "validation")
    f = _finite(value, name)
    if f != int(f):
        raise ApiError(400, f"{name} 必须是整数", "validation")
    iv = int(f)
    if minimum is not None and iv < minimum:
        raise ApiError(400, f"{name} 不能小于 {minimum}", "validation")
    return iv


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError(400, f"{name} 必须是布尔值", "validation")
    return value


def _require_dict(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiError(400, f"{name} 必须是对象", "validation")
    return value


# ======================================================================
# 请求模型
# ======================================================================

@dataclass
class CompositionItem:
    el: str
    pct: float

    @staticmethod
    def from_api(raw: Any, where: str = "composition") -> "CompositionItem":
        d = _require_dict(raw, where)
        el = d.get("el")
        if not isinstance(el, str) or not el.strip():
            raise ApiError(400, f"{where}.el 不能为空（元素符号区分大小写）", "validation")
        pct = _finite(d.get("pct"), f"{where}.pct")
        if pct < 0:
            raise ApiError(400, f"{where}.pct 不能为负（不自动归零）", "validation")
        return CompositionItem(el.strip(), pct)


@dataclass
class CommonParams:
    """共同模拟参数（适用于单次/批量/扫描）。"""
    te: float
    ne: float
    resolution: int
    low_w: float
    up_w: float
    max_ion_charge: int
    mode: str                      # static | dynamic
    mode_version: int = 1
    headless: bool = True
    resample: bool = False         # 是否本地插值（重采样）
    resample_step: float = DEFAULT_RESAMPLE_STEP
    intensity_scale: str = 'photon'
    broadening: str = 'nist'       # nist=服务端/页面展宽；local=本地线表展宽
    broaden_convention: str = 'nist'   # nist: w=λ/R；physics: FWHM=λ/R
    broaden_grid_step: float = DEFAULT_RESAMPLE_STEP
    broaden_center_decimals: Optional[int] = None
    broaden_min_rel_int: float = 0.0
    local_gaussian_nm: float = 0.0
    local_lorentz_nm: float = 0.0
    local_temperature_K: float = 0.0
    local_temperature_mode: str = 'manual'

    @staticmethod
    def from_api(raw: Any) -> "CommonParams":
        d = _require_dict(raw, "params")
        mode = d.get("mode", "dynamic")
        if mode not in ('static','dynamic','server','client','local'):
            raise ApiError(400, '无效计算模式', 'validation')
        version = _int(d.get('mode_version',1),'mode_version',1)
        if version != (2 if mode in ('server','client','local') else 1):
            raise ApiError(400,'server/client 需要 mode_version=2；旧模式使用版本1','validation')
        scale=d.get('intensity_scale','photon')
        if scale not in ('photon','energy'):raise ApiError(400,'强度尺度须为photon/energy','validation')
        if mode=='local' and scale!='photon':raise ApiError(400,'本地模式仅支持相对photon强度','validation')
        p = CommonParams(
            te=_positive(d.get("te"), "params.te"),
            ne=_positive(d.get("ne"), "params.ne"),
            resolution=_int(d.get("resolution"), "params.resolution", minimum=1),
            low_w=_positive(d.get("low_w"), "params.low_w"),
            up_w=_positive(d.get("up_w"), "params.up_w"),
            max_ion_charge=_int(d.get("max_ion_charge"), "params.max_ion_charge", minimum=0),
            mode=mode,
            mode_version=version,
            headless=_bool(d.get("headless", True), "params.headless"),
            resample=_bool(d.get("resample", False), "params.resample"),
            resample_step=DEFAULT_RESAMPLE_STEP,
            intensity_scale=scale,
        )
        if p.resample:
            p.resample_step = _positive(d.get("resample_step", DEFAULT_RESAMPLE_STEP), "params.resample_step")
        if not (0 < p.low_w < p.up_w):
            raise ApiError(400, "波长范围需满足 0 < 下界 < 上界", "validation")
        if p.max_ion_charge>2:raise ApiError(400,'最大离子电荷须为0–2','validation')
        expected = 'local' if mode in ('client','local') else 'nist'
        p.broadening = d.get('broadening', expected)
        if version==2 and p.broadening!=expected:
            raise ApiError(400,'v2 计算模式固定展宽路径，不能独立组合','validation')
        if mode=='server' and p.resolution<100:
            raise ApiError(400,'官方 JS 重算要求 R>=100','validation')
        if p.broadening not in ("nist", "local"):
            raise ApiError(400, "params.broadening 只能是 'nist' 或 'local'", "validation")
        p.broaden_convention = d.get("broaden_convention", "physics" if mode=='local' else "nist")
        if p.broaden_convention not in ("nist", "physics"):
            raise ApiError(400, "params.broaden_convention 只能是 'nist' 或 'physics'", "validation")
        if mode=='local' and p.broaden_convention!='physics':raise ApiError(400,'离线本地使用FWHM=lambda/R物理约定','validation')
        p.broaden_grid_step = _positive(d.get('broaden_grid_step',.01 if mode in ('client','local') else DEFAULT_RESAMPLE_STEP),'params.broaden_grid_step')
        center = d.get("broaden_center_decimals")
        if center is not None:
            p.broaden_center_decimals = _int(center, "params.broaden_center_decimals", 0)
        p.broaden_min_rel_int = _finite(d.get("broaden_min_rel_int", 0.0), "params.broaden_min_rel_int")
        if p.broaden_min_rel_int < 0:
            raise ApiError(400, "params.broaden_min_rel_int 不能为负", "validation")
        for key in ('local_gaussian_nm','local_lorentz_nm','local_temperature_K'):
            value=_finite(d.get(key,0),key)
            if value<0:raise ApiError(400,f'{key}不能为负','validation')
            setattr(p,key,value)
        p.local_temperature_mode=d.get('local_temperature_mode','manual')
        if p.local_temperature_mode not in ('linked','manual'):raise ApiError(400,'温度模式须为linked/manual','validation')
        if mode=='local' and p.local_temperature_mode=='linked':_positive(p.te*(1.602176634e-19/1.380649e-23),'有效重粒子温度K')
        if mode=='server' and (p.broaden_convention!='nist' or p.broaden_center_decimals is not None):
            raise ApiError(400,'服务器 v2 使用官方 JS 约定，不能指定 Python 展宽参数','validation')
        return p

    def grid_step(self) -> float:
        """实际谱线网格步长。本地展宽=合成/插值网格中更密者；其余：主动重采样用输入步长；
        static 默认 0.005；dynamic 保留 NIST 网格（近似估计）。"""
        if self.broadening == 'local':
            step = self.broaden_grid_step
            if self.resample:
                step = min(step, self.resample_step)
            return step
        if self.resample:
            return self.resample_step
        return 0.005 if self.mode == "static" else 0.01

    def points_estimate(self) -> int:
        ratio=(self.up_w-self.low_w)/self.grid_step()
        if not math.isfinite(ratio):raise ApiError(400,'网格点数超出有限范围','validation')
        return int(ratio)+1

    def check_points(self) -> None:
        n = self.points_estimate()
        if n > MAX_SINGLE_POINTS:
            raise ApiError(
                400,
                f"预计谱线点数 {n:,} 超过单谱上限 {MAX_SINGLE_POINTS:,}（可缩小波长范围或加大步长）",
                "validation",
            )

    def summary(self) -> str:
        return (f"Te={self.te:g} · Ne={self.ne:.3g} · R{self.resolution} · "
                f"{self.low_w:g}–{self.up_w:g}nm · {self.mode} · {self.intensity_scale} flux (a.u.)")


def validate_composition(items: List[CompositionItem], where: str = "composition") -> None:
    if not items:
        raise ApiError(400, f"{where} 至少需要一个元素", "validation")
    if len(items) > 32:
        raise ApiError(400, f"{where} 元素数量过多（≤32）", "validation")
    seen = set()
    for it in items:
        if it.el not in ELEMENTS:raise ApiError(400,f'无效元素符号：{it.el}（使用Fe等规范大小写）','validation')
        if it.el in seen:
            raise ApiError(400, f"{where} 元素重复：{it.el}", "validation")
        seen.add(it.el)
    total = sum(it.pct for it in items)
    if abs(total - 100.0) > SUM_TOL:
        raise ApiError(400, f"{where} 总和必须为 100%（当前 {total:.6g}%）", "validation")


@dataclass
class SingleRequest:
    params: CommonParams
    composition: List[CompositionItem]
    title: str = ""

    @staticmethod
    def from_api(raw: Any) -> "SingleRequest":
        d = _require_dict(raw, "body")
        comp = [CompositionItem.from_api(x) for x in d.get("composition", [])]
        validate_composition(comp)
        params = CommonParams.from_api(d.get("params"))
        params.check_points()
        title = d.get("title", "")
        if not isinstance(title, str):
            raise ApiError(400, "title 必须是字符串", "validation")
        return SingleRequest(params=params, composition=comp, title=title.strip())


@dataclass
class BatchSample:
    name: str
    items: List[CompositionItem]


@dataclass
class BatchRequest:
    params: CommonParams
    n_samples: int
    seed: int
    te_range: Tuple[float, float]
    ne_range: Tuple[float, float]      # 以 10^ 指数表示
    compositions: List[BatchSample]    # 候选组成池（至少 1 个，每行总和须 100%）
    batch_size: int = 32
    template_plan: Optional[Dict[str, Any]] = None

    @staticmethod
    def from_api(raw: Any) -> "BatchRequest":
        d = _require_dict(raw, "body")
        params = CommonParams.from_api(d.get("params"))
        template_plan=None
        if d.get('template_csv') is not None:
            from simlibs_ui.batch_template import parse_template
            from simlibs_ui.models import Parameters
            base=Parameters(Te=params.te,Ne=params.ne,resolution=params.resolution,low_w=params.low_w,upper_w=params.up_w,
                 max_ion_charge=params.max_ion_charge,webscraping=params.mode,mode_version=params.mode_version,
                 headless=params.headless,resample=params.resample,step=params.resample_step,intensity_scale=params.intensity_scale,
                 broadening=params.broadening,broaden_convention=params.broaden_convention,broaden_grid_step=params.broaden_grid_step,
                 broaden_center_decimals=params.broaden_center_decimals,broaden_min_rel_int=params.broaden_min_rel_int,
                 local_gaussian_nm=params.local_gaussian_nm,local_lorentz_nm=params.local_lorentz_nm,local_temperature_K=params.local_temperature_K,local_temperature_mode=params.local_temperature_mode)
            try:template_plan=parse_template(d['template_csv'],base,d.get('repeats',1),d.get('name_column','name'))
            except ValueError as error:raise ApiError(400,str(error),'validation') from error
            if d.get('n_samples',template_plan['sample_count'])!=template_plan['sample_count']:raise ApiError(400,'模板样本数须与行数×重复一致','validation')
            d=dict(d,n_samples=template_plan['sample_count'],compositions=[{'name':entry['name'],'items':[{'el':el,'pct':pct} for el,pct in zip(entry['parameters']['elements'],entry['parameters']['percentages'])]} for entry in template_plan['entries']],
                   te_range=d.get('te_range',[params.te,params.te]),ne_range=d.get('ne_range',[math.log10(params.ne)]*2))
        n = _int(d.get("n_samples"), "n_samples", minimum=1)
        if n > MAX_BATCH_SAMPLES:
            raise ApiError(400, f"n_samples 超过批量上限 {MAX_BATCH_SAMPLES}", "validation")
        batch_size = _int(d.get('batch_size', 32), 'batch_size', minimum=1)
        if batch_size > MAX_BATCH_SAMPLES:
            raise ApiError(400, 'batch_size 须 <= 5000', 'validation')
        seed = _int(d.get("seed", 0), "seed", minimum=0)

        def _range(key: str) -> Tuple[float, float]:
            r = d.get(key)
            if not isinstance(r, (list, tuple)) or len(r) != 2:
                raise ApiError(400, f"{key} 必须是 [min, max]", "validation")
            a, b = _finite(r[0], f"{key}[0]"), _finite(r[1], f"{key}[1]")
            if a > b:
                raise ApiError(400, f"{key} 的 min 不能大于 max（允许相等=固定值）", "validation")
            return a, b

        te_range = _range("te_range")
        ne_range = _range("ne_range")
        for te in te_range:
            _positive(te, '实际 Te')
        try:
            for exponent in ne_range:
                _positive(10.0 ** exponent, '实际 Ne')
        except OverflowError:
            raise ApiError(400, 'Ne 指数产生非有限密度', 'validation') from None
        if params.mode in ('dynamic','server') and params.broadening != 'local' and not params.resample:
            raise ApiError(400, '客户端计算的 NIST 展宽批量须选择统一重采样', 'validation')
        comps: List[BatchSample] = []
        for i, row in enumerate(d.get("compositions", [])):
            rd = _require_dict(row, f"compositions[{i}]")
            items = [CompositionItem.from_api(x, f"compositions[{i}].items") for x in rd.get("items", [])]
            validate_composition(items, f"compositions[{i}]（{rd.get('name', i)}）")
            comps.append(BatchSample(name=str(rd.get("name", f"sample-{i+1}")), items=items))
        if not comps:
            raise ApiError(400, "compositions 候选池不能为空", "validation")
        cells = sum(Parameters.from_dict(e['parameters']).points for e in template_plan['entries']) if template_plan else n * params.points_estimate()
        if cells > MAX_BATCH_CELLS:
            raise ApiError(400, f"批量光谱单元 {cells:,} 超过上限 {MAX_BATCH_CELLS:,}", "validation")
        return BatchRequest(params=params, n_samples=n, seed=seed,
                            te_range=te_range, ne_range=ne_range, compositions=comps, batch_size=batch_size,template_plan=template_plan)


@dataclass
class ScanRequest:
    params: CommonParams
    axis: str                          # te | ne | r
    start: float
    end: float
    frames: int
    composition: List[CompositionItem] = field(default_factory=list)

    @staticmethod
    def from_api(raw: Any) -> "ScanRequest":
        d = _require_dict(raw, "body")
        params = CommonParams.from_api(d.get("params"))
        comp = [CompositionItem.from_api(x) for x in d.get("composition", [])]
        validate_composition(comp)
        axis = d.get("axis")
        if axis not in ("te", "ne", "r"):
            raise ApiError(400, "axis 只能是 te / ne / r", "validation")
        start = _finite(d.get("start"), "start")
        end = _finite(d.get("end"), "end")
        if axis == "ne":
            start, end = _positive(start, "start"), _positive(end, "end")
            try:
                _positive(10**start,'实际Ne起点');_positive(10**end,'实际Ne终点')
            except OverflowError:raise ApiError(400,'Ne指数产生非有限密度','validation') from None
        if axis == "te" or axis == "ne":
            if not (start < end):
                raise ApiError(400, "扫描需要 start < end", "validation")
        else:  # R 轴：取整后仍需递增
            if int(start) >= int(end):
                raise ApiError(400, "R 扫描取整后需要 start < end", "validation")
        frames = _int(d.get("frames"), "frames", minimum=2)
        if frames > MAX_SCAN_FRAMES:
            raise ApiError(400, f"帧数超过上限 {MAX_SCAN_FRAMES}", "validation")
        if axis == "r":
            values = scan_values(start, end, frames)
            rounded = [int(round(v)) for v in values]
            if len(set(rounded)) != len(rounded):
                raise ApiError(400, "R 扫描各帧取整后出现重复值，请减少帧数或扩大范围", "validation")
        cells = frames * params.points_estimate()
        if cells > MAX_BATCH_CELLS:
            raise ApiError(400, f"扫描光谱单元 {cells:,} 超过上限 {MAX_BATCH_CELLS:,}", "validation")
        return ScanRequest(params=params, axis=axis, start=start, end=end, frames=frames,
                           composition=comp)


def scan_values(start: float, end: float, frames: int) -> List[float]:
    """帧数模式：均匀采样并包含两端。"""
    if frames < 2:
        return [start]
    values=[start + (end - start) * (i / (frames - 1)) for i in range(frames)]
    values[0],values[-1]=start,end
    if not all(math.isfinite(v) for v in values):raise ApiError(400,'扫描派生值非有限','validation')
    return values


# ======================================================================
# 事件与任务
# ======================================================================

@dataclass
class JobEvent:
    seq: int
    ts: str
    job_id: str
    type: str                        # status | log | progress
    message: str = ""
    level: str = "info"              # info | ok | warn | error
    status: Optional[str] = None     # queued | running | completed | failed | cancelled
    progress: Optional[float] = None # 0~100
    final: bool = False              # 终态事件（SSE 收到后可断开）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq, "ts": self.ts, "job_id": self.job_id, "type": self.type,
            "message": self.message, "level": self.level,
            "status": self.status, "progress": self.progress, "final": self.final,
        }


class EventQueue:
    """任务的订阅队列：后端 push，SSE 连接消费。get() 返回 (kind, event)，
    kind ∈ {"event", "close", "timeout"}。"""

    _CLOSE = object()

    def __init__(self) -> None:
        self._q: "queue.Queue[Any]" = queue.Queue()

    def push(self, event: JobEvent) -> None:
        self._q.put(event)

    def close(self) -> None:
        self._q.put(self._CLOSE)

    def get(self, timeout: float) -> Tuple[str, Optional[JobEvent]]:
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            return "timeout", None
        if item is self._CLOSE:
            return "close", None
        return "event", item


# ======================================================================
# 后端协议 —— 真实程序接入时实现此协议即可
# ======================================================================

@dataclass
class ExportPayload:
    payload: Any          # str（文本）或 bytes（二进制）
    media_type: str
    filename: str


class SimlibsBackend(Protocol):
    """真实后端需要实现的最小接口。

    语义约定：
    - 所有 start_* 立即返回 job_id，任务在后台执行，进度通过 JobEvent 推送；
    - 失败/取消不伪造成功结果；取消保留上一次成功结果；
    - 校验失败抛 ApiError(400, ...)；
    - result/export 为纯 JSON-able 或文件负载，便于直接下载。
    """

    def api_version(self) -> str: ...
    def engine_status(self) -> Dict[str, Any]: ...
    def default_params(self) -> Dict[str, Any]: ...
    def preview(self, params: CommonParams, elements: List[str]) -> Dict[str, Any]: ...
    def start_single(self, req: SingleRequest) -> str: ...
    def start_batch(self, req: BatchRequest) -> str: ...
    def start_scan(self, req: ScanRequest) -> str: ...
    def cancel(self, job_id: str) -> bool: ...
    def list_jobs(self) -> List[Dict[str, Any]]: ...
    def get_job(self, job_id: str) -> Dict[str, Any]: ...
    def get_result(self, job_id: str) -> Dict[str, Any]: ...
    def export(self, job_id: str, kind: str, frame: Optional[int] = None) -> ExportPayload: ...
    def get_settings(self) -> Dict[str, Any]: ...
    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]: ...
