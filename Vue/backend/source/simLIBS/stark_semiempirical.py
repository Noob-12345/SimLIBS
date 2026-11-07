"""Dimitrijevic & Konjevic (1980) 修正半经验 Stark 展宽，式 (6)-(10)。

文献: JQSRT 24, 451-459, DOI: 10.1016/0022-4073(80)90014-X。
适用于双/三电离离子的孤立谱线、电子碰撞近似、LS 耦合。
只使用 Python 标准库；由 stark_resolver 在可靠原子输入齐备时接入主模拟器。

输入单位: wavelength_nm 为 nm，temperature_k 为 K，electron_density_cm3
为 cm^-3，delta_e_ev 为 eV，matrix_element_sq_a0 为以 a0^2 为单位的数值。
ion_charge 是实际电荷数 q (2 或 3)，论文中的 Z=q+1，不是原子序数。
n_eff 为有效主量子数；能量须相对于对应离子芯的电离阈值确定。
same_n 必须显式列出相关的同 n 跃迁阵列，不会把缺少数据解释为零贡献。

矩阵元应对所有分量/末态磁子态求和，并对初态磁子态平均。它不是
未作简并度处理的线强 S，也不只是径向积分平方。对 l+1 和 l-1 两个
阵列应提供完整数据；不存在的阵列可省略，未知的阵列不可直接省略。
可使用 same_n_matrix_element_sq 按式 (8) 计算；phi 必须由调用者提供，
本文件不实现 Bates-Damgaard 径向积分表，phi=1 只能作为显式近似。

数值约定:
* 式 (7) 的 R^2 是以 a0^2 为单位的数值；前因子已含 hbar^2/m_e^2，
  不能再乘 a0^2。SI 计算中只需把 Ne 从 cm^-3 换为 m^-3。
* g(x) 取原文给出的 2,3,5,10,30,100 节点；节点间对 log(x) 线性插值。
  原文未指定插值算法，这属于本实现明确选择的数值约定。
* 同 n 项统一用式 (6): g_tilde=0.7-1.1/Z+g。原文前文另提到阈值
  0.9-1/Z，与式 (6) 不完全一致；这里以编号公式为准，不混用两者。
* 每项 x=3kT/(2 delta_E)>50 时均切换到式 (10) 的 GBKO 高温极限；
  不进行额外平滑，切换点可能有跳变，原文未给出平滑方案。

返回 FWHM (rad/s、nm、Angstrom)、HWHM (nm) 和逐项贡献。nm 换算
采用窄线近似 delta_lambda=lambda^2*delta_omega/(2*pi*c)。现有 simLIBS
渲染器的宽度参数是 HWHM；使用本结果时不得再次把 FWHM 乘二。
模型不自动验证谱线隔离、碰撞近似或 LS 耦合，不包含仪器/多普勒展宽。

命令行 (先在本文件所在目录打开终端):
    python stark_semiempirical.py --example
    python stark_semiempirical.py --input line.json
--example 打印纯演示用合成数据，不代表任何真实元素。

函数调用示例 (原子数据同样是合成演示数据):
    lower = Level(3.0, 0, (Perturber(2.0, 18.0),))
    upper = Level(3.0, 1, (Perturber(2.0, 6.0), Perturber(2.0, 7.5)))
    result = calculate_stark_width(
        wavelength_nm=500.0, temperature_k=10000.0,
        electron_density_cm3=1e17, ion_charge=2, lower=lower, upper=upper)
    print(result.fwhm_nm)
"""
from dataclasses import asdict, dataclass
import argparse
import json
import math
from numbers import Integral, Real
from pathlib import Path
from typing import Optional, Tuple


HBAR = 1.054571817e-34  # J s
ELECTRON_MASS = 9.1093837015e-31  # kg
BOLTZMANN = 1.380649e-23  # J/K
BOLTZMANN_EV = 8.617333262145e-5  # eV/K
HYDROGEN_IONIZATION_EV = 13.605693122994
LIGHT_SPEED = 299792458.0  # m/s
GAUNT_NODES = ((2., .20), (3., .24), (5., .33), (10., .56), (30., .98), (100., 1.33))


def _finite(name, value, *, zero=False):
    if (isinstance(value, bool) or not isinstance(value, Real) or
            not math.isfinite(value) or (value < 0 if zero else value <= 0)):
        qualifier = 'nonnegative' if zero else 'positive'
        raise ValueError(f'{name} must be a finite {qualifier} number')
    return float(value)


def _charge(ion_charge):
    if isinstance(ion_charge, bool) or not isinstance(ion_charge, Integral) or ion_charge not in (2, 3):
        raise ValueError('ion_charge must be 2 or 3 (actual ionic charge q; paper Z=q+1)')
    return int(ion_charge) + 1


def _orbital(l):
    if isinstance(l, bool) or not isinstance(l, Integral) or l < 0:
        raise ValueError('l must be a nonnegative integer orbital angular momentum')
    return int(l)


@dataclass(frozen=True)
class Perturber:
    """一个同 n 碰撞跃迁阵列：绝对能级间隔与平均矩阵元平方。"""

    delta_e_ev: float
    matrix_element_sq_a0: float
    label: str = ''

    def __post_init__(self):
        object.__setattr__(self, 'delta_e_ev', _finite('delta_e_ev', self.delta_e_ev))
        object.__setattr__(self, 'matrix_element_sq_a0',
                           _finite('matrix_element_sq_a0', self.matrix_element_sq_a0, zero=True))


@dataclass(frozen=True)
class Level:
    """光学跃迁的一个端点；different_n_sum 默认用式 (9) 估计。"""

    n_eff: float
    l: int
    same_n: Tuple[Perturber, ...]
    different_n_sum_a0_sq: Optional[float] = None

    def __post_init__(self):
        object.__setattr__(self, 'n_eff', _finite('n_eff', self.n_eff))
        object.__setattr__(self, 'l', _orbital(self.l))
        if not isinstance(self.same_n, (list, tuple)) or not self.same_n:
            raise ValueError('same_n must explicitly contain the relevant same-n perturbing arrays')
        if any(not isinstance(p, Perturber) for p in self.same_n):
            raise ValueError('same_n entries must be Perturber objects')
        object.__setattr__(self, 'same_n', tuple(self.same_n))
        if self.different_n_sum_a0_sq is not None:
            object.__setattr__(self, 'different_n_sum_a0_sq',
                               _finite('different_n_sum_a0_sq', self.different_n_sum_a0_sq, zero=True))


@dataclass(frozen=True)
class Contribution:
    level: str
    channel: str
    label: str
    delta_e_ev: float
    matrix_element_sq_a0: float
    x: float
    gaunt_factor: Optional[float]
    gaunt_regime: str
    weighted_matrix_element_sq_a0: float
    fwhm_rad_s: float


@dataclass(frozen=True)
class StarkWidth:
    wavelength_nm: float
    temperature_k: float
    electron_density_cm3: float
    ion_charge: int
    fwhm_rad_s: float
    fwhm_nm: float
    weighted_sum_a0_sq: float
    contributions: Tuple[Contribution, ...]

    @property
    def fwhm_angstrom(self):
        return self.fwhm_nm * 10

    @property
    def hwhm_nm(self):
        return self.fwhm_nm / 2

    def to_dict(self):
        out = asdict(self)
        out.update(fwhm_angstrom=self.fwhm_angstrom, hwhm_nm=self.hwhm_nm,
                   method='Dimitrijevic-Konjevic 1980 modified semiempirical, Eqs. (6)-(10)')
        return out


def effective_principal_quantum_number(binding_energy_ev, ion_charge):
    """由到相关离子芯电离阈值的正束缚能求 n_eff=Z*sqrt(E_H/E_bind)。"""
    z = _charge(ion_charge)
    binding = _finite('binding_energy_ev', binding_energy_ev)
    return z * math.sqrt(HYDROGEN_IONIZATION_EV / binding)


def same_n_matrix_element_sq(n_eff, l, l_prime, ion_charge, *, phi):
    """式 (8)，返回以 a0^2 为单位的数值；phi 是径向积分修正因子。"""
    n = _finite('n_eff', n_eff)
    l, lp = _orbital(l), _orbital(l_prime)
    z = _charge(ion_charge)
    correction = _finite('phi', phi, zero=True)
    if abs(l-lp) != 1:
        raise ValueError('Dipole arrays require l_prime = l +/- 1')
    largest = max(l, lp)
    if n <= largest:
        raise ValueError('Eq. (8) requires n_eff > max(l, l_prime)')
    return (3*n/(2*z))**2 * largest/(2*l+1) * (n*n-largest*largest) * correction**2


def different_n_matrix_sum(n_eff, l, ion_charge):
    """式 (9) 的全部 delta_n != 0 矩阵元平方之和，以 a0^2 为单位。"""
    n, l, z = _finite('n_eff', n_eff), _orbital(l), _charge(ion_charge)
    return (3*n/(2*z))**2 * (n*n+3*l*l+3*l+11)/9


def tabulated_gaunt_factor(x):
    """原文 g(x)；0<=x<=2 为 0.2，2<x<=100 按 log(x) 插值。"""
    x = _finite('x', x, zero=True)
    if x <= 2:
        return .2
    for (left, gl), (right, gr) in zip(GAUNT_NODES, GAUNT_NODES[1:]):
        if x <= right:
            fraction = math.log(x/left) / math.log(right/left)
            return gl + fraction*(gr-gl)
    raise ValueError('Tabulated g(x) is only defined through x=100; use gaunt_factor for GBKO')


def gaunt_factor(x, *, n_eff, ion_charge, same_n):
    """式 (6)/(10)；逐项以 x>50 选择 GBKO，same_n=False 时使用 g。"""
    x = _finite('x', x, zero=True)
    n, z = _finite('n_eff', n_eff), _charge(ion_charge)
    if type(same_n) is not bool:
        raise ValueError('same_n must be boolean')
    if x > 50:
        # 2 Z kT / (n^2 delta_E) = 4 Z x / (3 n^2).
        value = math.sqrt(3)/math.pi * (.5 + math.log(4*z*x/(3*n*n)))
        if value <= 0:
            raise ValueError('GBKO factor is nonpositive for these n_eff and x; asymptotic regime is invalid')
        return value
    base = tabulated_gaunt_factor(x)
    return .7 - 1.1/z + base if same_n else base


def calculate_stark_width(*, wavelength_nm, temperature_k, electron_density_cm3,
                          ion_charge, lower, upper):
    """式 (7)：返回电子碰撞 FWHM 及各项贡献，原子数据由调用者提供。"""
    wavelength = _finite('wavelength_nm', wavelength_nm)
    temperature = _finite('temperature_k', temperature_k)
    density = _finite('electron_density_cm3', electron_density_cm3, zero=True)
    z = _charge(ion_charge)
    if not isinstance(lower, Level) or not isinstance(upper, Level):
        raise ValueError('lower and upper must be Level objects with explicit perturbing arrays')
    prefactor = (density*1e6 * (8*math.pi/3) * (HBAR/ELECTRON_MASS)**2
                 * math.sqrt(2*ELECTRON_MASS/(math.pi*BOLTZMANN*temperature))
                 * math.pi/math.sqrt(3))
    energy_ev = 1.5*BOLTZMANN_EV*temperature
    contributions = []
    for name, level in (('lower', lower), ('upper', upper)):
        matrix_sum = level.different_n_sum_a0_sq
        if matrix_sum is None:
            matrix_sum = different_n_matrix_sum(level.n_eff, level.l, ion_charge)
        gap = 2*z*z*HYDROGEN_IONIZATION_EV/level.n_eff**3
        arrays = [(p.delta_e_ev, p.matrix_element_sq_a0, True, p.label) for p in level.same_n]
        arrays.append((gap, matrix_sum, False, 'n -> n+1 estimate; summed delta_n != 0'))
        for gap, r2, same, label in arrays:
            x = energy_ev/gap
            if r2 == 0:
                # A zero strength is identically zero even outside the Gaunt domain.
                # Keep the row for auditing; None means the factor was not evaluated.
                contributions.append(Contribution(
                    name, 'delta_n=0' if same else 'delta_n!=0', label, gap, r2, x,
                    None, 'zero-matrix-element', 0., 0.))
                continue
            g = gaunt_factor(x, n_eff=level.n_eff, ion_charge=ion_charge, same_n=same)
            weighted = r2*g
            contributions.append(Contribution(
                name, 'delta_n=0' if same else 'delta_n!=0', label, gap, r2, x, g,
                'GBKO' if x > 50 else ('modified-table' if same else 'table'),
                weighted, prefactor*weighted))
    weighted_sum = math.fsum(c.weighted_matrix_element_sq_a0 for c in contributions)
    omega = prefactor*weighted_sum
    width_nm = omega*(wavelength*1e-9)**2/(2*math.pi*LIGHT_SPEED)*1e9
    return StarkWidth(wavelength, temperature, density, int(ion_charge), omega, width_nm,
                      weighted_sum, tuple(contributions))


def _example():
    return dict(
        description='synthetic demonstration only; NOT measured atomic data for any element',
        wavelength_nm=500., temperature_k=10000., electron_density_cm3=1e17, ion_charge=2,
        lower=dict(n_eff=3., l=0, same_n=[dict(delta_e_ev=2., matrix_element_sq_a0=18.)]),
        upper=dict(n_eff=3., l=1, same_n=[dict(delta_e_ev=2., matrix_element_sq_a0=6.),
                                       dict(delta_e_ev=2., matrix_element_sq_a0=7.5)]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--example', action='store_true', help='print synthetic input JSON (not a real line)')
    mode.add_argument('--input', type=Path, help='UTF-8 JSON file; use --example to see its schema')
    args = parser.parse_args(argv)
    if args.example:
        print(json.dumps(_example(), indent=2, ensure_ascii=True))
        return 0
    try:
        data = json.loads(args.input.read_text(encoding='utf-8-sig'))
        params = {name: data[name] for name in ('wavelength_nm', 'temperature_k',
                                               'electron_density_cm3', 'ion_charge')}
        for name in ('lower', 'upper'):
            level = dict(data[name])
            level['same_n'] = tuple(Perturber(**p) for p in level['same_n'])
            params[name] = Level(**level)
        out = calculate_stark_width(**params).to_dict()
        if 'description' in data:
            out['input_description'] = data['description']
        print(json.dumps(out, indent=2, ensure_ascii=True, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
