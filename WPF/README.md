# simLIBS Studio —— WPF 桌面版（C# / .NET 10）

本项目是 `CLI/`（PySide6/Qt 版 simLIBS Studio）的 **WPF 重写版**：真实窗口程序、
黑红 "Plasma Dark" 界面（还原 `../UI/design/DESIGN.md` 设计稿，浅色为青色方案）、
自定义自绘光谱图表、toast 通知、页面淡入动画、深/浅主题一键切换（Ctrl+T）。

后端与 Web / Tk / Qt 版**完全同源**：`backend/wpf_bridge.py` 以 JSON-lines 子进程方式
包装 `../UI/web/real_backend.py`（或 mock 演示引擎），任务跑在
`simlibs_ui.jobs.JobController` 的专属 worker 子进程中（Windows Job Object、协作取消、
deadline 超时）。WPF 端不重复实现任何模拟/NIST/打包逻辑，未改动 UI 与源库任何文件。

## 启动

**双击 `start_wpf.cmd`** 即可（首次自动编译）。也可以手动：

```bat
:: 使用项目内置 .NET SDK（WPF\.dotnet，用户级安装，无需管理员/系统安装）
set DOTNET_ROOT=%~dp0.dotnet
.dotnet\dotnet.exe build src\SimlibsStudio\SimlibsStudio.csproj -v q -nologo
src\SimlibsStudio\bin\Debug\net10.0-windows\SimlibsStudio.exe
```

命令行开关：

```bat
SimlibsStudio.exe            :: 真实引擎（local 模式离线可用；server/client 需 NIST 网络）
SimlibsStudio.exe --mock     :: MOCK 演示引擎（合成谱，无需线库/网络）
SimlibsStudio.exe --screenshot          :: offscreen 巡回渲染各页面 PNG（含一次 mock 端到端）
SimlibsStudio.exe --screenshot --real   :: 同上，但走真实引擎（local 离线模式）
```

依赖：现有 simLIBS conda 环境（`E:\Anaconda\envs\simLIBS\python.exe`，失效时自动回退）。
.NET 侧零第三方 NuGet 包（纯 WPF + System.Text.Json）。

## 功能（五个页面，F2–F6 快捷切换）

### 外观系统（标题栏右侧三个图标）

- **主题颜色**（渐变圆点按钮）：六套预设强调色——等离子（红橙，默认）、深海青、
  星舰蓝、星云紫、翡翠、熔金琥珀。点击弹出**预览卡片**（每张卡片用该主题自己的颜色
  画出迷你谱峰 + 渐变按钮 + 滑块缩略图，非色板/文字），单击即换，全局生效
  （按钮/滑块/图表/导航/图标同步换色），选择持久化到 `.wpf-ui.json`。
- **明暗模式**（月亮/太阳按钮）：浅色 ☀ / 深色 ☾ / **跟随系统 ◐** 三选一，
  与右上角按钮合并；跟随系统读取 Windows 个性化设置并实时监听变更
  （`SystemEvents.UserPreferenceChanged`）；Ctrl+T 在浅/深之间快速切换。
- **GitHub**（octocat 图标按钮）：直达 [Noob-12345/SimLIBS](https://github.com/Noob-12345/SimLIBS)。

### 页面功能

- **单次模拟**：元素输入自动补全（`f` → `Fe`，失焦自动规范大小写）+ 逐行配比编辑、
  主动归一化、总和 100% 校验；Te / Ne(10^x) / R 滑块 + 数字直输双向同步
  （Te 0.5–10 eV 线性、Ne 指数、R 对数）；三计算路径（本地 / 服务器 / 客户端，v2 协议）、
  强度尺度、统一重采样、离线展宽开关及参数；两个预设（H 窄波段 / W-Fe-Mo，只填参数不联网）；
  元数据 chips（来源/点数/SHA/实际 Ne/计算位置/展宽/实际 R/未展宽标注/警告）；
  元素贡献叠加视图（同元素离子求和、按元素稳定配色）；导出 CSV / PNG。
- **批量模拟**：三种生成方式与 Web 同协议——组成池（支持“＋新组成”多候选块、
  组成 CSV 导入、用当前配比）、随机规则（Te/Ne 边界 + 逐元素浓度上下界，种子确定）、
  CSV 模板（模板内容随请求下发）；样本数 / 种子 / 每包样本数；样本预览表 + 宽表首尾；
  导出数据集 CSV / 训练包 ZIP / 实际参数 CSV / 模板 CSV（可用性按任务结果启用）。
- **扫描动画**：Te / Ne(10^x) / R 轴 + 起止 + 帧数；⏮ ▶/⏸ ⏭ 自动播放（0.45s/帧）+ 帧滑块；
  懒帧加载（缓存 3 帧）；导出当前帧 PNG / 整段 GIF。
- **任务记录**：任务卡（状态徽章 / 进度条 / 耗时）+ 事件日志面板；已完成任务可
  “查看结果”直达对应页面；离线打开历史 CSV（`wavelength,intensity` 或 NIST 格式，
  SHA256 记录、参数未知标注）。
- **设置**：解释器 / 源库 / Chrome / ChromeDriver / 输出目录（带浏览按钮）、
  超时与期限、TLS 校验、HTTPS 代理（针对 NIST 间歇性 TLS 干扰），
  保存到 `WPF/.wpf-settings.json`（与 Qt 版 `.cli-settings.json` 互不影响）；
  引擎状态面板（引擎 / NIST / Chrome / 线库 / 运行中任务）。

## 图表交互（SpectrumChart，纯自绘 DrawingContext）

| 操作 | 效果 |
|---|---|
| 左键拖动 | 框选缩放 |
| 中键拖动 或 Shift+左键拖动 | 平移 |
| 滚轮 | 以光标为中心缩放 |
| 右键单击 / 双击 | 复位 |
| 悬停 | 十字光标 + 最近点读数（λ / I） |

大数据按像素列 min/max 包络降采样（保峰不丢尖峰）；未展宽线谱自动切换 stick 竖线渲染；
主线双层描边产生光晕，连续谱带渐变面积填充；元素贡献按元素名哈希稳定配色。

## 目录结构

```
WPF/
├─ start_wpf.cmd            双击启动（首次自动编译）
├─ backend/wpf_bridge.py    Python 桥接进程（JSON-lines over stdio，包装 RealBackend/Mock）
├─ src/SimlibsStudio/
│  ├─ MainWindow.xaml(.cs)  外壳：自定义标题栏 + 侧边栏导航 + 页面切换动画 + toast 宿主
│  ├─ Themes/               Dark/Light.xaml（深浅底色）+ Accents/*.xaml（6 套强调色）+ Styles.xaml
│  ├─ Bridge/               BridgeHost（进程管理/事件泵）+ Models + JSON 扩展
│  ├─ Controls/             SpectrumChart（自绘图表）/ SmartSlider / ElementBox /
│  │                        Segmented / SectionHeader / Chip / ToastService
│  ├─ SinglePage 等 ×5      单次 / 批量 / 扫描 / 任务 / 设置（代码构建 UI）
│  ├─ AppState.cs           全局状态：桥接、元素表、主题、任务事件分发
│  └─ CompositionEditor / ParamsPanel   配比编辑器与共享参数面板
├─ tests/
│  ├─ test_bridge_mock.py        桥接冒烟（mock，不联网）——23 项
│  └─ test_bridge_real_local.py  真实引擎 local 离线全链路——20 项
├─ .dotnet/                 项目内 .NET 10 SDK（用户级安装；可删除，见下）
└─ output/screenshots/      --screenshot 自检产物
```

## 测试

```bat
:: Python 桥接层（覆盖协议全命令 + 校验错误路径）
E:\Anaconda\envs\simLIBS\python.exe -B tests\test_bridge_mock.py
E:\Anaconda\envs\simLIBS\python.exe -B tests\test_bridge_real_local.py

:: WPF 端到端自检（渲染各页 PNG + mock 真实谱图，产出 output/screenshots/）
src\SimlibsStudio\bin\Debug\net10.0-windows\SimlibsStudio.exe --screenshot
```

## 实现说明

- **进程模型**：`BridgeHost` 以子进程启动 `wpf_bridge.py`（stdin/stdout UTF-8 JSON 行，
  请求/响应按 id 关联，事件异步回调经 Dispatcher 派发到 UI 线程）。退出时
  `Kill(entireProcessTree: true)` 清理整棵进程树。
- **换算约定**（与 Qt/Web 版一致）：Ne 以 10^x 指数输入；批量随机规则的 ne 边界下发实际值；
  local 模式固定 photon 强度 + physics 展宽约定；server/client 固定 nist 展宽，
  server 要求 R ≥ 100 且批量必须统一重采样。
- **懒帧**：真实扫描任务按帧取全量（`get_result(job, frame)`），UI 侧 LRU 缓存 3 帧；
  mock 引擎为整包帧，两种形状都兼容。
- **显示降级**：峰谷数超显示预算时桥接层回退均匀抽样并在 meta 标注
  （与 Qt 版 `CliBackend.get_result` 同策略）。
- **.NET SDK**：`WPF/.dotnet` 是用 `dotnet-install.ps1` 装的用户级 SDK
  （约 500 MB，纯构建用途）。删除它不影响已编译产物的运行（运行需要 .NET Desktop
  Runtime 10.0，或在其他装了 SDK/Runtime 的机器上直接跑）；删除后可用系统 dotnet 重新编译。

## 已知边界

- 新模拟依赖 NIST 可用性（server/client）；本机对 physics.nist.gov 存在间歇性 TLS
  干扰，可在设置页配置代理，失败会在 toast + 任务日志中如实显示，重试即可。
- 训练包 ZIP / 数据集导出在大批量（数千样本）时可能需要数十秒，导出按钮按任务结果启用。
- 续跑（resume）依赖 checkpoint 机制，此版本保留数据但未提供续跑按钮（与协议兼容，后续可加）。
