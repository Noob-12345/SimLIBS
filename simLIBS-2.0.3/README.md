# simLIBS 中文使用说明

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE.md)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.7260706.svg)](https://doi.org/10.5281/zenodo.7260706)

simLIBS 根据元素组成、电子温度和电子密度生成 LIBS 模拟光谱，可用于单次模拟、绘图、CSV 导出及批量数据集生成。本说明对应当前目录的源码版本。

**日常调用统一使用 `SimulatedLIBS`。** `simulation.py` 负责组织整个流程，`nist_lines.py` 和 `nist_self_absorption.py` 由主类内部调用。

```python
from simLIBS import SimulatedLIBS
```

## 1. 环境与安装

当前源码使用了 `match/case`，需要 **Python 3.10 或更高版本**。虽然 `setup.cfg` 中仍声明 `>=3.8`，运行本目录源码时应按实际语法要求选择环境。

先激活对应的 Python 环境，再在项目目录安装本地源码。下面使用当前仓库的 Windows 路径：

```powershell
cd D:\LIBS\SimLIBS\simLIBS-2.0.3
python --version
python -m pip install -e .
```

可编辑安装后，修改此目录中的代码会直接用于后续调用。主要依赖为 `numpy`、`pandas`、`scipy`、`matplotlib`、`requests`、`bs4`、`selenium` 和 `webdriver-manager`。

- `static`：需要联网访问 NIST，使用本地 Python 计算线形。
- `dynamic`：需要 Chrome，程序通过 Selenium 操作 NIST 页面并导出结果；驱动由 `webdriver-manager` 获取。
- Stark 系数统一来自 STARK-B 数据库，可复用已验证的数据库响应缓存。

确认实际导入的是正在编辑的源码，可以运行：

```python
import inspect
from simLIBS import SimulatedLIBS

print(inspect.getfile(SimulatedLIBS))
```

## 2. 快速开始：普通静态模拟

下面的例子获取 Mg 的 NIST 计算谱线，在本地做高斯展宽，读取结果、绘图并保存 CSV。

```python
from pathlib import Path

import matplotlib.pyplot as plt
from simLIBS import SimulatedLIBS

output = Path("output/basic_static")
output.mkdir(parents=True, exist_ok=True)

libs = SimulatedLIBS(
    Te=1.0,                  # 电子温度，eV
    Ne=1e17,                 # 电子密度，cm^-3
    elements=["Mg"],
    percentages=[100.0],
    low_w=280.0,             # 波长下界，nm
    upper_w=290.0,           # 波长上界，nm
    resolution=3000,         # 仪器分辨率 R
    max_ion_charge=2,        # 允许中性、一价和二价离子发射
    webscraping="static",
    self_absorption=False,
    stark_broadening=False,     # 本例只使用仪器高斯展宽
    instrument_broadening=True,
)

spectrum = libs.get_interpolated_spectrum()
print(spectrum.head())
libs.save_to_csv(output / "spectrum.csv")

libs.plot(color="blue", title="Mg: static spectrum")
plt.show()
```

创建 `SimulatedLIBS(...)` 时就会请求数据并计算光谱，无须额外调用一个“开始模拟”方法。输出是两列 `pandas.DataFrame`：

| 列名 | 含义 |
| --- | --- |
| `wavelength` | 真空波长，nm |
| `intensity` | 该采样点的模拟谱强度；沿用 NIST 计算线权重，未经实验绝对定标 |

## 3. 怎样选择模拟模式

静态模式下，使用三个独立参数选择处理方式：

| `self_absorption` | `stark_broadening` | `instrument_broadening` | 实际输出 |
| --- | --- | --- | --- |
| `False` | `False` | `True` | NIST 线强 + 仪器高斯 |
| `False` | `True` | `False` | NIST 线强 + 纯 Stark（Lorentz） |
| `False` | `True` | `True` | NIST 线强 + Stark + 仪器高斯（Voigt） |
| `False` | `False` | `False` | 未展宽离散谱线在输出网格上的表示 |
| `True` | `True` | `False` / `True` | Stark + 逐线自吸收，可选仪器高斯 |
| `True` | `False` | 任意 | 报错：当前自吸收公式需要内禀 Stark 宽度 |

不传新增参数时保留旧默认：`stark_broadening=None` 随自吸收开关启用或关闭；`instrument_broadening=None` 在未启用 Stark 时默认开启，在 Stark 路径中使用旧配置的值，默认也为 `True`。显式传入顶层 `instrument_broadening` 时，以顶层值为准。

仅启用 Stark 时，仍通过 `self_absorption_config` 提供系数和采样步长，但不使用其中的光程、总密度进行吸收计算。所有启用 Stark 的组合都需要逐线系数。

两种展宽均关闭时，不赋予谱线物理线宽；程序将线面积分配到相邻采样点，保持梯形积分面积与重心。输出高度随采样步长变化，实际跃迁位置和线面积仍保留在 `line_table`。

`dynamic` 始终使用浏览器导出的结果，忽略这些本地展宽与自吸收配置。

普通静态模式的处理顺序为：

```text
输入组成、Te、Ne
  -> NIST 返回 dataSticksArray 中的未展宽计算谱线
  -> 按核心波段合并谱线表
  -> 本地高斯展宽并相加
  -> 输出总谱
```

静态请求默认使用 `min_rel_int=0` 保留弱线，以 500 nm 为核心波段，内部边界保留 2 nm 请求重叠。谱线按核心区间归属后统一展宽，不逐段归一化，也不按相同波长删除不同跃迁。

`render_sticks()` 中的宽度参数为 `w = wavelength / resolution`，表示高斯 **1/e 半宽**。线形为：

```text
I(lambda) = area / (w * sqrt(pi)) * exp(-((lambda - center) / w)^2)
FWHM = 2 * sqrt(ln(2)) * w
```

其中 `area` 来自 NIST 计算线强。高斯贡献只在中心左右各 6 个 `w` 范围内计算。

## 4. 调用静态逐线自吸收

建议先使用下面的 Si II 窄窗口确认调用流程。该真空波长窗口已有真实 STARK-B 数据验证。

```python
from pathlib import Path

from simLIBS import SimulatedLIBS, MissingStarkDataError

output_sa = Path("output/self_absorption")
output_sa.mkdir(parents=True, exist_ok=True)

try:
    libs_sa = SimulatedLIBS(
        Te=1.0,
        Ne=1e17,
        elements=["Si"],
        percentages=[100.0],
        low_w=634.88,
        upper_w=634.90,
        resolution=3000,
        max_ion_charge=2,
        webscraping="static",
        self_absorption=True,
        stark_broadening=True,
        instrument_broadening=True,
        self_absorption_config={
            "path_length_m": 0.001,           # 光程，m；这里为 1 mm
            "wavelength_step_nm": 0.001,     # 采样步长，nm
        },
    )
except MissingStarkDataError as error:
    error.missing_lines.to_csv(output_sa / "missing_stark.csv", index=False)
    raise  # 导出完整缺失清单后保留异常，便于定位数据问题

libs_sa.save_to_csv(output_sa / "absorbed.csv")
libs_sa.unabsorbed_interpolated_spectrum.to_csv(output_sa / "thin_voigt.csv", index=False)
libs_sa.self_absorption_diagnostics.to_csv(output_sa / "line_diagnostics.csv", index=False)

print(libs_sa.self_absorption_diagnostics[
    ["element", "wavelength_nm", "tau_center", "SA", "thin_fwhm_nm", "absorbed_fwhm_nm"]
])
```

窄窗口适合验证单线流程；要查看完整线翼，可扩大输出波段，并检查新进入波段的其他跃迁在数据库中是否有可用系数。

自吸收路径依次完成以下工作：

1. 从 NIST 获取计算线强、上下能级、`g_upper * Aki`、能级统计权重和电离能。
2. 使用 NIST 页面提供的全部电离阶段及裸核阶段计算配分函数和 Saha 布居。
3. 按原子数百分比计算组分比例。总密度默认通过电荷守恒反推，也可显式指定。
4. 匹配每条参与计算的跃迁所需的 Stark 系数，求未吸收内禀 FWHM。
5. 根据粒子布居和光程计算线中心光学厚度 `tau_center` 及自吸收因子 `SA`。
6. 修正逐线面积和宽度，叠加可选仪器响应，合成 Voigt 光谱。

当前模型使用：

```text
SA = (1 - exp(-tau_center)) / tau_center，tau_center=0 时 SA=1
吸收后 Stark FWHM = 未吸收 Stark FWHM * SA^(-0.54)
吸收后线面积 = NIST 原始线面积 * SA^(0.46)
```

`SA` 表示仪器响应前的内禀 Lorentz 峰高比；经过仪器展宽后，最终峰高比可能改变。仪器宽度不参与光学厚度计算，仪器高斯标准差为 `sigma = wavelength / (R * sqrt(2))`。

这里采用各谱线独立计算的经验模型，尚未处理谱线之间的耦合辐射传输。Stark 宽度采用数据库温度表值、已发布拟合或 VAMDC 表内插值，再按电子密度线性缩放；不推断额外的温度依赖。

### 4.1 自吸收配置参数

`self_absorption_config` 可以使用字典，也可以使用包入口导出的 `NISTSelfAbsorptionConfig` 对象。为兼容已有代码保留了这个名称；仅做 Stark 展宽时同样从这里读取数据库选项及采样步长。

| 配置项 | 默认值 | 含义 |
| --- | --- | --- |
| `path_length_m` | `0.01` | 有效光程，m；允许为 0 |
| `total_number_density_cm3` | `None` | 总粒子数密度，cm^-3；默认通过 `Ne / 平均电荷` 反推 |
| `wavelength_step_nm` | `0.005` | 期望输出采样步长，nm |
| `instrument_broadening` | `True` | 兼容旧调用的仪器开关；顶层同名参数显式传值时优先 |
| `stark_cache_dir` | `None` | 原始数据快照目录；默认 `%LOCALAPPDATA%/simLIBS/stark-v1`，其他系统为用户 `.cache` |
| `stark_allow_network` | `True` | `False` 只读已有 Stark/身份缓存；NIST 计算谱本身仍需联网 |
| `stark_methods` | `("SCP", "MSE")` | 方法优先序；默认也允许 VAMDC 未导出方法的有来源记录，标为 `unreported`；填 `("SCP",)` 则严格只接受明确标注 SCP 的数据 |
| `missing_stark` | `"error"` | `"error"` 在系数缺失时报错；`"unbroadened"` 保留这些谱线及 NIST 面积，关闭其 Stark/自吸收校正，仪器展宽仍按开关执行 |

STARK-B 网页表单不可用时，程序自动查询官方版本化接口
`https://stark-b.obspm.fr/12.07/vamdc/tap/sync`。服务报告截断的响应会分段补取，未能补全时终止取数；原始 XML 和来源 URL 验证后写入缓存。

这个接口提供原始温度/密度表，但未导出网页中的温度拟合系数、计算方法和 C 参数。
因此仅对 VAMDC 来源在表内按温度线性插值，并记录 `stark_temperature_method`、插值两端温度及原始参考密度；不做温度或高密度外推。
`stark_method="unreported"` 和 `stark_isolated_limit_cm3=None` 分别表示方法与隔离线密度上限未知。
这些状态及计数保存在逐线诊断与元数据中，不能据此声称已验证隔离线近似。
默认缺少某条跃迁的已发布系数时仍报 `MissingStarkDataError`，保留缺失清单；可用 `missing_stark="unbroadened"` 继续模拟，见第 5 节。

### 4.2 关闭自吸收，独立调用 Stark 展宽

直接设置 `self_absorption=False`、`stark_broadening=True`。下面关闭仪器高斯，得到纯 Stark 线形：

```python
from simLIBS import SimulatedLIBS

libs_stark = SimulatedLIBS(
    Te=1.0,
    Ne=1e17,
    elements=["Mg"],
    percentages=[100.0],
    low_w=285.27,
    upper_w=285.33,
    resolution=3000,
    max_ion_charge=2,
    webscraping="static",
    self_absorption=False,
    stark_broadening=True,
    instrument_broadening=False,     # 改为 True 即为 Stark + 仪器高斯
    self_absorption_config={
        "wavelength_step_nm": 0.001,
    },
)

stark_spectrum = libs_stark.get_interpolated_spectrum()
```

该路径保留 NIST 计算面积，跳过自吸收所需的完整布居表、Saha、总密度和光学厚度计算。诊断中的 `tau_center=0`、`SA=1`，默认要求逐线 Stark 系数齐全；允许缺失的设置见第 5 节。开启自吸收但将光程设为 0 的旧用法仍然可用。

若已有 `libs_sa`，可读取它的 `unabsorbed_interpolated_spectrum` 作为相同仪器设置下的薄谱参考，避免再次联网。比较两次调用时，要同时核对仪器开关、R 和采样网格。

## 5. Stark 数据来源与覆盖

**Stark 系数统一从 STARK-B 数据库取得，或复用已验证的数据库响应缓存。** 项目已删除内置系数 JSON 和独立离线论文模型；不再接受用户本地系数表或本地数据文件。所有元素和跃迁均执行相同的数据库查询与匹配流程。

自动流程先用 NIST ASD 导出补齐上下态，确认真空 Ritz 波长、上下能量及 `gA`，然后按 STARK-B 的组态、项和 J 匹配。数据库明确给出多重态平均系数时，才允许覆盖相同组态/项的细结构分量，并按来源规定的波长平方比换算。不会按最近波长猜系数。

STARK-B 提供的是有文献出处的理论计算数据，SCP 为半经典微扰法，MSE 为改进半经验法；不等同于每条线都有实验测量。温度优先用表值，否则使用数据库发布的拟合系数；不在表的温度区间外外推。密度不超过数据集上限，保留碰撞近似标记和 `C/W` 隔离线条件；源表未给 C 时诊断中的隔离线上限为 `None`，不能据此保证高密度下的隔离线近似成立。[STARK-B 数据约定](https://stark-b.obspm.fr/index.php/description)

自动查询仍不能保证任意元素、任意电离态、任意波段都有系数。默认严格模式下，任何参与计算的非零跃迁仍缺失时，抛出 `MissingStarkDataError`：`error.missing_lines` 包含缺失原因，`error.matched_lines` 包含已经成功匹配的谱线和来源。

如果希望系数缺失时继续生成光谱，设置 `self_absorption_config={"missing_stark": "unbroadened"}`（可与其他配置合并）。有系数的谱线正常计算；没有系数的谱线保留原始 NIST 面积，不施加 Stark 展宽。开启仪器展宽时，这些谱线仍使用仪器高斯；关闭仪器展宽时，将离散线投影到相邻网格点并保持面积与重心。启用自吸收时，这些缺失谱线也不作自吸收校正。

运行后用 `libs.missing_stark_lines.to_csv("missing_stark.csv", index=False)` 导出缺失谱线、元素、电荷态、真空波长及缺失原因；`libs.matched_stark_lines` 保存已匹配系数。逐线诊断以 `stark_missing`、`stark_broadening_applied`、`self_absorption_applied` 区分处理方式，未能计算的内禀宽度和光学厚度保留为空。元数据 `self_absorption_metadata["stark_data"]` 记录匹配数、缺失数及处理策略。`test.py` 已启用此模式，并在保存光谱后导出缺失清单。

下面的 Si II 示例已实测通过，系数由数据库自动获取：

```python
from simLIBS import SimulatedLIBS

libs_si = SimulatedLIBS(
    Te=1.0, Ne=1e17,
    elements=["Si"], percentages=[100.0],
    low_w=634.88, upper_w=634.90,       # NIST 真空 nm，含 Si II 634.886 nm
    max_ion_charge=1, resolution=3000,
    webscraping="static",
    stark_broadening=True, self_absorption=False,
    self_absorption_config={
        "stark_cache_dir": "cache/stark",
        "wavelength_step_nm": 0.001,
    },
)
print(libs_si.self_absorption_diagnostics[[
    "wavelength_nm", "thin_fwhm_nm", "stark_source", "stark_method"
]])
```

开启自吸收仍使用同一数据源，只需设 `self_absorption=True` 并提供所需光程。`stark_allow_network=False` 只复用已下载的数据库响应，缓存缺失会报取数错误；它不启用本地系数模型。`interpolate()` 直接复用本次已匹配的线宽，不再次查询数据库。更改 Te/Ne 应重新创建模拟，重新检查适用范围。

原始响应按物种/密度缓存，包含取数时间和 SHA-256；结果诊断保留数据集、计算方法、温度处理方式、量子态、NIST 能级 ID 和引用。调试新增组件可依次查看：`stark_b.py`（取表、缓存、单位与适用条件）→ `nist_stark.py`（NIST 身份补全与跨库匹配）→ `nist_self_absorption.py`（组织系数并合成线形）。

### 5.1 线宽字段与单位

`stark_width_nm` 是数据库宽度换算后供渲染器使用的半高半宽 W；`stark_reference_ne_cm3` 是其参考密度。最终内禀宽度为：

```text
Stark FWHM_nm = 2 * stark_width_nm * Ne / stark_reference_ne_cm3
```

数据库原始电子 FWHM 从 Å 换算为 nm，并按来源约定处理波长平方比。在线数据已经缩放到目标 Ne 后，参考密度字段也设为目标 Ne，避免重复缩放；原表参考密度另存于 `stark_table_reference_ne_cm3`。

### 5.2 命令行运行与缺失数据处理

以下命令均在项目目录执行，所有 Stark 宽度使用同一数据库流程：

```powershell
# 默认 Si II 窄窗口：吸收谱、薄谱、NIST 线强、诊断和元数据
python examples/nist_self_absorption_demo.py --output output/nist_self_absorption

# 仅做 Stark 展宽，关闭自吸收和仪器高斯
python examples/nist_self_absorption_demo.py --stark-only --no-instrument-broadening --output output/stark_only

# 下载数据库响应到指定缓存目录
python examples/nist_self_absorption_demo.py --stark-only --cache-dir cache/stark --output output/si_stark

# 复用数据库缓存；NIST 计算谱仍需联网
python examples/nist_self_absorption_demo.py --stark-only --cache-dir cache/stark --offline-stark --output output/si_repeat

# 扩大波段，数据库缺少系数时保留未展宽谱线并记录缺失原因
python examples/nist_self_absorption_demo.py --element Mg --low 280 --high 290 --stark-only --missing-stark unbroadened --output output/mg_stark
```

还可设置 `--te`、`--ne`、`--max-charge` 和 `--stark-methods SCP`。默认缺系数时导出 `missing_stark.csv` 和 `matched_stark.csv`，返回 2；网络或缓存取数失败返回 3。没有本地系数导入选项。

## 6. 主类参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `Te` | `1.0` | 电子温度，eV；使用正值 |
| `Ne` | `1e17` | 电子密度，cm^-3；使用正值 |
| `elements` | `None` | 调用时显式提供元素符号列表 |
| `percentages` | `None` | 显式提供对应比例；自吸收时为总和 100 的原子数百分比 |
| `resolution` | `1000` | 无量纲仪器分辨率 R |
| `low_w`、`upper_w` | `200`、`1000` | 波长范围，nm，需为正且下界小于上界 |
| `max_ion_charge` | `3` | 最大发射电荷态，0 对应 I，1 对应 II |
| `webscraping` | `"static"` | `"static"` 或 `"dynamic"` |
| `self_absorption` | `False` | 静态逐线自吸收入口开关 |
| `stark_broadening` | `None` | 静态 Stark 开关；`None` 时随自吸收开关，显式 `True` 可独立启用 |
| `instrument_broadening` | `None` | 静态仪器高斯开关；显式值优先于旧配置中的同名字段 |
| `self_absorption_config` | `None` | Stark/自吸收共用的第 4.1 节配置；无 Stark 时忽略 |
| `headless` | `True` | 动态模式请求无界面运行 Chrome |
| `keep_browser_open` | `False` | 动态取数后是否保留浏览器会话，便于调试 |
| `detach_browser` | `False` | 动态模式的 Chrome 脱离驱动选项 |
| `optical_depth` | `None` | 保留的旧参数；当前开启自吸收时传手动光学厚度会报错 |

`max_ion_charge` 控制请求的发射谱线范围。当前 NIST 自吸收模型计算布居时仍使用页面提供的全部电离阶段。

## 7. 采样、结果与导出

### 7.1 两处 resolution 的含义

```python
# 继续使用第 2 节的 libs 对象。
# 初始化中的 resolution=3000 是仪器 R。
libs.interpolate(resolution=0.01)  # 此处是输出采样步长，单位 nm
resampled = libs.get_interpolated_spectrum()
```

| 位置 | 控制内容 |
| --- | --- |
| `SimulatedLIBS(resolution=3000)` | 线形中的仪器分辨率 |
| `libs.interpolate(resolution=0.01)` | 新输出网格的采样间隔 |
| `self_absorption_config["wavelength_step_nm"]` | Stark/自吸收入口初次输出的采样间隔 |

静态初始普通谱的期望步长为 `0.005 nm`。网格包含两端点，点数为 `max(2, round((upper_w-low_w)/step)+1)`，由 `linspace` 生成，实际间隔可能略有调整。

静态重采样复用已获取的谱线并重新计算线形或离散投影，无须再次联网。Stark 分支同时更新 `raw_spectrum`、`interpolated_spectrum` 及参考谱；未使用 Stark 的静态分支仅更新 `interpolated_spectrum`。动态数据显式调用 `interpolate()` 时沿用三次样条。

### 7.2 可以检查哪些结果

| 属性或方法 | 内容 | 可用路径 |
| --- | --- | --- |
| `get_interpolated_spectrum()` | 当前输出网格上的总谱 | 所有模式 |
| `get_raw_spectrum()` | 原始/最近一次 Stark 渲染的总谱 | 所有模式 |
| `line_table` | 合并后的 NIST 计算谱线表 | 静态模式 |
| `get_ion_spectra()` | 各离子分量，含 `Wavelength (nm)` 和 `Sum(calc)` | 动态或静态 Stark |
| `unabsorbed_interpolated_spectrum` | 同一 Stark/仪器模型的薄谱参考 | 静态 Stark/自吸收 |
| `unabsorbed_raw_spectrum`、`unabsorbed_ion_spectra` | 未吸收总谱及离子分量 | 静态 Stark/自吸收 |
| `self_absorption_diagnostics` | 原始面积、W、出处、tau、SA、前后面积/宽度/内禀峰高；仅 Stark 时 tau=0、SA=1 | 静态 Stark/自吸收 |
| `self_absorption_metadata` | 实际开关、模型、网格和假设；仅自吸收时包含重新计算的布居与密度 | 静态 Stark/自吸收 |

未使用 Stark 的静态路径只生成总谱，调用 `get_ion_spectra()` 会报错。Stark 薄谱与纯高斯谱存在差别。诊断表中的 `thin_peak`、`absorbed_peak` 是仪器响应前的内禀峰高。

`save_to_csv(path)` 保存当前 `interpolated_spectrum`；父目录需要事先创建。单独导出其他表时，使用相应 `DataFrame.to_csv(..., index=False)`。

## 8. 动态浏览器模拟

动态模式由 Chrome 打开 NIST 页面，填写分辨率、点击重新计算，再读取导出的 CSV：

```python
from simLIBS import SimulatedLIBS

libs_dynamic = SimulatedLIBS(
    Te=1.0,
    Ne=1e17,
    elements=["Mg"],
    percentages=[100.0],
    low_w=280.0,
    upper_w=290.0,
    resolution=3000,
    max_ion_charge=2,
    webscraping="dynamic",
    headless=True,
    keep_browser_open=False,
    detach_browser=False,
)

dynamic_spectrum = libs_dynamic.get_interpolated_spectrum()
ion_spectrum = libs_dynamic.get_ion_spectra()
```

排查页面或导出问题时，可设置 `headless=False`、`keep_browser_open=True` 观察页面。动态模式忽略本地展宽及自吸收配置，相关实例开关均记录为 `False`，表示本地引擎未执行。

## 9. 批量生成数据集

输入组成表中，元素为列名，**最后一列必须为 `name`**，每行为一组组成。主类从表中随机抽样，并随机选择指定范围的 `Te` 和 `Ne`：

```python
from pathlib import Path

import pandas as pd
from simLIBS import SimulatedLIBS

composition = pd.DataFrame({
    "Mg": [100.0, 50.0],
    "Ca": [0.0, 50.0],
    "name": ["Mg_sample", "Mg_Ca_sample"],
})

dataset = SimulatedLIBS.create_dataset(
    input_composition_df=composition,
    size=1,                       # 初次调试先生成一个样本
    Te_min=0.9,
    Te_max=1.1,
    Ne_min=8e16,
    Ne_max=1.2e17,
    webscraping="static",
    self_absorption=False,
)

dataset_dir = Path("output/dataset")
dataset_dir.mkdir(parents=True, exist_ok=True)
dataset.to_csv(dataset_dir / "samples.csv", index=False)
```

输出为一行一个样本的宽表，前面是以波长命名的强度列，后面是元素比例、`name`、`Te[eV]`、`Ne[cm^-3]`。

当前批量接口没有暴露波段、仪器分辨率和最大发射电荷态参数，内部使用主类默认值，即 `200–1000 nm`、`R=1000`、`max_ion_charge=3`。它会转发 `stark_broadening`、`instrument_broadening`、自吸收开关与配置；启用 Stark 时，各随机样本在默认波段内同样需要完整的逐线系数。样本并发数随 `size` 增加，建议先用小批量确认调用和数据覆盖。

## 10. 数据来源迁移说明

2026-10-28 起，本项目删除内置 Stark 系数 JSON、独立离线论文模型及其运行示例。配置不再接受 `stark_source`、`stark_data`、`data_path`；示例也不再提供 `--stark-source` 和 `--stark-csv`，传入旧选项会明确报错。

数据库响应缓存继续用于避免重复下载，它保存真实原始响应和来源信息，仍走相同的解析、量子态匹配与适用条件检查。`stark_allow_network=False` 和 `--offline-stark` 仅限制数据库请求，不是本地系数模拟模式；没有对应缓存时会报错。

已有 `saved/` 和 `docs/self_absorption_results/` 输出保留为历史结果，不参与后续模拟。尤其旧匹配清单可能含 `paper coefficient table` 来源，不能视为当前数据库路径的覆盖统计，需重新运行才能取得新结果。

- [当前 NIST 示例](examples/nist_self_absorption_demo.py)
- [数据库覆盖与精度边界](STARK_DATA_COVERAGE.md)
- [自吸收历史报告](SELF_ABSORPTION_REPORT.md)：保留旧原理与结果记录，旧 API 已移除。

## 11. 模块职责与调试顺序

| 文件 | 职责 | 适合检查的内容 |
| --- | --- | --- |
| [simLIBS/__init__.py](simLIBS/__init__.py) | 对外导入入口 | 导出的主类、配置和异常 |
| [simLIBS/simulation.py](simLIBS/simulation.py) | 组织取数、模型调用、缓存、重采样与导出 | `site`、`response`、`line_table`、`_absorption_lines`、结果回写 |
| [simLIBS/nist_lines.py](simLIBS/nist_lines.py) | 计算谱线解析、网格划分、仪器高斯/无展宽离散投影 | `parse_sticks()`、`render_sticks()` |
| [simLIBS/nist_self_absorption.py](simLIBS/nist_self_absorption.py) | 当前 NIST Stark/逐线自吸收模型 | `resolve_stark()`、`prepare_nist_absorption()`、`render_nist_absorption()` |
| [simLIBS/nist_stark.py](simLIBS/nist_stark.py) | NIST 身份补全和跨库量子态匹配 | `identify()`、`same_state()`、`match_width()`、`resolve_online()` |
| [simLIBS/stark_b.py](simLIBS/stark_b.py) | STARK-B 取表、缓存、宽度换算与适用条件 | `species()`、`parse_table()`、`evaluate_width()` |
| [simLIBS/self_absorption.py](simLIBS/self_absorption.py) | 共享数值工具与结果容器 | `slab_attenuation_factor()`、`SpectrumResult` |

静态自吸收适合按以下顺序下断点：

```text
SimulatedLIBS.__init__
  -> retrieve_data_static           检查 NIST 请求和 HTML
     -> parse_sticks               检查计算谱线/线强
     -> parse_atomic_payload       检查跃迁；仅自吸收时需要完整能级和电离能
  -> prepare_nist_absorption
     -> attach_nist_strengths      检查同波长跃迁的面积分配
     -> nist_populations           仅自吸收时计算配分函数和电离比例
     -> resolve_stark              检查系数匹配、缺失和歧义
        -> resolve_online          为全部跃迁补全 NIST 态身份并查 STARK-B
           -> species/parse_table  检查快照、电子宽度表和拟合
           -> match_width          检查组态/项/J、Te/Ne 和来源优先序
  -> _render_paper_model
     -> render_nist_absorption     检查 width、q、tau、SA 和 Voigt 叠加
  -> get_interpolated_spectrum      读取当前结果
```

常见情况：

| 现象 | 检查方式 |
| --- | --- |
| `MissingStarkDataError` | 导出 `error.missing_lines`，核对每条跃迁及其系数来源 |
| `StarkDataAccessError` | 检查网络、缓存路径或快照校验；不要按“物理缺系数”处理 |
| `self_absorption requires Stark broadening` | 开启自吸收时保留 Stark；如只需展宽，设置 `self_absorption=False`、`stark_broadening=True` |
| `Ambiguous STARK-B sources` | 核对数据库数据集、量子态及原始文献；可用 `stark_methods` 限定明确的方法 |
| 找不到 `dataSticksArray` 或原子数组 | 查看 `response.text`，确认返回的是 NIST 数据页；静态请求最多尝试 3 次 |
| 把 `resolution=0.01` 传给初始化后线宽异常 | 初始化需要仪器 R；`0.01 nm` 步长应传给 `interpolate()` 或自吸收配置 |
| 关闭自吸收后两张谱仍有差别 | 同时核对 Stark、仪器高斯、R 和网格；纯高斯与 Stark 薄谱使用不同线形 |
| 提示网格或计算规模超限 | 缩小波段或增大采样步长；初次自吸收步长应在配置中指定 |
| 中文注释已修改但调试未进入对应文件 | 用 `inspect.getfile(SimulatedLIBS)` 检查当前解释器导入的源码位置 |

静态网格最多支持 2,000,000 点；自吸收还限制“谱线数 × 网格点数”等计算规模。有限采样与输出窗口会影响数值积分捕获的面积，核对线面积时应使用足够细的网格与足够宽的波段。

现有离线测试可从项目目录运行，无须真实访问 NIST 或启动 Chrome：

```powershell
python -m unittest discover -s tests -v
```

## 12. 项目来源与许可

原项目由 **Marcin Kastek** 创建，服务于利用 LIBS 光谱识别元素的本科毕业研究。导师为 **Paweł Gąsior**，单位为 Institute of Plasma Physics and Laser Microfusion（IPPLM）。原项目地址：[MKastek/simLIBS](https://github.com/MKastek/simLIBS)。

本目录在原项目上增加了本地静态谱线合成、逐线自吸收、诊断结果和对应测试。许可见 [LICENSE.md](LICENSE.md)。

相关文献：

- M. Kastek 等，*Analysis of hydrogen isotopes retention in thermonuclear reactors with LIBS supported by machine learning*，Spectrochimica Acta Part B 199，106576。[DOI: 10.1016/j.sab.2022.106576](https://doi.org/10.1016/j.sab.2022.106576)。
- L. M. John、K. K. Anoop，*A numerical procedure for understanding the self-absorption effects in laser induced breakdown spectroscopy*，RSC Advances，2023，13，29613–29624。[DOI: 10.1039/D3RA06226K](https://doi.org/10.1039/D3RA06226K)。当前逐线自吸收使用其中的线中心衰减与经验宽度关系。
- Chen 等，*Line intensity calculation of laser-induced breakdown spectroscopy during plasma expansion in nonlocal thermodynamic equilibrium*，Optics Letters，2023，48(12)，3227–3230。[DOI: 10.1364/OL.488250](https://doi.org/10.1364/OL.488250)。原项目 README 将其列为相关研究。
