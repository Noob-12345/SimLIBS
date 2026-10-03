# 实现记录（第一轮返工完成，等待原 reviewer 复验）

首轮 reviewer 已完成独立验收，结论需返工；原 review.md/review-round1.md 不修改。下面首版自测记录保留为历史，本轮以文末 R1/R2/R3 返工记录为准。仍由唯一 coder 执行，不创建 agent/pane/新终端，不改源库。

## 范围与执行规则
仅增加 UI 目录文件，真实源库保持只读，使用 D:\Anaconda3\envs\simLIBS\python.exe 3.10。
遵守 coder.md、task.md、plan.md、coordinator-notes.md；唯一 coder，不启动 agent/pane。
用户明确要求持续直接实现；沿用现有规划，不额外等待批准，不创建其他 checkout。
采用 test-driven-development、executing-plans 与 planning-with-files，已读对应 SKILL.md。
执行层测试用标准 unittest，传输在离线测试中 mocked，科学构造/解析仍使用真实源库。

## 小步记录
1. 范围：models.py、包初始化、run_ui.py（3 业务文件）。先增加 5 个模型测试；实际 RED 为 5 个“参数契约尚未实现”断言失败，再实现有限数值/元素/100%/整数/网格限制和扫描端点契约。
   R 扫描四舍五入为整数，重复取整值拒绝；步长扫描包含终点，最后一段可短于步长。零占比保留配置，实际请求移除。

2. 范围：settings.py、storage.py（2 业务文件）。4 个存储测试先 RED；模型+存储 9 测试 GREEN。配置校验不联网，历史 CSV 带 path/SHA256/参数未知；数据预览限 1500 点，完整 CSV 全量保留；旧 Unnamed 索引清理，*_at% 与 samples 显式映射，95% 不自动归一化。
3. 范围：adapter.py、worker.py（2 业务文件）。7 个真实适配测试先 RED。mock fixture 首次与真实解析格式不符、mock 可见性未赋值，查源解析/Selenium 条件后修正 fixture。随后测试确实发现原 interpolate 再次改变网格时索引长度冲突，UI 子类清空目标表后继续原 CubicSpline。静态执行真实构造/HTML 解析/get_*；动态只重写控件导航，使用 CSS id/name/onclick，CSV 解析与 getter 保持原语义。动态默认 raw=interpolated 明确标注 NIST 网格；选重采样时调用原 interpolate。
   requests 进程内补 timeout 并默认 TLS 校验（覆盖源 verify=False，设置可明确关闭）；驱动在 worker 中按 Chrome 的 major.minor.build 检查，manager 定位精确版本并只写 UI/.driver-cache。成功/页面失败均由原 finally driver.quit 回收。容差内 >100 的向上浮点残差仅在提交最后一项消除，保留原请求配置与实际提交配比作为证据。

## 后续小步与修复
4. 范围：jobs.py（1 业务文件）。4 个离线后台测试先 RED，随后 GREEN；真实启动受控 worker、后代与无关进程，Tk 心跳继续，取消所属树 <5s，无关进程不受影响。Job Object 在 go 门开启前建立所有权；KILL_ON_JOB_CLOSE；事件带唯一 job_id，过期消息拒绝，无 join/future.result。deadline 由每帧/样本开始事件更新。成功才替换 last_result，失败恢复按钮。
5. 范围：operations.py、plotting.py、worker.py（3 业务文件）。6 个测试先 RED，随后 GREEN；种子可复现、采样范围、宽表列序、逐帧透传、不同扫描网格、partial、取消后无后续请求、零谱两帧 GIF 与全量 CSV/PNG。批量顺序执行而非 create_dataset(size) 个线程；保留同语义与全部公共参数。扫描不直接调用源动画的 dynamic/ImageMagick 路径，每帧真实单次调用，Pillow 输出 GIF。
6. 范围：input_views.py、result_view.py、app.py（3 业务文件）。计划 single_view/batch_view/scan_view 合并为 input_views；plotting 独立、result_view 独立；设置对话框与应用协调合并 app；减少跨 view 状态但全部契约保留。4 个 Tk 测试先 RED，随后 GREEN，涵盖三页、参数往返、非法输入不启动 worker、显式归一化、历史来源、失败恢复与播放/暂停不联网。测试在反复销毁 Tk 时出现 after callback 残留，测试 teardown 取消全部 timer；用户关闭路径单个 Tk mainloop 按轮询结束。
7. 新增资源测试 RED：static 未重采样时 points 曾使用备用 step 而非实际默认网格；修正 models.points，同时动态批量未显式重采样在启动 worker 前拒绝。

8. 协调补充资源边界：新增两个离线回归测试先 RED（宽波段粗网格被旧默认限制拒绝）。修改范围 models.py/adapter.py（2 业务文件），子类 interpolate(None) 在原构造首次调用时使用用户显式 step，否则 .005；分配前再次检查点数。static 不再二次插值；dynamic 仍在获取后按主动选择插值。测试 spy 原 SimulatedLIBS.interpolate，断言 200–5000 nm/step=1 仅调用一次、分配 4800 点，超限细网格仍拒绝。

9. 真实 Full Access 动态诊断：当前 NIST H 单离子 CSV 只有 Wavelength (nm),H I，省略 Sum(calc)。保存原始 CSV/driver 日志后建立真实捕获 fixture 回归，先 RED；范围 storage.py/adapter.py（2 业务文件）。仅当一个合法元素/罗马离子级贡献列时复制原值为 Sum(calc)，不插入假离子贡献；来源 ion_total 明示 copied sole H I contribution。多列缺 Sum 继续拒绝。读 coordinator-permission-note.md，确认 workspace-write 的 tab crashed / screen capture 不是应用或 NIST 不可用证据。
10. 范围：start_ui.cmd/start_ui.ps1/README.md（3 业务文件）。启动器离线测试先 RED，发现 CMD LF/PowerShell 无 BOM 编码问题；改 CMD UTF-8+CRLF、PS1 UTF-8 BOM+CRLF 后从其他工作目录诊断 GREEN。系统默认 ExecutionPolicy 禁止脚本；README 给 CMD/直接 Python 或仅本进程 Bypass 命令，没有修改全局策略。
11. 范围：app.py/run_ui.py（2 业务文件）。CLI smoke 首次 60s 超时，补真正 Tk /历史导入/后台 CSV PNG JSON 导出/自动关闭；stdout 明确 UTF-8，避免 Windows GBK 与日志 UTF-8 不一致。diagnose 不联网。范围 verify_real.py/README/adapter 仅 3 业务文件，补真实复验工具和说明；支持 --dynamic-only / --static-only，后续诊断不重跑全量模拟。
12. 范围：models.py（1 业务文件）。有限但极大整数/占比和、极小步长使中间算术溢出：离线用例先 RED，统一 ValueError，在分配网格/worker 前拒绝，GUI 不泄漏 OverflowError。
13. 范围：app.py/verify_real.py（2 业务文件）。原坐标截图拍到其他前景照片窗口，不能作为布局证据；原 output/smoke-full-access/tk-smoke.png 已删除。新截图函数只捕获本应用 HWND（Pillow window=，不抓桌面 bbox），有离线参数断言；实际 Tk 测试成功与错误截图明确分开。ttk 使用 clam 统一主题，消除 HWND 捕获下原生主题重绘残影；最终图片已实际查看。
14. 范围：storage.py/README.md（2 业务文件）。源 saved/contents.csv 名称列实际为前导空格的“ samples”；新增真实源样例测试先 RED，读取后先 strip 列名再映射。read_compositions 最多读 5001 行并拒绝 >5000；历史读最多 MAX_POINTS+1 后拒绝超限。源 data.csv 3 行全部校验通过，95% 历史组成确实拒绝；完整结果目录重定位/拒绝覆盖测试通过。
15. 范围：adapter.py（1 业务文件）。最终合并测试暴露源目录永久留在 sys.path 首位而遮蔽 UI/tests 名称空间。新增路径泄漏测试先 RED，改临时插入/导入/finally 移除；真实源包 __path__ 和已验证 class/file 仍保存，源文件不改。完整 45 测试随后 GREEN。
16. 最小 950×680 布局回归先 RED：批量“校验”、目录/GIF 按钮被横向裁掉；补取消/进度可见性断言又定位到外层 pack 将状态栏裁掉。范围 input_views.py/app.py/result_view.py（3 业务文件）：批量按钮 3 列换行、导出 4 列换行；外层 top/body/status 三行 grid，中间图区和右侧图区域有权重缩放；Matplotlib 工具栏先保留底部空间。最小窗口全部操作/取消/进度可见性测试 GREEN。仅重跑离线/Tk，不重复全量科学模拟。最终 UI 截图 output/smoke-final-layout/tk-smoke.png 已实际看图，状态栏与取消按钮均可见。

## 最终文件清单
共 28 个实现/测试/说明文件，机器可读清单 files.json。

| 文件 | 作用 |
| --- | --- |
| run_ui.py | 入口定位、禁止 source 字节码写入、UTF-8 CLI 输出 |
| start_ui.cmd / start_ui.ps1 | 固定已有 3.10 环境、版本检查、可显式覆盖、任意 cwd 启动 |
| README.md | 中文完整使用与网络/Chrome/配置/导出说明 |
| verify_real.py | 真实 Tk 与同一 worker 复验、逐项落盘、针对性动态复验 |
| simlibs_ui/__init__.py | 包信息 |
| simlibs_ui/models.py | 参数、配比、范围、扫描值、资源和 finite 校验 |
| simlibs_ui/settings.py | 本地设置、预设、JSON 配置校验与往返 |
| simlibs_ui/storage.py | 组成/历史导入、schema、原子存储、全量文件和小预览 |
| simlibs_ui/adapter.py | 真实 SimulatedLIBS、有限 HTTP、真实 CubicSpline、动态导航/驱动/单离子适配 |
| simlibs_ui/worker.py | 独立后台入口、所有权启动门、进度/结果/错误/导出协议 |
| simlibs_ui/jobs.py | Windows Job Object、超时/取消/关闭、旧消息隔离、保留成功结果 |
| simlibs_ui/operations.py | 有界批量、三轴扫描、partial、全量 CSV/目录/PNG/GIF 导出 |
| simlibs_ui/plotting.py | 共用绘图、零谱安全归一化、Agg/Pillow 后台导出 |
| simlibs_ui/input_views.py | 共同参数、配比与三个工作页输入（合并计划中的三个 view 模块） |
| simlibs_ui/result_view.py | Matplotlib 工具栏、视图选择、有限分页预览、来源说明 |
| simlibs_ui/app.py | 桌面事件、设置/配置、导入导出、播放/暂停、smoke/diagnose、所属窗口截图 |
| tests/test_models.py / test_storage.py / test_adapter.py | 参数/资源/源适配/历史与真实捕获 CSV 回归 |
| tests/test_jobs.py / test_app.py / test_cli.py | 真实受控进程、Tk 心跳、取消/关闭、GUI、CLI/启动器 |
| tests/test_operations.py | seed、范围、schema、partial、逐帧、不同网格、GIF 与目录重定位 |
| tests/job_fixture.py / tests/__init__.py | 无网络受控慢/失败/后代 worker 与测试包 |
| tests/fixtures/nist_H_singleion.csv / README.md | 真实 NIST 2026-10-02 捕获的单离子格式离线 fixture，明确不作为新模拟 |

新增工作流记录 implementation.md、files.json、unittest-final.log；UI/output 下为自测结果与诊断；UI/.driver-cache 为匹配驱动缓存。未增加依赖、未创建 pane/agent/终端、未修改源库、未提交/合并 Git。plan.md 不改写；本实现与原计划差异仅模块合并和已说明的 UI 适配。

## 实际执行的验证及结果
所有 Python 命令使用 D:\Anaconda3\envs\simLIBS\python.exe（3.10.20），cwd=UI；完整独立验收仍待 reviewer。

### 离线与真实窗口
```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\run_ui.py' --diagnose
cmd /c start_ui.cmd --diagnose
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_ui.ps1 --diagnose
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\run_ui.py' --smoke-test --output '.\output\smoke-final-layout'
```

- 最终离线集合 **46 测试、17.048s、OK、exit 0**；原输出在 unittest-final.log。默认 tests 没有真实外网请求；adapter 用 mocked HTTP/Selenium/manager，实际执行真实构造/HTML 解析/get_* /原 CubicSpline。
- diagnose 所有 10 依赖存在，source_exists=true，network_used=false，driver_downloaded=false；两个启动器从 UI 的父目录运行同样诊断通过。
- 最终 Full Access smoke：**4.047s、59 心跳**，实际 Tk 三页、历史源导入、后台 CSV/PNG/JSON 导出、自动关闭。new_simulation=false，历史来源 docs/single_simulation.csv；来源 SHA256 73cb0fbe6bd677e564945d901305671ad59a9447626d2b7c24f6882ace7bf107。
- **最终真实 UI 截图**：**output/smoke-final-layout/tk-smoke.png**（只 capture 本应用 HWND，已看图核对）；报告 output/smoke-final-layout/smoke.json。较早 smoke-final 仍是真实本应用截图，但最终布局以本次为准。原拍到照片查看器的坐标截图已删除，不作为任何验收证据。旧受限环境 screen grab failed 的报告同样不能证明 UI 不可用。
- Tk 定时心跳/慢 worker、取消/窗口关闭 <5s、所属后代清理、无关进程保留、超时、旧消息隔离、失败保留结果和重试已自动验证。最后只读 Get-Process Chrome/ChromeDriver count=0；未用按名称终止进程命令。

### 真实联机
```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\verify_real.py' --output '.\output\real-validation-complete'
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\verify_real.py' --dynamic-only --output '.\output\dynamic-fixed-full-access'
```

第一条覆盖静态/批量/扫描/导出，最后动态在旧 workspace-write 环境报 tab crashed；不能把该条总体 exit=1 当成静态失败。动态后续在已授权 Full Access 中诊断并修复单离子 schema，第二条全部成功，exit=0。没有重复全量模拟；协调者另有 coordinator-dynamic-full-access 的修复前 CSV 校验失败记录。

| 验证 | 实际结果 | 时间/响应 | 证据 |
| --- | --- | --- | --- |
| H100 static，Te=1、Ne=1e17、R=1000、650–660 nm | raw 47×2、interpolated 2000×2；均 finite，max=1802；CSV/PNG/JSON 全量成功 | 4.000s、117 心跳 | output/real-validation-complete/real-validation.json；H-raw.csv、H-interpolated.csv、H.png、H-origin.json |
| 真实 size=2 批量，seed=42 | 2×2004 宽表；元素 H/name/Te[eV]/Ne[cm^-3] 末列；两次真实调用 | 4.172s、131 心跳 | dataset-size2.csv 与 JSON；每个 sample manifest |
| Te 1→1.2，两帧 | 2 帧真实请求、finite；最大强度差 6437；GIF 打开 n_frames=2 | 4.734s、149 心跳 | Te.gif、Te-frames/manifest.json |
| Ne 1e17→1.2e17，两帧 | 2 帧真实请求、finite；最大强度差 10.16654412；GIF n_frames=2 | 4.515s、142 心跳 | Ne.gif、Ne-frames/manifest.json |
| R 1000→1200，两帧 | 2 帧真实请求、finite；最大强度差 360；GIF n_frames=2 | 4.062s、127 心跳 | R.gif、R-frames/manifest.json |
| H dynamic/ion（修复后 Full Access） | raw=interpolated 49×2（原 NIST 网格），ion 49×3（Wavelength/H I/Sum）；finite、max=1802，完整 ion CSV 成功 | 14.359s、450 心跳；ion 导出 0.734s/23 心跳 | output/dynamic-fixed-full-access/real-validation.json、H-ion.csv、H-ion.csv.json |

真实静态 PNG 已用 view_image 检查，单位/标题/图例/曲线可读；三种真实 GIF 均用 Pillow 打开并确认 2 帧，各帧 CSV 和参数清单独立保留，导出目录路径已重定位。所有记录中的 worker_exited=true。
动态 Chrome=154.0.8037.58，实际匹配驱动=154.0.8037.92（major.minor.build 相同）；headless 参数明确 --headless=new，keep_browser_open/detach 固定 false。当前页面只返 H I，未伪造 H II/H III 曲线。nist-dynamic.csv 和 chromedriver.log 保存在任务目录。最终读取 Chrome/ChromeDriver 无残留。

### 源哈希复核
source-baseline.json 的 3 个条目逐一重算 SHA256 均相同：

| 源文件 | SHA256（未变） |
| --- | --- |
| simLIBS/simulation.py | 4279A121C07D88D1BEF9E6E8650B2DF77EF04A6B4CCA28B705AFC143ED2FA899 |
| simLIBS/animation.py | EEE804D29155A4130FB7CA2F2C378A38BA2653B43817B1518EDC31975E296DCC |
| simLIBS/__init__.py | EA49DBDFD082A543137ED75619C18F3AA21C2B4924AB8721D0284B4A322FB24A |

## 已考虑的边缘情况与建议复验
- NaN/Inf、巨大有限数中间溢出、0 Ne/Te/R/步长、负占比、空/重复/未知元素、总和 95/101、相等/反向波段、非整数电荷/R、扫描重复取整值、空表、重复波长、无原始插值点、网格/总单元/帧数超限均拒绝。验证发生于 worker 前与 worker 内。
- 0 占比字段保留数据集而不请求 NIST；归一化仅主动按钮；95% 不补尾元素。浮点容差内 >100 残差只在请求最后一项消除并保存实际提交值。
- 历史索引、空/带空格列名、*_at%、名称列位置/中文路径；真实 samples 带前导空格；配置 JSON roundtrip/损坏配置；分页抽样与完整导出有明确差别。NIST 默认动态边缘网格可能超出请求边界，原始数据原样保留；用户主动插值才使用固定区间。
- 批量共同网格失败、网络中途失败/取消 partial、种子可复现、每帧 Te/Ne/R 透传、不同网格扫描、全零 GIF、原子写入、完整目录拒绝覆盖与路径重定位。
- 子进程异常/超时、合作取消/强制回收、关闭无 join、迟到 job_id、上一成功结果保留、重新运行、其他进程不受影响。动态成功/失败都 quit，驱动不匹配具体报版本。
- reviewer 建议先运行同一 46 unittest 和 --smoke-test，从任意目录启动脚本并检查三个页面、设置、批量编辑、历史来源与最小窗口取消按钮；然后只用 --dynamic-only 复核修复（现有结果已覆盖完整科学流程，不需无理由反复全量请求）。所有离线/真实结果必须与来源 JSON 对照。

## 未完成与风险（如实交接）
请求的功能已实现并完成 coder 自测，**独立 reviewer 验收尚未执行/未宣布通过**。未打包 exe（原范围之外）。
真实联机当前已成功，后续 NIST 页面/网络/TLS、Chrome 与 driver 的版本/下载供应仍有外部依赖；具体错误会显示，不用历史数据冒充成功。旧 workspace-write 与 Full Access 的结果不同，禁止把受限执行崩溃误判为产品不可用。
预览最多 1500 等距点（可能漏尖峰）和每页 100 行，页面明确提示；全量 CSV/PNG/GIF 不抽样。动态单离子 Sum 复制规则严格限定唯一合法贡献，其他未知 schema 报错；没有创造未返回的离子级。
保留所有诊断/失败/partial 目录作为可追溯证据，未删除用户输入或其他浏览器。只删除本任务错误截图。源库默认 Ne 有三位有效数字处理，来源同时保存输入 Ne 与实际 Ne；源科学公式未改。
本文件、task.md、plan.md、files.json、unittest-final.log、真实输出与最终 HWND UI 截图交给协调者，由既有 reviewer 独立验收；coder 到此停止，不自行操作 reviewer pane。
此记录中的阶段结果只代表 coder 自测，不代表独立验收通过。

## 第一轮独立验收返工

按 rework-task.md 分三小步执行，review.md/review-round1.md 保持原样，源库不改。新增回归先运行观察失败，再修改。首版已通过的静态/批量/扫描科学证据保留，本轮不重复全量 NIST 流程。

### R1/P1：科学 CSV 缺失值（adapter.py/storage.py，2 业务文件）

新增 adapter/storage/jobs 回归及 tests/mock_dynamic_worker.py。使用真实源库构造/getter 和真实 worker/JobController，只 mock Selenium 传输。先执行 4 个新测试：9 个子用例失败、2 个合法稀疏支持用例报错，确认缺失波长/NaN 总谱此前确实被接受为 SUCCEEDED。
改为 dtype=str + keep_default_na=False 保留 CSV 原始词元，删除整表 fillna(0)。清理层只把合法元素+罗马离子贡献列的真正空字符串/空白字符串按零贡献处理；np.nan/pd.NA/None、NaN/Inf/NA 文本、波长空白及已有总谱空白均拒绝。单一 H I 缺 Sum 仍复制原值并保留来源说明，已有损坏 Sum 不会复制覆盖。历史 CSV 使用同样严格语义；来源记录 ion_blank_policy。
实际 mocked worker 负向用例验证 FAILED、无成功 manifest、driver.quit=1、保留旧 result/path。受影响 adapter/storage/jobs 集合 26 测试、8.979s、OK、exit0；用 -W error::FutureWarning 复查无 pandas 警告。
只做一次针对性真实动态：verify_real.py --dynamic-only --output output/rework-r1-dynamic。dynamic SUCCEEDED，14.047s/433 心跳；raw/interpolated 49×2、ion49×3，单一 H I 原值与 Sum 一致；完整 ion 导出 0.844s/27 心跳，worker 退出、源 hash 不变。证据 output/rework-r1-dynamic/real-validation.json、H-ion.csv、来源 JSON、原始 nist-dynamic.csv。

### R2/P2：扫描中间溢出与逐帧契约（models.py，1 业务文件）

5 个新回归先 RED：11 个子用例失败、2 个异常，复现 Te/Ne 派生 inf、R round(inf) 抛 OverflowError、坏派生帧仍调用 Popen。
count 模式先生成 i/(n-1) 比例，再乘 delta；精确保留两端，step 模式也保留输入起点/终点。每帧检查 finite、正数、范围、顺序和实际端点；R 保留既有取整语义与正整数契约，重复取整值拒绝。无法用当前浮点精度表示不同帧时抛可读 ValueError，不静默重复。
ScanSpec 再次检查派生帧，并逐帧调用同轴 Parameters.validated；NaN/Inf/0/越界/倒序在启动 worker 前拒绝，Popen 和 requests 零调用。Te/Ne/R 的 1e308→1.7e308 五帧完整有限，没有无依据的物理上限。受影响 models/jobs/operations 集合 25 测试、10.275s、OK、exit0。保持原终点包含规则、最多200帧和500万单元限制，未向 NIST 发送极端参数。

### R3/P2：最小窗口结果控件/分页（result_view.py，1 业务文件）

实际950×680新回归先 RED，精确复现颜色 width16<requested93、归一化未映射、上/下页未映射四处失败。结果控制区改为两行 grid，标题输入随剩余宽度伸缩；来源和预览说明按实际宽度折行。数据表用加权行 grid 分配表体，固定预留横向滚动条与分页行，不让 Treeview 先占完高度。
验证实际映射、请求尺寸、所有祖先裁剪边界、颜色选择/归一化 invoke、上下页数据改变和恢复。最小尺寸仍950×680；绘图/表格、导出、播放、进度和取消保持可用。app 7 个测试3.470s、OK、exit0。新 smoke：output/rework-smoke，4.047s/59心跳，历史导入/后台 CSV PNG JSON 导出，new_simulation=false、自动关闭。
实际最小布局检查通过后保存 output/rework-r3-min-window/plot-950.png 与 table-950.png，均只捕获本应用 HWND；checks.json 保存控件尺寸和实际翻页数据。第一次辅助截图脚本因 PowerShell stdin 默认为 us-ascii 将中文查找词变成问号而报错，未取得错误截图；定位后只为该执行进程使用 UTF-8 stdin 再验证，不改变全局设置。期间用 ASCII stdin 追加的返工文段也已重写为正确 UTF-8，业务源文件和原 review 不受影响。

进一步看图发现最小画布中完整归一化轴标签超出边界；用真实8000行源历史样例增强同一Tk回归，先 RED（label.y1=143.660 > canvas126），随后仅将 UI 轴标签缩为常用的 Normalized I；科学数据和全量PNG/GIF标签不改。最终 label bbox y=[32.410,117.535]，在125px画布内。受影响 app 集合7测试、3.896s、OK、exit0。最终两张图片已实际 view_image 查看，分页第二页100行、来源未知历史提示、颜色/归一化和取消均可见；保持950×680。

## 本轮最终命令、结果与交回

工作目录 UI，Python 均为 D:\Anaconda3\envs\simLIBS\python.exe，带 -B。下面所有结果仅为本轮 coder 修复验证，**由原 reviewer 再独立复验，不代表独立通过**。

```powershell
# R1 受影响集合（含科学坏 CSV 实际 mocked worker）
& 'D:\Anaconda3\envs\simLIBS\python.exe' -W error::FutureWarning -B -m unittest tests.test_adapter tests.test_storage tests.test_jobs -v
# R2 受影响集合
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest tests.test_models tests.test_jobs tests.test_operations -v
# R3 真实 Tk 回归
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest tests.test_app -v
# 最终完整离线集合
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v
# 本轮新实际 Tk smoke（历史数据，未做新模拟）
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\run_ui.py' --smoke-test --output '.\output\rework-smoke'
# 本轮仅针对性真实 dynamic/ion（已授权 Full Access）
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\verify_real.py' --dynamic-only --output '.\output\rework-r1-dynamic'
```

| 项目 | 最终实际结果 | 证据 |
| --- | --- | --- |
| 完整离线 unittest | **57 tests，23.948s，OK，exit0**；原有46测试及本轮11个回归均通过 | unittest-rework-round1.log（UTF-8） |
| 科学坏CSV | 波长/总谱缺失、字面NaN/Inf贡献拒绝，实际 mocked worker FAILED，无成功manifest，旧result/path保留，quit=1；合法稀疏/单H I仍通过 | tests/test_adapter.py、test_storage.py、test_jobs.py、mock_dynamic_worker.py |
| 大有限扫描 | Te/Ne显示值约为1e308、1.175e308、1.35e308、1.525e308、1.7e308（完整双精度值见JSON）；R为对应正整数，全部有限；坏派生帧Popen/requests零调用 | tests/test_models.py、test_jobs.py；rework-final-check.json |
| 针对性真实dynamic | SUCCEEDED 14.047s/433心跳，raw/interpolated49×2、ion49×3；完整ion导出0.844s/27心跳，worker退出，所有请求均使用原源类路径 | output/rework-r1-dynamic/real-validation.json、H-ion.csv、H-ion.csv.json |
| 新实际Tk smoke | 4.047s/59心跳，三页、历史导入与CSV/PNG/JSON后台导出，new_simulation=false，自动关闭 | output/rework-smoke/smoke.json、tk-smoke.png、history.* |
| 最小950×680实际绘图页 | 颜色93×33、归一化81×23、标题93×33，均映射/满足请求尺寸/在祖先边界内；实际改色+归一化，max=1，轴标签也完整 | output/rework-r3-min-window/plot-950.png、checks.json |
| 最小950×680实际表格页 | 上/下页93×33，均映射；invoke后第2/15页、100行、首波长200→253.3；上一页恢复；取消/进度可见 | output/rework-r3-min-window/table-950.png、checks.json |
| 源基线与范围 | 源3/3 SHA256未变；旧冻结UI只改4业务+5测试文件，另加1离线worker测试辅助文件；files.json更新为29项；app.py和其他业务均未改 | rework-final-check.json、files.json |
| 残留 | 交回时只读Get-Process：Chrome/ChromeDriver count=0；无按名称杀进程操作 | 本轮工具输出；既有所属Job清理测试继续通过 |

本轮4个业务改动严格拆为R1两文件、R2一文件、R3一文件，没有任何一步超过3个业务文件。新增测试辅助位于 tests/，仅离线 mocked Selenium，不用于生成UI科学数据。原 unittest-final.log、review.md、review-round1.md、review-baseline.json 及已通过的真实静态/批量/扫描/单离子证据保留，不伪装原独立结论，也不擅自改冻结基线；由协调者重新冻结后交原 reviewer。

本轮未增加物理参数上限，未改变源科学公式、单离子原值复制规则、启动环境或全局设置，未创建 agent/pane/新终端。CSV允许空白归零的边界严格限定合法离子贡献，波长和已有总谱永不补零；未来未知CSV格式仍报错而非猜测。NIST/Chrome/driver仍有外部依赖，当前针对性真实复验已成功。

R1/R2/R3 修复及 coder 验证完成；停止业务修改，交协调者安排原 reviewer 复验。
