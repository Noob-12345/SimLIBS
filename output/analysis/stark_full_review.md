# STARK-B 全库采集与模拟接入独立 review

## C1/C2 返工后最终复审：PASS（2026-11-05，北京时间）

**本任务最终结论：PASS。采集器、冻结 JSON 和核心 simLIBS 优先级实现均在约定范围内通过独立复审；C1、C2 已关闭。** 本节为最新结论，覆盖下方返工前 REWORK；历史发现和证据保留。Vue 为用户确认的外部并行任务，未复审、未覆盖、不评定其完成状态。

本轮严格限定于 C1/C2 修复及三项新增测试，未重新采集、未重跑全库数据验证、未扩展到 Vue。review 没有修改业务源码。解释器仍为 `E:/Anaconda/envs/simLIBS/python.exe`。

### C1 关闭：STARK-B 命中不再依赖无关后备模型

核心 `stark_resolver.py` 将 `models.json` 延迟至 q=2/3 且数据库未命中的谱线再读取。已有完整量子态身份时，数据库匹配前不读取后备 atomic 文件；数值身份需要原子数据补充的原有路径保留。

独立复验原问题：在临时目录写入损坏的 `models.json`，原来受阻的官方 Si II 表现在成功返回 **STARK-B**。新增回归进一步覆盖 q=1 与 q=2 的完整态身份，models 与物种 atomic 文件均损坏仍能命中 STARK-B，并断言后备模型加载函数未被调用。

### C2 关闭：身份访问故障保持异常分类，可靠替代成功保留故障证据

核心保留捕获的身份访问异常对象；相关谱线最终未获可靠宽度时重新抛出原 `StarkDataAccessError`，不会由 `missing_stark='error'` 或 `'unbroadened'` 转成物理缺失。

独立复验原问题：对两种 missing 策略分别注入身份 TLS/缓存故障，两者均抛出同一个原异常对象，保留 `code='stark_cache_corrupt'`。新增测试同时覆盖 `stark_network` 和 `stark_cache_corrupt`；另一个新增测试验证完整显式原子输入可成功计算 DK1980，并在 `stark_access_failures` 保留原故障分类与消息。该显式模型为测试用合成原子输入，不作为真实谱线数值证据。

### 定向测试和最终版本

独立执行命令（工作目录 `simLIBS-2.0.3`）：

```powershell
& 'E:/Anaconda/envs/simLIBS/python.exe' -m unittest discover -s tests -p test_stark_resolver.py -v
```

结果：**15 项全部通过**，其中 3 项为本轮新增回归；随后再用审查前原始复现操作独立核验 C1 与 C2，两项均已修复。本轮没有新增未关闭发现。

| 本轮文件（相对 simLIBS-2.0.3） | 大小（字节） | SHA-256 |
| --- | --- | --- |
| simLIBS/stark_resolver.py | 17853 | `5e556ee1091bc79717225f37c8f22c3b79576af268eb8d2f2336139d54fa8a01` |
| tests/test_stark_resolver.py | 14266 | `345e5f8b37fde412a0761959bea46fa47cd95a5ee1d5b12ee9aea3c3900d22b0` |
| docs/STARK_DATABASE.md | 4780 | `452026aa556783d0ddf5cc2e12a467ed51fdafa3bbfca2fba8d317af885560b1` |

文档追加的 q=0–12、1000–6000000 K、1e10–1e24 cm^-3、21 个非正原值，以及原子阶段 162 ready / Co III、Mn III 输入缺失的说明，与既有核对证据一致；明确区分原子阶段不完整和 STARK-B 下载完整性。已更新其摘要，无需重验冻结数据。

冻结数据继续沿用上一轮已通过的产物：30,604,896 字节，SHA-256 `0b52574f83a99104be78afd12ec823c28991a10d37fd601ee4b9d37b4af42540`；60 元素、172 物种、5329 条来源身份谱线、11819 表、66851 点。原始 172 payload 无损还原、Pb selector / 方法保留、实际加载及 Si 主入口 / Al III 回退证据均沿用下方独立验证。

本 PASS 对应以上实际字节版本和已约定的采集＋核心范围，不包含桌面构建、发布、GUI 或 Vue 外部并行任务。

---

## 返工前复审记录（2026-11-05，C1/C2 现已关闭）

**采集器与最终 JSON：PASS。核心 simLIBS 模拟：REWORK，存在下述两项已独立复现的问题。** Vue 属用户确认的外部并行任务，本次不评定其完成状态，不以其改动作为本任务返工原因，不覆盖其业务。

本节为返工前历史结论，当前结论以上方“C1/C2 返工后最终复审”为准。下方首轮记录也保留为历史审查证据。review 未修改业务实现；获用户授权仅新增 `tests/test_stark_export_runtime.py`，以及维护审查文档和证据。

### 返工前核心发现（已在最终版本关闭）

**C1 / P1：低优先级 DK1980 模型文件提前加载，会阻断可用的 STARK-B 命中。**

- 位置：`simLIBS-2.0.3/simLIBS/stark_resolver.py:202` 至 `load_model_inputs`，发生在数据库表匹配之前；同文件 `:229` 起也在匹配前读取物种 atomic 文件。
- 独立复现：使用现有官方 Si II 表和已确定完整态身份，正常解析层级为 STARK-B；仅在临时 atomic 目录加入损坏的 `models.json`，同一谱线变为 `StarkDataAccessError: Invalid atomic models ...`，没有机会使用本可命中的 STARK-B。
- 影响：无关的后备模型损坏可中断数据库已覆盖的模拟。该行为不满足 STARK-B 优先命中后无需进入后备模型的短路要求；q=1 本不适用 DK1980，也受影响。
- 建议：先完成 STARK-B 可独立确认的匹配，只对未决谱线按需加载后备模型。确需 atomic 文件补充数值/量子态身份的情况可按需要读取，但不应预先加载无关全模型文件。增加“STARK-B 命中且不读取 DK1980 模型”的回归。

**C2 / P1：离线 JSON 路径吞掉身份数据访问异常，误转为物理缺失。**

- 位置：`simLIBS-2.0.3/simLIBS/stark_resolver.py:243` 至 `:247` 捕获 `transition_identities` 的 `StarkDataAccessError` 只保存文字；`:267` 至 `:278` 将其并入缺失原因。末尾 `:292` 的重新抛出仅覆盖另一条在线路径的 `access_error`。
- 独立复现：提供有效 Si II 数据库表和仅含 NIST 数值身份的谱线，令身份读取抛出模拟 TLS/缓存故障。`missing_stark='error'` 返回 `MissingStarkDataError`，而非访问异常；`missing_stark='unbroadened'` 成功返回 `stark_missing=True`。
- 影响：官网传输、身份缓存损坏等访问故障被当成“数据库/公式没有宽度”，允许继续生成缺展宽谱。与直接损坏数据库会报访问异常的行为不一致。
- 建议：保留异常对象与访问故障分类；无经过验证的替代来源完成该谱线时继续抛出访问异常，不能仅由 missing 策略吞掉。若可靠替代来源成功，应保留明确降级证据。增加两种 missing 策略下的身份访问故障回归。

上述 C1/C2 在最终只审 core 的复核中再次实际复现，核心 resolver SHA-256 仍为 `2aa1f44f824462c5287faea1ff073415366a9cb26a7b78799985e16a8cfdcc09`。因此不以正常数据成功探针或既有测试通过替代这两项故障处理验收。问题交原 code 修复，review 不修改业务。

### 采集与数据修复复验：通过

最终文件：`simLIBS-2.0.3/stark-b/stark_broadening.json`。

| 检查项 | 独立复核结果 |
| --- | --- |
| 文件大小 | 30,604,896 字节 |
| SHA-256 | `0b52574f83a99104be78afd12ec823c28991a10d37fd601ee4b9d37b4af42540` |
| 完整性 | `complete=true`、`scope=all` |
| 数量 | 60 元素、172 物种、5329 条含来源身份谱线、11819 表、66851 点 |
| 实际核心加载器 | `load_database` 接受，返回 11819 表 |
| 原始来源归档 | 全部 172 个 gzip+base64 payload 严格解码、解压、摘要验证，并与分物种缓存原 payload 序列化字节逐一比较；0 错误 |
| 来源格式 | 171 个 VAMDC XSAMS 物种、1 个官方 HTML 物种 |
| Pb IV | 6 页、133 表、798 点，全部页保留 transition/temperature 原始 selector，解析时集合检查通过 |
| Pb 方法标签 | 118/129/130 的标准 `method` 均为 SCP；129/130 的 Cowan/电离势说明完整保留在 `method_label`，原 payload 标签未改写 |

首轮 R1 已关闭：导出与核心加载器均使用不带结尾换行的紧凑、排序 UTF-8 rows JSON 摘要，实际 export→runtime roundtrip 通过，篡改 rows 会拒绝。

首轮 R2 已关闭（本轮已交付页完整性范围）：HTML 每页拒绝空表，fetch 保存原始 transition/temperature selector，逐页核对跃迁集合及每线温度集合；仅规范 selector 的空白，不删组态、项或 J 身份。最终 Pb 六页均已包含证据并重导出。

首轮 R3 已关闭：HTML 校验有限正波长、有限正温度与温度唯一性，异常样本测试通过。官方 source width 的零/负值仍原样保留且带不可用标记；此前所有已核查非正点均被求值器拒绝。

Pb 方法补充修复通过：只根据官方显式 method 标签提取 SCP/MSE，不从文献推断；完整原方法说明仍可追溯。VAMDC 未导出的方法继续为 unreported。电子宽度仍为 FWHM Å，运行时转 nm/HWHM 各一次；没有发现本次采集改动重复密度缩放或乘二。

### 核心正常路径与测试证据

- 本次独立定向测试：采集 25、VAMDC 23、HTML 4、导出/运行时回归 2、核心 resolver 12，共 **66 项通过**。不是引用主代理自测的 84 项数字，也未重跑全量历史测试。
- 真实 Si 主入口已独立执行：`SimulatedLIBS(Te=1 eV, Ne=1e17, Si, 634.88–634.90 nm, stark_broadening=True)`，使用捕获官方 NIST 响应及已保存身份 fixture，全程禁止额外 requests；输出 1 条诊断线，层级 STARK-B，W=`0.09262319354201339 nm`。本次默认步长为 0.005 nm，输出 5 个采样点；主代理 21 点证据对应其采样设置，不作为差异缺陷。
- Al III 69.58289 nm、Ne=1e15 cm^-3，在禁止 requests 时独立复现：50000 K 使用 STARK-B，W=`3.2646442911426445e-6 nm`；1000 K 数据库表外后使用 DK1980，W=`3.281572671287962e-5 nm`。
- 已有核心 resolver 测试覆盖 q=2/3 模型限制、真实 NIST 原子输入构造、显式模型精确数值身份、两层缺失策略、零/负宽度拒用、温度/密度边界、坏 rows 摘要和文件版本缓存失效。C1/C2 为这些通过用例尚未覆盖的异常路径。
- Vue 类型检查此前实际通过；按最新范围不将 Vue 代码、外部新 cascade、打包或 GUI 状态纳入本任务最终结论。

### 本轮关键源码摘要与边界

| 文件（相对 simLIBS-2.0.3） | SHA-256 |
| --- | --- |
| stark_data_collect.py | c6b51d00509c3aa79d3a230387a9b3d0eb15b2122136229fb3dc905da8d8de3a |
| stark_html_collect.py | db285a051e0ab3047f0eecfa42e9308d6091aba8b93e911954eded8944821710 |
| simLIBS/stark_resolver.py | 2aa1f44f824462c5287faea1ff073415366a9cb26a7b78799985e16a8cfdcc09 |
| simLIBS/nist_stark.py | 59b0953b5f591907bba047144a8b2c23538f5c3cf625dab6c9bb87cec6d7e410 |
| simLIBS/stark_atomic_data.py | 037087b11fc40b5cd527a27a44cd0eaa2d568382209850c137e5a718d0c41b1d |
| simLIBS/nist_self_absorption.py | 015a77405b07e91758b81d00f9d12d5e2fa606963868c79f72fdddc0ffd79311 |
| simLIBS/stark_vamdc.py | 0e763205ff8bedf5d90b7a6e468391c5b71f14e2eae7205e781aace179b56df1 |

全库结论限于官方发现清单暴露的 172 个物种；162 条为完整原子输入支持的比较/模型子集，不作为全库限制。本次未重新采集、不改业务、不接管或覆盖 Vue 外部并行任务。最终总体 REWORK 仅由核心 C1/C2 决定，采集与最终 JSON 可独立接收。

---

## 首轮审查历史（以下不是最终产物版本）

- 日期：2026-11-04（北京时间）
- 角色：独立 review；未修改业务源码，未重复联网，未干预采集/导出进程。
- 本轮结论：**REWORK**。采集缓存与压缩产物已完成离线核对，但存在一个阻断模拟加载的问题，以及两个 HTML 采集校验问题。最终模拟优先级实现尚未交接，本记录不构成其验收。
- 根目录：`D:/LIBS/SimLIBS`；业务目录：`simLIBS-2.0.3`。
- Python：`E:/Anaconda/envs/simLIBS/python.exe`。
- 工作区为多人并行修改；版本证据为下列文件 SHA-256 与审查脚本记录，不仅以 Git HEAD `0e48c55` 为准。

## 必须处理的发现

### R1 / P1：导出器与模拟加载器的 rows_sha256 规范不一致，最终全库无法加载

位置：

- `simLIBS-2.0.3/stark_data_collect.py:161`，`_json_bytes` 在紧凑、排序 JSON 后增加一个 LF。
- `simLIBS-2.0.3/stark_data_collect.py:832`，`rows_sha256` 使用上述含 LF 的字节。
- `simLIBS-2.0.3/simLIBS/stark_resolver.py:91`，加载器使用不含 LF 的 `json.dumps(...).encode('utf-8')`。Vue 的同步副本也应随修复核对。

影响：正常导出的 JSON 被 `load_database` 判为损坏，抛出 `StarkDataAccessError: rows_sha256 checksum mismatch`，STARK-B 首选层无法使用。

验证：离线合成采集→导出→调用真正的 `load_database` 可稳定复现；对最终 30,599,499 字节产物同样复现。最终产物的摘要按导出器算法核对正确，因此不是下载或压缩损坏。

建议：双方统一规范，并在 `docs/STARK_DATABASE.md` 写清是否包含结尾 LF。增加真正调用导出器再调用运行时加载器的跨模块回归测试；当前两边各自生成测试 JSON，未覆盖该接口。

### R2 / P1：HTML 某数据集返回空表时仍可 complete=true，缺少逐页完整性证据

位置：

- `simLIBS-2.0.3/stark_html_collect.py:43`，`parse_table` 返回空列表后直接进入空循环，没有逐页拒绝。
- `simLIBS-2.0.3/stark_html_collect.py:104`，transitions / temperatures 选择器响应被丢弃，只提交 `all`，未保存或对比预期跃迁、温度。
- `simLIBS-2.0.3/stark_data_collect.py:457`，仅用物种合并后的 rows 是否非空判断 `status='ok'`；其它页有数据就能掩盖空页。

验证：基于已保存的 Pb IV 六页官方 payload，仅清空数据集 129 的 `#shiftings tbody`，保留表头、文献、其它数据集及所有六页。

- 原始：133 表 / 798 点，数据集 118、129、130。
- 异常后：122 表 / 732 点，仅剩数据集 118、130。
- `_payload_rows` 接受；临时目录中走完整采集与导出后，manifest 和导出 JSON 均为 **complete=true**。
- 另用离线 Session 模拟整个 HTML 请求链，`fetch_species` 也返回 `status='ok'`。

影响：官方 200 响应若因会话或页面异常返回结构完整但表体为空的某页，采集成功状态与 SHA-256 不能发现遗漏。已知缺页的缓存即使可重解析，也会被复用为完整。当前真实 Pb 六页有数据，本发现不等于声称最终真实产物已发生该遗漏。

建议：至少拒绝每个已发布 dataset/density 的空结果；保存数据集/密度/跃迁/温度选择器或等价的预期清单，验证实际返回覆盖请求范围，失败显式写入 manifest。对合法发布的缺失宽度保留空值与标记，应区分“发布的缺值”与“请求页没有返回预期行”。

### R3 / P2：HTML 未校验温度/波长的正值与同温度冲突样本

位置：`simLIBS-2.0.3/stark_html_collect.py:45-60`，只验证电子密度与宽度标记；继承的 `simLIBS/stark_b.py:121-133` 会把同一跃迁重复温度直接追加。

验证：对现有 Si II 官方 HTML fixture 作独立异常注入，以下均被 `parse_payload` 接受：

- 首个温度改为 0 K 或 -5000 K。
- 所有同跃迁计算波长改为 0 Å。
- 同密度同跃迁的 5000 K 增加第二个冲突宽度 1000 Å，原值为 2.74 Å。返回 5 个样本，`evaluate_width` 直接选第一个精确温度样本，得到渲染 HWHM 0.137 nm，没有报告歧义。

影响：非正温度或波长进入导出后，运行时严格加载器可能拒绝整个库；重复温度冲突则可能在模拟时随行序静默取值。XSAMS 路径已有正温度/波长与重复温度检查，HTML 路径需要等价保护。

建议：逐 row 检查有限正波长、有限正温度，同一 dataset / transition / reference density 的温度唯一性。不能把“允许非正 source width”扩大到温度、密度、波长。增加相应离线异常测试。

## 已核对通过的内容

1. **最终缓存全量离线重解析**：172 个物种均通过 `_manifest_structure`、`_read_index`、逐个 `_read_species`，没有校验错误；11819 表、66851 点，scope=all、complete=true、无失败。读到的 manifest SHA-256 为 `aa17d1b0b73a8d1e1169cc7cc71f7d0957b4ea61df3541673d24d55a138b2661`。
2. **离子范围与温度密度**：未按 DK1980 的 q=2/3 筛选；发现范围实际包含 q=0 到 q=12。验证到的参考密度为 1e10 到 1e24 cm^-3（包括 2.8e18、3e18、3.2e18、3.5e18 等实际参考值），温度为 1000 到 6000000 K。`_MIN_NE=1e-300` 保留所有正参考密度，未按模拟目标温度过滤。
3. **宽度单位**：XSAMS 和 HTML 标准 rows 保存电子 FWHM、Å；文档描述转 nm 除 10、转渲染 HWHM 再除 2，与既有 `evaluate_width` 一致。未发现本次采集改动重复乘二。
4. **非正 source width**：本地官方 Cl q6 为 47 表 / 270 点，其中 -5.11 Å 原值保留且带 `nonpositive source electron width`。Mg q10 为 156 表 / 930 点，12 个零宽度；Ca q8 为 18 表 / 102 点，2 个零宽度。对所有这些非正点以其确切温度调用 `evaluate_width`，均抛出 `StarkBUnavailable`。其余正值保留，不因一个无效点丢弃整个离子。
5. **Pb IV HTTP400 补取**：官方 HTML payload 六页重解析为 133 表 / 798 点。dataset 118 包含 1e17、1e18、1e19、1e20 cm^-3；129、130 各含 1e17 cm^-3。页内拟合、C、文献与完整其它碰撞体列均保留在原始 HTML。
6. **坏缓存基础保护**：SHA-256、原始 payload 重解析、标准 rows 一致性、物种身份、清单覆盖/计数等既有测试通过。该结论受 R2/R3 的 HTML 校验遗漏限制。
7. **无损 gzip+base64**：方案可用；最终 JSON 的全部 172 个 raw_payloads 均逐个严格 base64 解码、gzip 解压并验证 `uncompressed_sha256`，解压字节与对应物种缓存 `payload` 的 `_json_bytes` **逐字节一致**。无损覆盖 payload 内 XSAMS/HTML，包括其它碰撞体和位移；rows 保持普通 JSON。压缩固定 `mtime=0`。
8. **.gitignore**：`stark-b/stark_broadening.json` 已明确排除忽略；`sample/models.json` 和 `sample/*_atomic.json` 也可交付。分物种缓存继续忽略，但原始 payload 已装入单文件产物，不因此丢失来源。
9. **docs/STARK_DATABASE.md**：数据规模、162 条为比较子集、单位、非正宽度、压缩说明与本轮实际结果一致；rows 摘要字节规范需按 R1 补齐。

## 最终产物离线证据

- 路径：`simLIBS-2.0.3/stark-b/stark_broadening.json`。
- 大小：30,599,499 字节（29.18 MiB）。
- 文件 SHA-256：`61b45775f1b8c61eca8e1db4025f4de5eccd6d31eb2b2e6695facde6ba8abdfb`。
- counts：60 元素、172 物种、5329 条含数据集/来源身份谱线、11819 表、66851 点。
- raw_payloads：172 个，全部解压/摘要/原始 payload 字节比较通过。
- rows_sha256：按导出器算法验证通过；模拟加载失败见 R1。
- 机器可读记录：`output/analysis/stark_final_artifact_review.json`。

## 测试与复现

已执行原有及新增的纯离线测试：

```powershell
# 工作目录 D:/LIBS/SimLIBS/simLIBS-2.0.3
& 'E:/Anaconda/envs/simLIBS/python.exe' -m unittest discover -s tests -p test_stark_data_collect.py -v
& 'E:/Anaconda/envs/simLIBS/python.exe' -m unittest discover -s tests -p test_stark_vamdc.py -v
& 'E:/Anaconda/envs/simLIBS/python.exe' -m unittest discover -s tests -p test_stark_html_collect.py -v
```

结果：25 + 23 + 2 = **50 项通过**。gzip 导出变更后已重跑 25 项采集测试。既有测试未覆盖 R1 的实际导出/消费接口，以及 R2/R3 异常。

独立审查脚本：`output/analysis/stark_review_probe.py`，仅写临时测试目录和审查证据，显式禁止 socket 网络；从工作区根目录执行。输出：`output/analysis/stark_review_evidence.json`。脚本记录具体异常注入与被审源文件 SHA-256。

## 本轮版本及复审边界

| 文件（相对 simLIBS-2.0.3） | SHA-256 |
| --- | --- |
| stark_data_collect.py | 69afdcee994d70e0410c6c0ee7189f3a5077d3cd85cf0209b5da5b46ded0457e |
| stark_html_collect.py | b2e9628c6be00c273828a823ccd2206edb02698b62f13d1f63784b41889a33c5 |
| simLIBS/stark_vamdc.py | 0e763205ff8bedf5d90b7a6e468391c5b71f14e2eae7205e781aace179b56df1 |
| tests/test_stark_data_collect.py | 4169327cc8a62c23020298667d8b4c63b9c58c2ec9f1cd03f03a731805a27f56 |
| tests/test_stark_vamdc.py | 32bfbd9751767d185f6137c4790445f177069f9bad17868b8139b7d967730ed3 |
| tests/test_stark_html_collect.py | 63c43bf2bf05f7c76bfa9bc925f26804d1f4b8814cf745cad4ef03db6ce50a6d |
| .gitignore | afb7c4bb0c13c100bbfdd680ce22b973bb051ab5aaa142adadff55e50f1c5286 |
| docs/STARK_DATABASE.md | 0d0ea4a56f721a194f1e77a6191cf4b6acaa3579efb575253b0a7904eb8786e8 |

`stark_resolver.py` 仍由 code 代理修改；R1 以已运行的加载失败证据及上述实际代码位置为准，不将进行中的 hash 当作最终冻结版本。待采集层修复和模拟实现交接后，复验 R1/R2/R3，并独立审核 STARK-B→DK1980→缺失的实际行为、Vue 副本及回归测试。

本轮没有重新向官网核对 SELECT SPECIES 与整个网站数据库是否存在接口之外的差异；“全库”结论限定为已保存官方发现清单暴露的全部 172 物种。
