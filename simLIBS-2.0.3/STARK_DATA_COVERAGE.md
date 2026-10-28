# Stark 数据覆盖与验证记录

更新日期：2026-10-28。适用于此目录中的 `SimulatedLIBS` 静态入口。原有联网验证记录保留；当前版本已删除内置 JSON 和本地 Stark 模型。

## 已实现的扩展

全部元素按物种请求 STARK-B，或复用已验证的数据库响应缓存，再通过 NIST ASD 补齐量子态后匹配。不接受本地 JSON、CSV 或手工系数覆盖；Mg、Ca、Zn 也使用同一数据库流程。

新增两个组件均有中文注释和函数说明：

| 文件 | 用途 | 建议断点 |
| --- | --- | --- |
| `simLIBS/stark_b.py` | 官网查询、原始响应缓存、电子 FWHM 解析、温度拟合、密度和近似适用条件 | `species()`、`parse_table()`、`evaluate_width()` |
| `simLIBS/nist_stark.py` | NIST TSV 身份补全、组态/项/J 识别、跨库匹配、缺失原因 | `identify()`、`same_state()`、`match_width()`、`resolve_online()` |
| `simLIBS/nist_self_absorption.py` | 全部系数查询 STARK-B；合成 Stark 或带自吸收的总谱 | `resolve_stark()`、`render_nist_absorption()` |

## 真实联网验证

以下均实际经过 `SimulatedLIBS`，不使用测试虚构系数。共同参数为 **Te=1 eV、Ne=1e17 cm^-3**；宽度是仪器和自吸收处理前的 Stark FWHM。该表是已验证的例子，不是允许元素列表，也不代表整元素全波段覆盖。

| 元素/电离态 | NIST 真空波长 nm | Stark FWHM nm，约值 | 数据方法 |
| --- | ---: | ---: | --- |
| Si II | 634.886 | 0.179445 | SCP |
| Fe II | 258.664928 | 0.00882906 | SCP，多重态数据 |
| Ni II | 226.5161 | 0.00648258 | SCP |
| Al I | 308.30462 | 0.04258925 | SCP，多重态数据 |
| Na I | 818.55053 | 0.38977004 | SCP，多重态数据 |
| K I | 693.81995 | 0.93822977 | SCP，多重态数据 |
| Li I | 610.522、610.533、610.535 | 0.37174947、0.37176286、0.37176530 | SCP，多重态数据 |

以上记录验证了七种元素的部分谱线。Si 的仅 Stark 和自吸收两个分支还使用真实捕获响应做了自动化集成测试。重新采样只使用已匹配的数据，不再次联网。

例如从项目目录运行：

```powershell
python examples/nist_self_absorption_demo.py --element Si --low 634.88 --high 634.90 --stark-only --cache-dir cache/stark --output output/si_stark
python examples/nist_self_absorption_demo.py --element Al --low 308.28 --high 308.33 --stark-only --cache-dir cache/stark --output output/al_stark
python examples/nist_self_absorption_demo.py --element Li --low 610.50 --high 610.55 --stark-only --cache-dir cache/stark --output output/li_stark
```

## 精度与覆盖边界

“大部分元素的任意谱线都能模拟”仍不能作为保证。数据库某个元素有记录，不等于覆盖其每个电离态、每条 NIST 跃迁或当前 Te/Ne。本次抽样之外的宽波段应实际运行并检查覆盖清单。

- 不按最近波长配对，不删除母项、项编号或显式闭壳层来强行增加命中。组态命名不能证明等价、指认不确定、J 缺失/多值等情况继续列为缺失。
- 只有来源明确按多重态给宽度时才用于相同组态和项的分量，诊断保留 `published multiplet` 标记；来源明确给出 J 时必须匹配 J。
- 温度使用真实表值或来源发布的拟合，不外推温度，不补造通用温度幂律。超过数据集最大密度时不向高密度外推。
- 电子碰撞宽度与质子/离子宽度分开，当前只接入电子碰撞部分。星号表示碰撞近似接近或超出有效范围，这类数据不自动采用。
- C 已给出时检查隔离线条件；C 未给出时 `stark_isolated_limit_cm3=None`，元数据统计未知上限条数。来源有出处不等于近似在所有密度下都有效。
- 理论方法包含 SCP 和 MSE，默认优先 SCP，再查 MSE；可以配置 `stark_methods=("SCP",)`。同等优先的多个来源会报歧义，不取平均。

用户此前样例中的 Pr、Sm、Tb、Ho、Er、Tm、Yb 在已核查的 STARK-B 元素表中未开放数据。其他数据源或文献可能另有数据；本组件不会为它们生成虚构系数。

## 怎么检查自己的组成和波段

仍用 `SimulatedLIBS(...)` 调用。只要每条实际非零贡献跃迁都匹配成功，就返回总谱及 `self_absorption_diagnostics`；其中保留来源、数据集、方法、温度范围、量子态和快照校验值。

缺失时捕获 `MissingStarkDataError`，分别导出：

```python
except MissingStarkDataError as error:
    error.missing_lines.to_csv("missing_stark.csv", index=False)
    error.matched_lines.to_csv("matched_stark.csv", index=False)
```

缺失清单中的 `stark_missing_reason` 区分无物种数据、密度超范围、NIST 身份未确认、没有对应状态、温度超范围或拟合缺失。网络和缓存错误另抛 `StarkDataAccessError`，不会伪报成“元素没有数据”。默认严格模式在缺失时中止；显式设置 `missing_stark="unbroadened"` 可保留缺失谱线的 NIST 面积，并在诊断中明确标记未施加 Stark/自吸收校正。

## 数据来源

- [STARK-B 数据定义](https://stark-b.obspm.fr/index.php/description)：电子 FWHM、波长平方换算、C/W、星号与温度拟合范围。
- [STARK-B 方法说明](https://stark-b.obspm.fr/index.php/introduction)：来源的物理方法与近似。
- [NIST ASD 能级与命名约定](https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html)：组态、母项、J 和不确定指认。
- [NIST ASD Lines 表单](https://physics.nist.gov/PhysRefData/ASD/lines_form.html)：真空波长、能量、跃迁概率与量子态导出。

具体原始论文引用保留在每条结果的 `stark_source`，引用研究结果时应同时引用对应论文和数据库。
