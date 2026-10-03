# simLIBS 本地桌面 UI

本目录为同级 `simLIBS-2.0.3` 源库的 Windows 桌面界面。使用 tkinter/ttk、Matplotlib 和真实 `SimulatedLIBS`，新模拟请求 NIST LIBS。源库文件保持只读；未增加离线物理求解器。打开历史 CSV、配置、绘图和导出可离线使用，历史数据持续显示来源路径与“参数未知”，不会作为新模拟成功结果。

## 启动

双击 `start_ui.cmd`，或在 PowerShell 中运行：

```powershell
& 'D:\LIBS\simLIBS-2.0.3\UI\start_ui.ps1'
# 若系统阻止 .ps1，使用 CMD 启动，或只为本次 PowerShell 进程指定策略：
powershell -NoProfile -ExecutionPolicy Bypass -File 'D:\LIBS\simLIBS-2.0.3\UI\start_ui.ps1'
# 也可以直接运行（任意工作目录）
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B 'D:\LIBS\simLIBS-2.0.3\UI\run_ui.py'
```

默认使用现有 `D:\Anaconda3\envs\simLIBS\python.exe`（Python 3.10）。默认 Anaconda Python 3.7 无法运行源库的 match 语法。启动脚本支持环境变量 `SIMLIBS_UI_PYTHON` 指定另一个已有的 Python 3.10+ 环境。界面“设置”中的 Python 路径用于之后的后台 worker；更改 GUI 自身解释器需重启。所需依赖：tkinter、Matplotlib、pandas、numpy、scipy、requests、beautifulsoup4、selenium、webdriver_manager、Pillow；本任务使用已有依赖，没有安装 pytest/ImageMagick。

```powershell
.\start_ui.ps1 --diagnose
.\start_ui.ps1 --smoke-test --output '.\output\smoke'
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v
```

`--diagnose` 只检查解释器、依赖和源路径，不联网、不下载驱动。`--smoke-test` 创建并显示实际 Tk 窗口，导入源库 `docs/single_simulation.csv` 历史谱，后台导出 CSV/PNG/JSON、保存窗口截图和 `smoke.json` 后自动关闭。它没有执行新模拟。

## 单次模拟与组成

左侧共同参数适用于当前工作页：Te [eV]、Ne [cm⁻³]、整数分辨率 R、波长上下界 [nm]、最大离子电荷、static/dynamic、headless 和可选重采样。

- 配比表示总原子数密度占比；合法元素符号区分大小写，如 `H`、`He`、`Fe`。元素不能重复，所有占比有限且非负，总和必须为 100%（绝对浮点容差 `1e-6`）。不把空格、NaN、负数或无穷转换为零。
- 在“单次模拟”逐行新增、选中更新或删除元素。CSV 导入用名称列映射后的第一行；完整组成也会放入批量页。只有“主动归一化”按钮才改变配比，并显示前后值。零占比可保留在配置/数据集列，实际 NIST 请求移除零项。
- 预设包含 H 100%、Te=1、Ne=1e17、650–660 nm、R=1000，以及源库 README 的 W/Fe/Mo=50/25/25、200–1000 nm。预设只填写参数，不联网。
- R 控制光谱分辨率，**不是重采样步长**。static 默认调用原始 CubicSpline、0.005 nm 网格、上界排除；主动重采样才使用输入步长。dynamic 默认保留 NIST 网格，所以 raw 与 interpolated 相同；主动重采样会再次调用原 CubicSpline。
- 右侧可选 raw、interpolated、ion，修改标题和颜色、显示归一化、缩放/平移。零谱归一化仍为零。static 不生成 ion，视图列表不会提供 ion，并显示原因；dynamic 展示各离子曲线及完整表。

当前 NIST 对只有一个离子贡献列的 CSV 可能省略 `Sum(calc)`。例如真实 H 窄波段只返回 `Wavelength (nm),H I`；适配层保留 H I 原值，把同一列复制为总谱并在 `ion_total` 来源字段明确记录。多贡献列缺总谱等不明确格式继续报错。

单谱最多 200000 点。预览最多等距抽样 1500 行，数据表按 100 行/页显示，并注明完整行数；窄尖峰可能未在抽样图中显示。完整 CSV、PNG 导出使用全量数据，不限于预览。所有数值均须 finite，Te/Ne/R/步长>0、0<下界<上界、电荷为非负整数；非法输入在启动 worker 前拒绝。

## 批量 dataset

“批量 dataset”导入 CSV、使用当前配比或编辑组成表。名称列默认 `name`，例如：

```csv
H,He,name
100,0,H-only
80,20,H-He
```

支持名称列映射（例如历史 `samples`），`*_at%` 显式映射为对应元素符号，清理历史 `Unnamed:` 索引列。每行均检查有限值、元素和总和；源库 `saved/contents.csv` 约 95% 的历史组成不能直接生成，须用户主动归一化。可新增/编辑/删除行、增加元素列、逐行归一化和校验；导入最多 5000 行，表格 100 行/页。

填写样本数、Te/Ne 范围、随机种子。采用源库 create_dataset 的语义：随机选择组成行，均匀采样 Te/Ne；在专属 worker 内顺序执行，每次调用真实适配层，避免源库按 size 启动线程。所有共同模拟参数都透传。动态批量必须主动勾选统一重采样，生成后还会检查网格一致。宽表前部是波长列，末列是各元素占比、`name`、`Te[eV]`、`Ne[cm^-3]`；最多 5000000 个光谱单元。结果可逐样本查看，“导出 CSV”在批量结果下导出全量宽表。

## Te / Ne / R 扫描与动画

选择扫描轴、起止值，以及帧数或步长。点击“预览扫描值”查看实际值与 NIST 请求数量。帧数模式均匀包含两端；步长模式包含终点，末段允许短于步长。R 各帧取整，重复值拒绝。最多 200 帧、总计 5000000 光谱单元。其他参数使用共同参数和当前配比；static/dynamic 均可。

扫描每帧独立真实模拟，不要求各帧网格相同。完成后“播放/暂停/上一帧/下一帧”只读取已保存的小型预览，不联网。完整结果目录保留各帧 raw/interpolated/ion CSV 和对应参数/来源 manifest；“导出 GIF”在后台用 Pillow 渲染所有帧，不依赖 ImageMagick，配套 JSON 记录同一帧序列。

## 导入、导出和配置

- “打开历史 CSV”接受 `wavelength,intensity`，或含 `Wavelength (nm)`、`Sum(calc)` 与离子列的 NIST CSV。空表、非有限数据或重复波长拒绝。内置历史样例读取源库 `docs/single_simulation.csv`，保留原路径和 SHA256、参数未知。
- 选择视图后“导出 CSV”导出完整 raw/interpolated/ion，表格不带索引，旁边 `.json` 保存来源。PNG 使用当前标题、颜色和显示归一化，但读取完整光谱。“来源 JSON”保存整个结果清单与参数证据。
- “完整结果目录”在所选父目录下创建新目录，复制全量结果（批量含各样本，扫描含各帧），并重定位内部 manifest 路径，便于搬运。不会覆盖已有目录。
- “保存配置/导入配置”保存共同参数、配比、批量/扫描设置和组成表、自定义运行设置；导入严格校验，不自动联网。损坏配置报具体原因，可“恢复默认”。
- 默认输出位于 UI `output/.jobs/<唯一任务 ID>`；每个任务的 `request.json`、`events.jsonl`、`worker.log`、`result/manifest.json` 可追溯。错误时保存 `error.json`（包含 traceback）。结果来源包含源文件 SHA256、真实类名、NIST URL、配置参数、实际 Ne（源库三位有效数字处理）和动态驱动版本。

## 网络、Chrome 和任务生命周期

新模拟依赖 NIST 的可用性及页面格式。默认连接/读取超时 10/30 秒、页面加载 45 秒、脚本 15 秒、static 单次总期限 60 秒、dynamic 180 秒；批量/扫描逐样本刷新期限，超时不再发下一请求。“设置”可调整期限、输出目录、源路径、Python、Chrome 与 ChromeDriver。

TLS 证书校验默认开启，覆盖源库 static 的 `verify=False`。证书错误会具体显示，不会自动关闭；若用户明确需要，可在设置中取消 TLS 校验并保留该设置的来源证据。

dynamic 显式 `--headless=new`（也可关闭 headless），使用稳定 CSS 控件 `input#resolution`/`name=resolution`、`button[name=recalc]`、`ViewDataCSV`/`onclick=viewDataCSV()`，不使用绝对 XPath。Chrome 与驱动的 major.minor.build 必须匹配；例如本机 Chrome 154 与缓存 152 不匹配。优先填写匹配驱动路径；留空则在后台由 webdriver_manager 获取对应版本，缓存只写 UI `.driver-cache`。自动下载可能受到网络、证书或 Chrome for Testing 是否提供该版本的影响；失败会报告 Chrome 版本与原因，请配置匹配驱动后重试。

慢网络、Selenium、CSV 导入/导出、PNG/GIF 和批量扫描均由专属子进程执行。Tk 主线程不联网、不 join。Windows worker 在父进程的 Job Object 所有权建立后才允许开始；取消先发送协作标记，0.8 秒宽限后清理所属树，关闭走相同路径。`keep_browser_open=False`、`detach_browser=False` 固定；禁止按名称杀其他 Chrome。失败或取消保留上一成功图谱并恢复按钮，不加载历史样例冒充成功。已完成样本可保存在带 `partial` 标记的结果目录，仅供检查，不作为完整成功数据集/GIF。

## 验证记录

离线 unittest 和真正 Tk smoke 可按上方命令复跑。真实联机复验使用 `verify_real.py`（随后交由独立 reviewer 再验收）：

```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\verify_real.py' --output '.\output\real-validation'
```

真实 NIST 结果可能随数据库更新而变化，检查非空、finite、参数/来源证据，不硬编码历史强度。实际命令、结果和动态外部限制记录在 `.ai-workflow/20261002-simlibs-ui/implementation.md`；coder 的自测不等于独立验收通过。

只复验动态可加 `--dynamic-only`，只复验静态系列可加 `--static-only`，输出目录请选择新目录。受限执行会话的 `tab crashed`/截屏失败应先在已授权 Full Access 下复核；本任务 Full Access 已成功取得真实 H 离子 CSV。最终实际 Tk 截图在 `output/smoke-final-layout/tk-smoke.png`，只按本应用 HWND 捕获；对应报告明确记录历史样例而非新模拟。最小 950×680 窗口已验证批量/导出/取消按钮可见，左侧较长表单可用滚动条浏览。
