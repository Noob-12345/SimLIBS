"""可序列化的输入契约；GUI 和 worker 使用相同的严格校验。"""
from dataclasses import asdict, dataclass, replace
import math
from urllib.parse import urlsplit,parse_qs

ELEMENTS = frozenset('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split())
MAX_POINTS = 200_000
MAX_CELLS = 5_000_000
MAX_FRAMES = 200


def intensity_scale_from_origin(origin):
    origin=origin or {}
    explicit=origin.get('intensity_scale') or (origin.get('parameters') or {}).get('intensity_scale')
    if explicit in ('photon','energy'):return explicit
    if origin.get('kind')=='history':return 'unknown'
    number=parse_qs(urlsplit(origin.get('nist_url') or '').query).get('int_scale',[''])[0]
    return {'1':'energy','2':'photon'}.get(number,'unknown')


def finite(value, label, positive=False):
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'{label} 必须是数值') from None
    if not math.isfinite(n) or (positive and n <= 0):
        raise ValueError(f'{label} 必须是有限的' + ('正数' if positive else '数值'))
    return n


def integer(value, label, minimum=0):
    if isinstance(value, bool):
        raise ValueError(f'{label} 必须为整数，不能是布尔值')
    n = finite(value, label)
    if not n.is_integer() or n < minimum:
        raise ValueError(f'{label} 必须为 >= {minimum} 的整数')
    return int(n)


def finite_total(values):
    try:
        total = math.fsum(values)
    except OverflowError:
        raise ValueError('占比总和超出有限数值范围') from None
    return finite(total, '占比总和')


def composition(elements, percentages, require_total=True):
    e = tuple(str(x).strip() for x in elements)
    p = tuple(finite(x, '元素占比') for x in percentages)
    if not e or len(e) != len(p):
        raise ValueError('元素不能为空，元素与占比数量必须一致')
    if len(set(e)) != len(e) or any(x not in ELEMENTS for x in e):
        raise ValueError('元素符号无效或重复（区分大小写，如 H、He、Fe）')
    if any(x < 0 for x in p):
        raise ValueError('元素占比不能为负数')
    total = finite_total(p)
    if require_total and not math.isclose(total, 100, abs_tol=1e-6, rel_tol=0):
        raise ValueError(f'元素占比总和为 {total:.10g}%，应为 100%；可主动点击归一化')
    return e, p


def normalize(percentages):
    p = [finite(x, '元素占比') for x in percentages]
    total = finite_total(p)
    if any(x < 0 for x in p) or total <= 0:
        raise ValueError('归一化要求非负占比且总和大于零')
    return [x / total * 100 for x in p]


@dataclass(frozen=True)
class Parameters:
    Te: float = 1.0
    Ne: float = 1e17
    resolution: int = 1000
    low_w: float = 650.0
    upper_w: float = 660.0
    max_ion_charge: int = 2
    webscraping: str = 'static'
    mode_version: int = 1
    headless: bool = True
    elements: tuple = ('H',)
    percentages: tuple = (100.0,)
    step: float = 0.005
    resample: bool = False
    intensity_scale: str = 'photon'
    # 数据抓取模式重塑（2026-10-03）：默认值完全保持旧行为
    broadening: str = 'nist'            # nist=服务端/页面展宽；local=本地线表展宽
    broaden_convention: str = 'nist'    # nist: w=λ/R（1/e 半宽）；physics: FWHM=λ/R
    broaden_grid_step: float = 0.005    # 本地合成网格步长 [nm]
    broaden_center_decimals: int | None = None  # 线中心舍入位数；None=保留 Ritz 波长
    broaden_min_rel_int: float = 0.0    # 本地展宽时的选线阈值（建议 0）
    local_gaussian_nm: float = 0.0
    local_lorentz_nm: float = 0.0
    local_temperature_K: float = 0.0
    local_temperature_mode: str = 'manual'  # absent legacy field keeps independent K=0 semantics

    @property
    def effective_temperature_K(self):
        value=float(self.Te)*(1.602176634e-19/1.380649e-23) if self.local_temperature_mode=='linked' else float(self.local_temperature_K)
        return finite(value,'有效重粒子温度K')

    @property
    def points(self):
        if self.broadening == 'local':
            # 本地展宽：合成网格 + （可选）插值网格，取更密者做上限校验
            steps = [float(self.broaden_grid_step)]
            if self.resample:
                steps.append(float(self.step))
            quotient = (float(self.upper_w) - float(self.low_w)) / min(steps)
        else:
            step = .005 if self.webscraping == 'static' and not self.resample else float(self.step)
            quotient = (float(self.upper_w) - float(self.low_w)) / step
        if not math.isfinite(quotient):
            raise ValueError('网格点数超出有限范围，请缩小波段或增加步长')
        return math.ceil(quotient) + (1 if self.broadening == 'local' else 0)

    def validated(self):
        e, p = composition(self.elements, self.percentages)
        values = {k: finite(getattr(self, k), k, True) for k in ('Te', 'Ne', 'low_w', 'upper_w', 'step')}
        values['resolution'] = integer(self.resolution, '分辨率 R', 1)
        values['max_ion_charge'] = integer(self.max_ion_charge, '最大离子电荷')
        if values['max_ion_charge']>2:raise ValueError('新模拟最大离子电荷须为0–2；历史结果保持原记录')
        if values['upper_w'] <= values['low_w']:
            raise ValueError('波长上界必须大于下界')
        if self.webscraping not in ('static', 'dynamic', 'server', 'client','local'):
            raise ValueError('模式必须为 static/dynamic（旧版）或 server/client（v2）')
        expected_version = 2 if self.webscraping in ('server', 'client','local') else 1
        if integer(self.mode_version, '模式版本', 1) != expected_version:
            raise ValueError('模式字段与版本不一致；server/client 需要 mode_version=2')
        if self.mode_version == 2:
            expected = 'nist' if self.webscraping == 'server' else 'local'
            if self.broadening != expected:
                raise ValueError('v2 计算模式固定展宽路径，不能独立组合')
            if self.webscraping == 'server' and values['resolution'] < 100:
                raise ValueError('官方 JS Recalculate 要求 R >= 100')
            if self.webscraping=='server' and (self.broaden_convention!='nist' or self.broaden_center_decimals is not None):
                raise ValueError('服务器 v2 使用官方 JS 约定；Python 展宽高级参数仅适用于客户端')
        if self.intensity_scale not in ('photon','energy'):
            raise ValueError('强度尺度必须为 photon 或 energy（NIST相对通量）')
        if self.webscraping=='local' and self.intensity_scale!='photon':raise ValueError('本地模拟使用相对photon强度')
        if self.webscraping=='local' and self.broaden_convention!='physics':raise ValueError('离线本地使用FWHM=lambda/R物理约定')
        for key in ('local_gaussian_nm','local_lorentz_nm','local_temperature_K'):
            values[key]=finite(getattr(self,key),key)
            if values[key]<0:raise ValueError(f'{key}不能为负')
        if self.local_temperature_mode not in ('linked','manual'):raise ValueError('热Doppler温度模式须为linked/manual')
        if self.broadening not in ('nist', 'local'):
            raise ValueError("broadening 必须为 'nist' 或 'local'")
        if self.broaden_convention not in ('nist', 'physics'):
            raise ValueError("broaden_convention 必须为 'nist' 或 'physics'")
        values['broaden_grid_step'] = finite(self.broaden_grid_step, 'broaden_grid_step', True)
        if self.broaden_center_decimals is not None:
            values['broaden_center_decimals'] = integer(self.broaden_center_decimals, 'broaden_center_decimals', 0)
        values['broaden_min_rel_int'] = finite(self.broaden_min_rel_int, 'broaden_min_rel_int')
        if values['broaden_min_rel_int'] < 0:
            raise ValueError('broaden_min_rel_int 不能为负')
        if type(self.headless) is not bool or type(self.resample) is not bool:
            raise ValueError('headless/resample 必须为布尔值')
        out = replace(self, elements=e, percentages=p, **values)
        if out.webscraping=='local':out.effective_temperature_K
        # UI 子类在原 static 构造首次 interpolate 时即使用显式步长。
        if out.points > MAX_POINTS:
            raise ValueError(f'单谱最多 {MAX_POINTS} 点；请缩小波长范围或调整步长')
        return out

    def request_composition(self):
        pairs = [(e, p) for e, p in zip(self.elements, self.percentages) if p > 0]
        return [e for e, _ in pairs], [p for _, p in pairs]

    def deadline(self, settings):
        return settings.dynamic_deadline if self.webscraping in ('dynamic', 'server') else settings.static_deadline

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data).validated()


def scan_values(axis, start, stop, count=None, step=None):
    if axis not in ('Te', 'Ne', 'R'):
        raise ValueError('扫描轴必须是 Te、Ne 或 R')
    a, b = finite(start, '起点', True), finite(stop, '终点', True)
    if b < a:
        raise ValueError('扫描终点不能小于起点')
    if step is not None:
        s = finite(step, '扫描步长', True)
        ratio = (b - a) / s
        if not math.isfinite(ratio) or ratio > MAX_FRAMES:
            raise ValueError('扫描最多 200 帧，请增大步长')
        n = math.floor(ratio + 1e-9) + 1
        if n > MAX_FRAMES:
            raise ValueError(f'扫描最多 {MAX_FRAMES} 帧')
        values = [float(f'{a + i * s:.14g}') for i in range(n)]
        values[0] = a
        if len(values) > 1 and math.isclose(values[-1], b, rel_tol=1e-12, abs_tol=1e-12):
            values[-1] = b
        elif values[-1] != b:
            values.append(b)  # 固定终点包含，最后一段允许小于步长。
    else:
        n = integer(count, '帧数', 1)
        if n > MAX_FRAMES or (n == 1 and a != b):
            raise ValueError('帧数须 <= 200；不同起止值至少需要 2 帧')
        # 先形成 [0,1] 内比例，避免 delta*i 在大有限区间内先溢出。
        values = [a] if n == 1 else [a + (b - a) * (i / (n - 1)) for i in range(n)]
        values[0], values[-1] = a, b
    if len(values) > MAX_FRAMES:
        raise ValueError('扫描最多 200 帧')
    if axis == 'R':
        values = [integer(round(finite(x, '扫描 R', True)), '扫描 R', 1) for x in values]
    return checked_scan_frames(axis, a, b, values)


def checked_scan_frames(axis, start, stop, values):
    """派生帧也必须满足有限、边界、端点、顺序及轴类型契约。"""
    if axis not in ('Te', 'Ne', 'R'):
        raise ValueError('扫描轴必须是 Te、Ne 或 R')
    a, b = finite(start, '起点', True), finite(stop, '终点', True)
    if b < a or not values or len(values) > MAX_FRAMES:
        raise ValueError('扫描范围或帧数无效（最多 200 帧）')
    if axis == 'R':
        a, b = integer(round(a), '起点 R', 1), integer(round(b), '终点 R', 1)
    result = []
    for i, value in enumerate(values, 1):
        value = integer(value, f'第 {i} 帧 R', 1) if axis == 'R' else finite(value, f'第 {i} 帧 {axis}', True)
        if not a <= value <= b:
            raise ValueError(f'第 {i} 帧 {axis} 超出扫描范围')
        result.append(value)
    if result[0] != a or result[-1] != b:
        raise ValueError('扫描必须包含实际起点和终点')
    if a < b and any(right <= left for left, right in zip(result, result[1:])):
        raise ValueError('扫描帧未严格递增或浮点精度不足，请减少帧数或扩大范围')
    if axis == 'R' and len(set(result)) != len(result):
        raise ValueError('R 扫描取整后出现重复值，请减少帧数')
    return result


@dataclass(frozen=True)
class BatchSpec:
    size: int = 2
    Te_min: float = 1.0
    Te_max: float = 1.0
    Ne_min: float = 1e17
    Ne_max: float = 1e17
    seed: int = 42
    batch_size: int = 32

    def validated(self, params, check_cells=True):
        p = params.validated()
        if p.webscraping in ('dynamic', 'server') and p.broadening != 'local' and not p.resample:
            raise ValueError('动态批量须主动选择统一重采样网格')
        size = integer(self.size, '样本数', 1)
        batch_size = integer(self.batch_size, '每 batch 的光谱数', 1)
        if size > 5000 or batch_size > 5000:
            raise ValueError('样本数和每 batch 的光谱数均须 <= 5000')
        vals = {k: finite(getattr(self, k), k, True) for k in ('Te_min', 'Te_max', 'Ne_min', 'Ne_max')}
        if vals['Te_min'] > vals['Te_max'] or vals['Ne_min'] > vals['Ne_max']:
            raise ValueError('采样范围最小值不能大于最大值')
        if check_cells and size * p.points > MAX_CELLS:
            raise ValueError('批量最多 5000000 个光谱单元，请减少样本数或网格点数')
        return replace(self, size=size, batch_size=batch_size, seed=integer(self.seed, '随机种子'), **vals)


@dataclass(frozen=True)
class ScanSpec:
    axis: str = 'Te'
    start: float = 1.0
    stop: float = 2.0
    count: int = 2
    step: float | None = None

    def validated(self, params):
        p = params.validated()
        values = scan_values(self.axis, self.start, self.stop, self.count, self.step)
        values = checked_scan_frames(self.axis, self.start, self.stop, values)
        field = 'resolution' if self.axis == 'R' else self.axis
        for value in values:
            replace(p, **{field: value}).validated()
        if len(values) * p.points > MAX_CELLS:
            raise ValueError('扫描最多 5000000 个光谱单元，请减少帧数或网格点数')
        return values
