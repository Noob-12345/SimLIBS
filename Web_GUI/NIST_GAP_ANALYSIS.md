# simLIBS Web UI 与 NIST 官方 LIBS 功能差距分析

> 2026-10-02。对比对象：本 Web UI（`web/`，已接入真实引擎）与 NIST ASD LIBS 官方接口
> （`physics.nist.gov/cgi-bin/ASD/ie.pl` + 浏览器端 `saha_lte.js`）。
> 结论先行：**任务编排上 Web UI 已远超官方**（批量、扫描、追溯、导出），差距集中在
> **物理参数保真度**和**谱线级交互**，其中第 1 条与 `Cross_attention/Dataset` 的诊断直接对应。

## 一、物理 / 数据保真差距（按优先级）

### P0 实际 R 检测与警告（约 0.5 小时）

- **差距**：NIST 会静默降低实际分辨本领（实测 200–700nm 请求 R=3000，实际 R=83），
  官方页面会显示实际 R 与警告；Web UI 目前完全信任请求值。
- **做法**：在 `simlibs_ui/adapter.py`（UI 侧文件，可改）缓存 bounded_get 的响应文本，
  解析其中的 `var resolution`，与请求 R 不符时：任务日志警告 + manifest `origin` 增加
  `actual_resolution` 字段 + 前端来源徽章显示"实际 R=xxx"。
- **验收**：用 200–700nm/R3000 跑一次，日志与 manifest 中出现 actual_resolution=83 左右。

### P1 线表模式：`dataSticksArray` + 本地统一展宽（1–2 天，核心）

- **差距**：官方的本质能力是给出 Saha–Boltzmann 计算的**未展宽线表**；Web UI 目前只有
  服务端按"实际 R"展宽后的 `dataDopplerArray`，宽波段必然失真且各样本不一致。
- **做法**：请求 `min_rel_int=0`，解析 `dataSticksArray`（A_i = 各离子列之和），
  按核心波段合并线表后，在统一网格上本地展宽一次。**直接复用已验证实现**：
  `D:\LIBS\Deeplearning\Cross_attention\Dataset\nist_reconstruction.py`
  （`parse_nist_matrix / merge_core_sticks / render_nist_sticks`，含单元测试），
  建议复制进 `simlibs_ui/` 并保留出处注释。
- **UI 呈现**：共同参数增加"生成方式"开关：服务端谱（现状）/ 线表本地展宽（推荐用于
  训练数据）；manifest `origin` 增加 `reconstruction` 字段（算法、R、网格、线表行数）。
- **验收**（对照 NIST_ASD_DIAGNOSIS.md 的指标）：
  - 分段线表合并 vs 整段线表：逐点完全一致（阈值为 0 时 11,940 行）；
  - 与官方 saha_lte.js 同 R 同舍入：corr ≥ 0.9999999；
  - 展宽后峰面积守恒、分辨率-峰高关系通过既有 5 项单元测试。

### P2 本地 Recalculate 交互（依赖 P1，分两档）

- **差距**：官方页改 Te/Ne/R 浏览器内立即重算（`saha_lte.js`），不发请求；
  Web UI 每改一次参数都要提交真实任务。
- **做法分两档，工作量差异大，不要混为一谈**：
  - **R / 网格即时重算（约 0.5 天）**：线表缓存后本地改 R 展宽即可，前端秒级响应；
  - **Te / Ne 即时重算（1 天以上）**：线表强度依赖 Te/Ne，需重跑 Saha–Boltzmann。
    可复用 `verify_nist_browser.cjs` 的思路：把官方 `saha_lte.js` 数值函数放进前端
    隔离执行（官方响应中携带所需数据）。
- **验收**：缓存线表后拖动 R 滑杆 0 请求重绘；Te/Ne 档与官方网页逐点对比。

### P3 逐离子曲线（约 0.5 天，Web 相对自家 Tk 版的退步）

- **差距**：Tk 版 dynamic 有"各离子曲线及完整表"；Web 版 ion 视图目前只画 Sum(calc) 总谱。
- **做法**：`real_backend._single_result` 把 ion preview 的各离子列一并下发，前端 ion
  视图改为多系列可切换（复用现有图例 chip 机制）。
- **验收**：dynamic 任务后可单独查看/叠加每个电离态曲线，数据与 CSV 一致。

### P4 高级参数面板（约 0.5–1 天，需先核对官方表单）

- **差距**：以下官方高级选项 UI 均未暴露（源库硬编码）：
  | 参数 | 官方能力 | 现状 |
  |---|---|---|
  | `min_rel_int` | 选线相对强度阈值 | 硬编码 0.001（分段/整段选线漂移的根源之一） |
  | `int_scale` | 能量通量 / 光子通量 | 硬编码 2（光子通量） |
  | 空气/真空波长 | 波长约定切换 | 未暴露（UV <200nm 分析必须一致） |
  | 波长单位 | nm / Å | 仅 nm（次要） |
- **做法**：设置或共同参数的"高级"折叠区；实现前先抓一次 ie.pl 表单确认参数名
  （以官方 libshelp.html 为准，不要凭记忆猜参数名）。
- **验收**：改 min_rel_int=0 与 datagen 管线数据可比；int_scale 切换后强度比值合理。

## 二、小项

| 项 | 说明 | 工作量 |
|---|---|---|
| NIST URL 前端展示 | manifest 来源证据里已有 `nist_url`，前端加一个可点击 chip | 10 分钟 |
| 历史 CSV 导入对比 | worker 已支持 `history` 任务类型，只差前端入口（文件选择 + 只读视图，参数未知标注） | ~0.5 天 |
| 批量组成 CSV 上传 | worker 已支持 `compositions` 任务类型（名称列映射、`*_at%`），差前端上传 | ~0.5 天 |
| 参数进 URL | 请求参数编码进地址栏，可像 NIST 一样直接链接分享 | ~0.5 天 |

## 三、Web UI 已超越 NIST 官方的部分（无需补）

批量 dataset（官方无批量）、Te/Ne/R 扫描动画 + GIF、任务追溯
（request.json / events.jsonl / worker.log / manifest）、导出体系
（CSV/JSON/PNG/GIF/数据集）、三键图表交互、协作取消与超时治理、亮暗主题。

## 四、建议执行顺序

> **2026-10-03 更新：本节已被第六节的"数据抓取模式重塑方案"取代。**
> P0（实际 R 检测）并入重塑方案的证据链；P1（线表模式）、P2（本地重算）、P3（逐离子）
> 都是该方案的组成部分；P4 的高级参数并入展宽参数组。执行时直接按第六节实施。

```
重塑方案（第六节）≈ P0 + P1 + P2(R 档) + P3 + P4(部分) 一起落地
  → 剩余小项按需穿插
  → Te/Ne 纯本地 Saha-Boltzmann 复算（P2 的深档）作为后续独立项
```

## 五、参考资产

- 诊断与已验证方案：`D:\LIBS\Deeplearning\Cross_attention\Dataset\NIST_ASD_DIAGNOSIS.md`
- 重建实现（相关系数 1.0）：同目录 `nist_reconstruction.py` + `tests/test_nist_reconstruction.py`
- 官方 JS 对照工具：同目录 `verify_nist_browser.cjs`（隔离 VM 调用官方数值函数）、
  `audit_nist_resolution.py`（`--fetch` 获取官方快照，离线可复现）
- 官方文档：LIBS Help —— Changing the wavelength resolution / Advanced Options
  （pml.nist.gov/PhysRefData/ASD/Html/libshelp.html）
- 本 UI 接口契约：`UI/web/backend_api.py`、`UI/web/README.md`；adapter 修补点：
  `UI/simlibs_ui/adapter.py`（bounded_get 缓存响应 / retrieve_data_static 覆写）

## 六、数据抓取模式重塑方案（✅ 2026-10-03 已实施并验收）

> 验收结果（真实 NIST 联机）：
> - ① static+NIST 展宽回归：H 650–660 R1000 → 峰 656.5 @ 1802（与改造前一致），actual R=1000 已提取；
> - ② static+本地展宽：峰 656.465 @ 1801.58、FWHM 1.085nm ≈ 理论 2√ln2·λ/R=1.093；线表存档、逐离子曲线、broadening_params 完整；
> - ②b 本地展宽+本地插值：5000 点（源库上界排除语义）；
> - ③ dynamic+NIST 展宽回归：与 ① 一致（client-js）；
> - ④ dynamic+本地展宽：与 ② 数值一致（页面 dataSticksArray 确认可用）；
> - 宽波段降级警告：W/Fe/Mo 200–1000 R3000 → 实际 R=85（诊断区间内），界面徽章+日志警告。
> 交叉验证：本地展宽峰高 1801.58 vs NIST 实际 R=1000 的 Doppler 峰高 1802，几乎完全一致。

> 目标：把"谁算线强、谁做展宽、是否本地插值"三个决策变成正交、可选择的参数，
> 并把每条路径的真相写进来源证据。static/dynamic 名称保留，语义明确化。

### 6.1 新模型：三个正交维度

**维度一：计算位置（static / dynamic，语义升级）**

| 模式 | 线强（Saha–Boltzmann）谁算 | 传输 | 展宽谁做（由维度二决定） |
|---|---|---|---|
| **static** | **NIST 服务器** | requests 拉 ie.pl HTML | 服务端（DopplerArray）或本地（SticksArray） |
| **dynamic** | **客户端**（页面内 saha_lte.js / 本地化，类比 Cross_attention/Dataset 的本地处理） | Selenium | 页面 CSV（现状）或本地（页面 JS 变量里的 SticksArray） |

**维度二：展宽位置（新增开关，两种模式都有）**

- **NIST 展宽**（默认，现状行为）：static 解析 `dataDopplerArray`；dynamic 抓页面 CSV。
- **本地展宽**：两种模式都改为获取 `dataSticksArray` 未展宽线表
  （static：同一份 HTML 里解析；dynamic：Recalculate 后从页面 JS 变量读取，
  **不再需要点 ViewDataCSV**），然后本地按官方约定展宽。实现时需确认 dynamic
  页面 Recalculate 后 HTML 中确有 `dataSticksArray`（源库解析代码用它作结束标记，
  大概率存在；不确定则回退抓 CSV 的 Sticks 数据源）。

**维度三：本地插值与否（现有"主动重采样"开关保留，语义不变）**

- 关（默认）：使用数据源自身网格（Doppler 网格 / 线表合成网格=目标网格，无需插值）。
- 开：CubicSpline 重采样到指定步长网格（沿用现有 step 输入与点数上限校验）。

### 6.2 四种组合的数据流

```
① static + NIST 展宽（现状回归）：
   ie.pl HTML → dataDopplerArray → [可选本地插值] → 结果
② static + 本地展宽（= datagen 方式，推荐用于训练数据）：
   ie.pl HTML（min_rel_int=0）→ dataSticksArray → 合并核心波段
   → 本地按官方高斯约定展宽到目标网格 → [可选本地插值] → 结果
③ dynamic + NIST 展宽（现状回归）：
   Selenium → Recalculate → 页面 CSV → [可选本地插值] → 结果
④ dynamic + 本地展宽：
   Selenium → Recalculate → 读页面 dataSticksArray → 本地展宽 → [可选本地插值] → 结果
```

### 6.3 本地展宽参数（开关打开时在界面暴露）

| 参数 | 默认 | 说明 |
|---|---|---|
| 展宽 R | =请求 R | 高斯展宽用的分辨本领；请求 URL 仍需合法 resolution（服务端校验），但线表模式下结果只取决于此处 |
| 高斯约定 | 严格复刻 NIST | w=λ/R 为 1/e 半宽（FWHM=2√ln2·w）；可切换物理 FWHM 约定，但全链路必须一致 |
| 输出网格 | 起止=波长范围，步长/点数二选一 | 沿用 200k 点上限校验 |
| 线中心舍入 | 保留原始 Ritz 波长 | center_decimals 仅在严格复现网页时用（参照诊断文档） |
| min_rel_int | 本地展宽时建议 0 | 线表选线阈值；非 0 会引入随波段的选线漂移（诊断结论） |

### 6.4 改动清单

**契约层（`web/backend_api.py`）**
- `CommonParams` 增加：`broadening: 'nist' | 'local'`（默认 nist）、
  `broadening_params: {convention, grid_step|grid_points, center_decimals, min_rel_int}`（local 时校验）。
- 校验规则：本地展宽时线表解析失败 → 400/任务失败（不得静默回退到 Doppler）；点数上限按目标网格计算。

**引擎层（`simlibs_ui/adapter.py` + 新文件 `simlibs_ui/nist_recon.py`）**
- `nist_recon.py`：从 `Cross_attention/Dataset/nist_reconstruction.py` 复制
  `parse_nist_matrix / merge_core_sticks / render_nist_sticks / line_strengths`，保留出处注释与单元测试。
- `adapter.simulate()` 增加 `broadening` 分支：
  - static：`retrieve_data_static` 覆写为同时解析两种数组（响应文本已在手）；
  - dynamic：`retrieve_data_dynamic` 覆写为读页面 JS 变量（或保留 CSV 路径按开关选择）；
  - 输出 frames 语义：NIST 展宽 → raw=Doppler 网格；本地展宽 → raw=合成谱（目标网格）+ 附 `line_table.csv`；
  - **顺带解决 P3**：线表自带各离子列 → ion frames 直接可用。
- 来源证据（manifest `origin`）增加：`computation_location`（server|client-js）、
  `broadening`（nist|local）、`broadening_params`、`actual_resolution`（P0，从响应 `var resolution` 解析，
  不一致时任务日志警告）、线表行数与 SHA。

**前端（`web/static/`）**
- 抓取方式 seg 语义说明更新（static=NIST 服务器算线强 / dynamic=客户端计算）。
- 新增"展宽位置"开关（NIST 展宽 / 本地展宽）+ 本地展宽参数折叠组（按 6.3）。
- "主动重采样"开关保留（即维度三），文案微调为"本地插值"。
- 结果徽章增加：计算位置、展宽位置、实际 R；线表模式下提供"谱线清单"查看入口（顺带 P9 谱线标注）。
- 离子图例在本地展宽模式下启用（线表含各离子列）。

### 6.5 校验与边界

- 本地展宽 + 本地插值同时开启：先合成到展宽网格，再 CubicSpline 到更细步长网格（两步点数分别校验）。
- `min_rel_int≠0` 时的选线漂移在界面上给出说明（引用诊断文档结论）。
- 本地展宽路径同样受取消/超时治理（worker 协作取消不变）；展宽本身为纯本地计算，秒级完成。
- static+本地展宽完全不需要 Selenium；dynamic+本地展宽仍需浏览器触发 Recalculate。

### 6.6 验收标准（按组合）

1. ①③ 与现状结果逐点一致（回归不破坏）。
2. ② 与 `Cross_attention/Dataset` 线表重建在同一组成/Te/Ne/R/网格下**逐点相等**
   （对照 NIST_ASD_DIAGNOSIS.md：分段 vs 整段 11,940 行逐位相等；与官方 JS corr≥0.9999999）。
3. ④ 与 ② 等价（同一页面的 SticksArray）。
4. 插值开关四种组合网格与点数正确；200k 上限拒绝路径有效。
5. manifest 证据链完整：computation_location / broadening / params / actual_resolution / 线表行数。
6. 本地展宽模式下离子曲线与谱线清单可用。

### 6.7 工作量与顺序

```
契约+校验（0.5 天）→ nist_recon.py 移植+单测（0.5 天）→ adapter ②④ 路径（1 天）
  → 前端参数面板与徽章（0.5 天）→ 四组合回归验收（0.5–1 天）
合计约 3–4 天；P0 证据链随 adapter 改动顺带完成。
```

### 6.8 明确不做（后续独立项）

- Te/Ne 的纯本地 Saha–Boltzmann 复算（把 saha_lte.js 数值函数放进前端/本地）——
  线表模式下 R 可即时重算，但 Te/Ne 改变需要重算线强，留作独立增强（P2 深档）。

### 6.9 实施落点（已全部完成）

- `simlibs_ui/nist_recon.py`：移植自 Cross_attention/Dataset（Band/render_ion_sticks 为 UI 增补），单测 `tests/test_nist_recon.py` 9 项；
- `simlibs_ui/models.py`：Parameters 增加 broadening / broaden_convention / broaden_grid_step / broaden_center_decimals / broaden_min_rel_int（默认值=旧行为，随 replace() 自动流过批量/扫描）；
- `simlibs_ui/adapter.py`：响应捕获、get_site 的 min_rel_int 重写（local 时）、retrieve_data_static 本地分支（不依赖 Doppler 解析）、retrieve_data_dynamic 本地分支（读页面线表，跳过 CSV）、interpolate 本地分支、frames ion 条件、origin 证据链（computation_location/broadening/broadening_params/actual_resolution/resolution_warning/line_table）；
- `web/backend_api.py` + `web/real_backend.py`：契约字段、校验、参数映射、结果 meta、警告日志；
- 前端：抓取方式语义说明、展宽位置开关、本地展宽参数组、计算位置/展宽/实际 R 徽章。
