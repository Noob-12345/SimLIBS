# simLIBS Studio（本目录）—— 原生桌面版（PySide6/Qt，真正的窗口程序）

**这是一个独立的桌面软件**：真实窗口、黑红 "Plasma Dark" 界面（还原 `../UI/design/DESIGN.md`
设计稿）、QSS 换肤、toast 通知、流光进度条、页面淡入动画、可框选缩放的光谱图表。
不使用 HTML/浏览器，也不在终端里跑 UI（终端里只打印诊断信息）。

后端与 Web 版**完全同源**：`simlibs_cli/backend.py` 包装
`../UI/web/real_backend.py`，任务跑在 `simlibs_ui.jobs.JobController` 的专属 worker
子进程中（Windows Job Object、协作取消 + 0.8s 宽限树清理、deadline 超时），结果与
来源证据写入 `../UI/output/.jobs/<task-id>/`。未改动 UI 目录与源库任何文件。

## 启动

**双击 `start_cli.cmd`** 即可打开窗口。也可以：

```bat
E:\Anaconda\envs\simLIBS\python.exe -B run_qt.py
E:\Anaconda\envs\simLIBS\python.exe -B run_qt.py --mock      :: MOCK 演示引擎（合成谱）
E:\Anaconda\envs\simLIBS\python.exe -B run_qt.py --diagnose  :: 只检查环境，不启动界面
E:\Anaconda\envs\simLIBS\python.exe -B run_qt.py --screenshot :: offscreen 渲染各页 PNG（自查）
```

依赖：现有 simLIBS 环境 + `pip install PySide6 textual`（textual 仅旧终端版需要）。
默认解释器路径失效时自动回退（本机 conda 在 `E:\Anaconda\envs\simLIBS`）。

## 功能（五个页面，F2-F6 快捷切换，Ctrl+T 换主题）

- **输入辅助**：元素输入框带自动补全（输入 `f` 弹出 `Fe`），`fe`/`hE` 等大小写在失焦时
  自动规范为 `Fe`/`He`；Te / Ne / R 支持**滑块拖动 + 数字直输双向同步**
  （Te 0.5–10 eV 线性，Ne 10¹⁴–10¹⁹ 指数，R 100–20000 对数）。
- **计算方式（v2，与 Web 版同协议）**：`本地模拟（local）`＝离线谱线库 LTE/I-II Saha
  相对光子谱（无需网络/浏览器）；`服务器计算（server）`＝NIST 页面数据 + 浏览器内
  官方 JS Recalculate（要求 R>=100，固定 NIST 展宽，禁用 Python 展宽参数）；
  `客户端计算（client）`＝HTTP 取 NIST 未展宽线表 + Python 高斯核在统一目标网格合成
  （默认步长 0.01，无需浏览器）。请求显式携带 `mode_version=2`；完整节点显示
  （无显示抽样），扫描按帧懒加载（缓存 3 帧），视图含"元素贡献"（同元素离子求和、
  按元素稳定配色）。
  **离线展宽开关**（与 Web 同默认）：local 默认**关闭**＝未展宽线谱（精确线位/权重
  竖线，R/热/额外宽度均不应用，meta 标注"未展宽 · R未应用"）；勾选后应用仪器 R、
  热 Doppler（linked/manual）与额外高斯/洛伦兹宽度。
  **强度尺度**：local 固定 Photon（相对光子）；server/client 可选
  Photon / Energy flux。

- **单次模拟**：Te/Ne/R（滑块 + 数字直输双向同步）/λ 范围/最大离子电荷、三计算路径、
  强度尺度、重采样；配比逐行增删 + 主动归一化 + 总和 100% 校验（启动前拦截）；
  两个预设（H 窄波段 / W-Fe-Mo，只填参数不联网）。
  元数据 chip：来源、点数、SHA、实际 Ne、计算位置/展宽/实际 R（含 NIST 实际 R 警告、
  未展宽标注）。
- **批量模拟**：生成方式三选（与 Web 同协议）——**固定**（组成池随机选行 + 均匀
  Te/Ne）、**随机**（Te/实际 Ne 边界 + 逐元素浓度随机开关与上下界，有界顺序分配恒
  总和 100%，种子确定可续跑；本地模式预检谱线库可用元素）、**CSV 模板**（严格按行，
  行内参数列覆盖）。组成 CSV 导入（元素列 / `*_at%` / name 列映射，可选导入时归一化）、
  用当前配比；样本数/种子 + **每包样本数**（随请求下发，1–5000）；样本结果表 +
  数据集 CSV 导出 + 训练包 ZIP；成功后可下载**实际参数/浓度 CSV** 与**可复用模板
  CSV**。服务器模式的 NIST 展宽批量须勾选统一重采样。
- **训练数据包 ZIP**：批量成功后 worker 自动按 `nist_R3000_min0` 约定打包
  （`Random_spectra[_N].csv` 强度/波长两行交替、无表头；`Random_contents[_N].csv`
  固定 28 参考元素列 + 额外元素稳定追加；`package-manifest.json` 记录哈希与来源），
  完成后"下载训练数据包 ZIP"启用；失败/取消不提供完整训练包。
- **扫描动画**：Te / Ne(10^x) / R 轴 + 起止 + 帧数；⏮ ▶/⏸ ⏭ 自动播放（0.45s/帧）；
  导出当前帧 PNG / 整段 GIF。
- **任务记录**：任务表（状态/进度/耗时）+ 点击查看事件日志；查看结果载入对应页面；
  **离线打开历史 CSV**（`wavelength,intensity` 或 NIST 格式，SHA256 记录，参数未知标注）。
- **设置**：超时/期限/输出目录/源库/解释器/Chrome/ChromeDriver/TLS 校验，
  保存到 `CLI/.cli-settings.json`；TLS 校验默认开启。

## 图表交互（SpectrumChart，matplotlib 嵌入）

| 操作 | 效果 |
|---|---|
| 左键拖动 | 框选放大（x/y 同时） |
| 中键拖动 或 Shift+左键拖动 | 平移 |
| 滚轮 | 以光标为中心缩放 x |
| 右键单击 | 复位 |

大数据按保峰抽样（复用 `UI/web/sampling.sample_indices`，预算 6000 点，窄尖峰不丢）。
运行前显示明确标注的"示意预览"；取消/失败保留上一次成功图谱，不冒充成功。

## 界面还原设计稿的要点

- Plasma Dark：`#0a0b0e` 底 + `#131418` 卡片 + `#ef4444→#f97316` 渐变主按钮；
  Light 变体为青色 `#0891b2` 方案；
- 主按钮/进度条走红→橙渐变（"等离子体热辐射"意象），进度条运行时有流光动画；
- 数值/日志/坐标用 Consolas 等宽字体；chip 徽章、toast 右下滑入、页面淡入 220ms；
- Windows 暗色标题栏（DWMWA_USE_IMMERSIVE_DARK_MODE）。

## 测试与验证

```powershell
# Qt 离线单测（6 项：导航/主题、配比拦截、mock 单次端到端、扫描播放、批量、导出）
& 'E:\Anaconda\envs\simLIBS\python.exe' -B -m unittest tests.test_qt_app -v
# 真实引擎联机冒烟（Qt 窗口走真实路径：按钮 → worker → NIST → manifest → 图表 → 导出）
& 'E:\Anaconda\envs\simLIBS\python.exe' -B verify_real.py
& 'E:\Anaconda\envs\simLIBS\python.exe' -B verify_real.py --wfe-mo   # 宽波段用例
```

`verify_real.py` 产出 `output/real-validation-qt/`：`verify-real.json` 逐项检查 +
exports（CSV/manifest/PNG）+ `snapshots/`（真实数据页面 PNG）。
NIST 间歇性 TLS 失败（本机到 physics.nist.gov 的 SSL EOF）时脚本自动重试。

## 目录结构

```
CLI/
├─ start_cli.cmd        双击启动（崩溃时窗口保持打开并显示错误 + last-crash.log）
├─ run_qt.py            桌面版入口（--mock / --diagnose / --screenshot）
├─ simlibs_qt/          Qt 应用：theme_qt(QSS) / chart / widgets / app
├─ simlibs_cli/         共享后端接入层（backend）+ 历史CSV/打包（history/packing）+ 旧终端版（遗留）
├─ tests/               test_qt_app.py（Qt）+ 旧终端版测试
├─ verify_real.py       真实引擎联机冒烟
└─ output/              截图与验证产物（.gitignore）
```

## 已知边界

- 新模拟依赖 NIST 可用性；本机网络对 physics.nist.gov 存在间歇性 TLS 干扰，
  失败会在界面 toast + 任务日志中如实显示，重试即可。
- `simlibs_cli/`（终端版）保留为遗留实现，入口与文档均指向桌面版 `run_qt.py`。
