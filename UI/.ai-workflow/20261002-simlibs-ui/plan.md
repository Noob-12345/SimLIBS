# simLIBS 本地桌面 UI 实现计划
日期：2026-10-02；状态：规划完成，业务代码尚未实现；交接给协调者安排原 coder → 原 reviewer 顺序执行。

## 1. 目标与边界
- 目标目录 `D:\LIBS\simLIBS-2.0.3\UI`；真实源库为同级 `simLIBS-2.0.3` 目录，全程保持源库文件不动。
- 使用 tkinter/ttk + 嵌入 Matplotlib，中文界面、系统字体、屏幕自适应；三个工作页：单次模拟、批量数据集、参数扫描动画。
- 使用 `D:\Anaconda3\envs\simLIBS\python.exe`（3.10.20）及已有依赖；不使用默认 Python 3.7，不安装 pytest、ImageMagick 或额外桌面框架。
- 用户已授权实现及外部 Herdr 协调；不再要求方案批准，不 split pane、不启动新 agent；规划、编码、验收保持独立顺序交接。
- 交付可启动桌面应用、离线测试、启动脚本和中文说明；打包 exe、改变源库算法、离线物理求解器不在本次范围。

## 2. 已核对证据
- `README.md`、`simLIBS/simulation.py`、`simLIBS/animation.py`、`tests/test_SimulatedLIBS.py`、`test.py`、依赖及 CSV 样例已读取，禁止重复全量探测。
- 协调者 `coordinator-notes.md`：真实 H=100%、Te=1 eV、Ne=1e17、650–660 nm、R=1000 静态成功，HTTP 200、raw 47 行、interpolated 2000 行，最大强度 1802.0；源库未改。
- NIST 组分为原子数密度占比，总和应为 100%；源码只拒绝总和超过 100%，UI 必须补足校验。官方说明见 https://physics.nist.gov/PhysRefData/ASD/LIBS/libs-form.html。
- 源库构造立即联网；static 请求没有 timeout，使用 verify=False；dynamic 依赖 Chrome、ChromeDriverManager、页面 XPath 和 CSV 弹窗。
- 当前 Selenium 中源码 `options.headless = True` 不生成 headless 参数；Chrome 已有，随库驱动 103 与 Chrome 154 不匹配，已发现缓存也不能直接当作匹配驱动。
- `create_dataset` 按 size 建线程、依赖 name 最后一列、固定默认波长等参数；动画固定 dynamic、全局 pyplot、固定保存位置及 ImageMagick。
- 源库 Ne 存为字符串，str/repr 数值格式化会失败；raw 可能为字符串列，动态 raw/interpolated 原本相同；不能虚构独立插值或离子结果。
- 样例：`data.csv` 为 W/H/He/name；`docs/single_simulation.csv` 有旧索引列；`saved/contents.csv` 为 samples 和 *_at% 且总和约 95%；历史光谱均不是本次生成。

## 3. 功能与交互契约
- 单次：Te[eV]、Ne[cm^-3]、光谱分辨率 R、波长上下界[nm]、最大离子电荷、static/dynamic、headless；混合元素逐行新增/编辑/删除、导入与主动归一化。
- 三种结果视图：raw、interpolated、ion；绘图含标题、颜色、图例、单位和工具栏，数据表分页；static 无 ion 时禁用并解释需动态获取。
- 区分 R 与重采样步长[nm]：保留源库默认 static 0.005 nm；自选网格调用真实 interpolate；dynamic 默认保留 NIST 网格，重采样须用户明确选择。
- 动态默认 `headless=True, keep_browser_open=False, detach_browser=False`；后两项作为源库调试生命周期参数固定关闭，并在说明中列出，保证应用可管理浏览器关闭。
- 批量：导入组成 CSV、预览/校验每行、name 映射、样本数、Te/Ne 范围、随机种子及公共模拟参数；按源库随机选择组成与均匀采样语义生成。
- 扫描：Te、Ne、R 三选一，起止值、步长或帧数、固定其余参数、static/dynamic；显示实际生成值和预计请求数，生成后播放/暂停/逐帧，导出逐帧 CSV 和 GIF。
- 内置预设至少含已验证 H 窄波段及 README W/Fe/Mo；配置/预设 JSON 保存、导入、恢复默认，加载不自动联网；设置解释器、源目录、驱动路径、超时和输出位置。
- 导出 raw/interpolated CSV、完整 ion CSV、PNG、参数/来源 JSON、批量宽表 CSV、扫描目录/GIF；表格导出无索引，图像/GIF用已有 Pillow。
- 离线打开已有 CSV 和内置历史示例；持续显示“已保存数据/来源路径/参数未知”，不得显示“本次模拟成功”；导出保留该来源说明。

## 4. 实现结构与适配决定
- `run_ui.py` 负责入口、源目录定位及诊断；`simlibs_ui/` 下 models/settings/storage、adapter、jobs/worker、operations、app/views；tests 使用标准 unittest。
- adapter 调用真实 `SimulatedLIBS` 构造与 get_raw/get_interpolated/get_ion；保存源文件路径、SHA256、请求参数、实际 Ne、NIST URL、时间和模式作为调用证据。
- 必要修正仅限 UI 进程内适配：有界 HTTP 请求、数值列整理、格式错误转换、显式 `--headless=new`、驱动定位及浏览器超时；不替换科学数据为固定示例。
- 对需在原构造插值前整理 raw 的情况，可用子类调用 `super().__init__` 并在 interpolate 前做有限值/排序/重复点检查；最终仍调用原 interpolate，测试证明真实基类路径。
- dynamic 优先使用配置的匹配驱动或匹配缓存；确需下载时由后台原 webdriver_manager 执行，记录下载依赖与失败；不得静默使用随库旧驱动。
- 批量和扫描由 operations 有界顺序循环，每个样本/帧调用同一真实适配层；不直接启动 size 个源库线程；记录这是 create_dataset/animation 的 GUI 功能适配及原因。
- 批量宽表要求共同网格（显式重采样后检查一致），末列为元素占比、name、Te[eV]、Ne[cm^-3]；扫描允许逐帧不同网格，用逐帧 CSV 与 manifest 避免强行拼接。
- 网络、驱动下载、Selenium、批量、扫描、重导出均在专属子进程；Tk 主线程仅事件、绘图和 after 轮询，禁止在按钮回调联网、join 或等待 future.result。
- worker 输出小型进度/结果消息和临时完整数据文件；显示预览限量并注明，CSV保留全量；大 CSV 读写和 GIF 渲染不占主线程。
- jobs 使用唯一 job_id 和 IDLE/RUNNING/CANCELLING/SUCCEEDED/FAILED/CANCELLED；一次运行一个生成任务，旧消息不得覆盖新任务，失败保留上一份成功结果。
- 取消先发协作信号停止后续请求，短暂宽限后终止本任务子进程及其 Chrome/driver；Windows 用所属 Job Object 或准确 PID 的进程树清理，禁止按 chrome.exe 全局杀进程。
- 关闭采用同一清理路径；只用 after 轮询结束，不阻塞事件循环；工作进程开始联网前已纳入所有权，防止浏览器遗漏。
- 默认 connect/read timeout=10/30s、页面加载45s、脚本15s，单次 static 总期限60s、dynamic180s；批量逐样本计时，截止后失败且不再发下一请求。
- TLS 默认正常证书校验；若现有源库 verify=False 被适配覆盖，明确记录此差异；网络/证书/驱动/页面格式异常显示具体原因与重试入口，不回退成假数据。
- 结果/配置原子写入；取消仅生成标记 partial 的已完成样本，禁止作为完整成功输出；仅清理本任务临时目录，用户输入与已有文件不得覆盖。

## 5. 输入与资源校验
- 在启动 worker 前、worker 内各校验一次：所有数值有限；Te/Ne/R/采样步长>0，0<low_w<upper_w，电荷为非负整数，模式合法。
- 元素必须是有效化学符号，无重复、非空；百分比有限非负，总和100（绝对容差1e-6）；零占比可保留在数据集列，实际请求移除零项。
- 不把负数、NaN、无穷或空单元格转为0；不自动把95%补到末元素。归一化仅由明确按钮执行，展示前后值并保存实际提交配比。
- CSV清除已识别的历史索引列、空白列名；name允许映射后统一放末列；*_at%显式映射为元素，95%样例必须经用户归一化后才能生成。
- 样本数/帧数正整数，范围最小值<=最大值，扫描不能空或反向；定义终点包含规则，避免浮点累计和 zip 静默截断；R扫描每帧为整数。
- 提交前计算网格点数、样本×点数与帧数；默认上限单谱200000点、批量5000000单元、扫描200帧，超过时请求缩小任务，不能进入无界分配。
- raw/ion 空表、非数值、非有限、重复波长或不足插值点判定为获取失败；零谱允许展示，归一化时保持零避免除0；不硬编码历史谱强度验收线上新结果。

## 6. 顺序实现步骤（每步最多3个业务文件）
以下均为 UI 相对路径；测试按对应步骤同步添加，测试文件不算业务文件；每步先可复现 unittest，再实现并记录 implementation.md。
1. `run_ui.py`、`simlibs_ui/__init__.py`、`simlibs_ui/models.py`：入口/数据契约/校验；验收非法输入零请求、源导入定位准确。
2. `simlibs_ui/settings.py`、`simlibs_ui/storage.py`：配置预设、组成/历史谱导入、原子导出及来源；验收100%/95%/NaN、旧索引、中文路径、JSON往返。
3. `simlibs_ui/adapter.py`、`simlibs_ui/worker.py`：真实构造、static/dynamic 适配与单任务协议；验收真实类+mock传输、超时、headless参数、driver.quit。
4. `simlibs_ui/jobs.py`、`simlibs_ui/app.py`、`run_ui.py`：进程所有权、消息轮询、窗口骨架；验收后台等待时UI心跳、取消关闭及迟到消息隔离。
5. `simlibs_ui/single_view.py`、`simlibs_ui/app.py`：参数/混合编辑、预设、单次提交；验收每个构造参数透传、归一化主动操作、按钮状态恢复。
6. `simlibs_ui/plotting.py`、`simlibs_ui/result_view.py`、`simlibs_ui/app.py`：raw/interpolated/ion、预览和CSV/PNG导出；验收静态无ion、动态图例、全量导出及旧结果保留。
7. `simlibs_ui/operations.py`、`simlibs_ui/worker.py`：有界批量、随机种子、统一网格、进度与partial；验收name映射、取样参数范围、取消后无新请求。
8. `simlibs_ui/batch_view.py`、`simlibs_ui/app.py`：批量导入编辑、范围/数量设置和输出；验收data.csv三行、多样本schema、逐行报错及重试。
9. `simlibs_ui/operations.py`、`simlibs_ui/plotting.py`、`simlibs_ui/worker.py`：三类扫描、全零安全归一化、Pillow GIF；验收每帧真实调用及参数变化、不同网格、GIF可读。
10. `simlibs_ui/scan_view.py`、`simlibs_ui/result_view.py`、`simlibs_ui/app.py`：扫描设置/播放/暂停/逐帧/导出；验收播放不联网、暂停有效、CSV/GIF来源一致。
11. `simlibs_ui/settings.py`、`simlibs_ui/app.py`：配置对话框、源/驱动/超时/目录设置；验收导入配置仍校验、无启动下载、损坏配置可恢复。
12. `start_ui.cmd`、`start_ui.ps1`、`README.md`：固定默认3.10并允许显式覆盖、相对目录引用、中文步骤与NIST依赖；验收任意工作目录启动、缺环境有可读错误。
13. `run_ui.py`、`simlibs_ui/app.py`：补齐 --diagnose 和 --smoke-test 验收入口；随后独立 reviewer 运行下述检查，问题交原 coder，每轮修复仍<=3业务文件。

## 7. 可操作验收与交接门槛
- 离线命令（cwd=UI）：`& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v`；默认测试严禁真实外网请求，记录数量与通过/失败。
- 测试至少覆盖 models/storage/adapter/jobs/operations：非法参数包括0 Ne、负百分比、NaN/Inf、空/重复元素、总和95/101、相等波段、0步长；断言未启动worker/未调用传输。
- adapter测试mock requests响应HTML、ChromeDriverManager及Selenium driver；调用真实构造/解析/get_*，验证数值谱、dynamic ion、有限timeout、headless实际参数、成功/异常都quit。
- jobs测试使用受控慢worker和错误worker：UI定时回调继续，取消/关闭5秒内清理所属进程树、无后续请求、无孤儿浏览器；其他Chrome会话保留；重新运行正常。
- operations测试固定seed组成选择、实际Te/Ne范围、R/Te/Ne逐帧透传、批量列序/网格一致、部分失败标记、零谱GIF和导出CSV往返；原create_dataset小样本可mock worker做schema对照。
- 真实启动命令：`& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\run_ui.py'`；reviewer看见真实窗口、三工作页、绘图工具栏、表格与设置，留截图/日志；不能以仅import通过代替。
- `--diagnose` 不联网，报告解释器/依赖/源路径；`--smoke-test` 创建真实Tk窗口、载入标明历史来源的CSV、绘图导出PNG/CSV/JSON、自动关闭并保存检查日志；不宣称进行了新模拟。
- 真实联网复验用协调者H窄波段参数；检查非空finite谱、参数/来源JSON、主线程响应和CSV/PNG；47/2000/1802是既有证据，不能硬要求未来NIST结果逐值相同。
- dynamic必须尝试真实Chrome适配并取得raw/ion，验证浏览器退出；再真实运行小批量size=2和Te/Ne/R各2帧（可先static）并打开GIF；离线mock通过不能替代此记录。
- 若网络/驱动外部条件阻止真实验证，review.md逐项标“未验证/原因/实际异常/复验命令”，不得写全功能通过；已验证static仍保留，新模拟失败不显示历史示例成功。
- 独立reviewer核对真实SimulatedLIBS调用证据、源库文件哈希未变、无不必要安装、关闭残留和所有导出；implementation.md/review.md列命令、结果、风险，问题由原coder修复后原reviewer复查。

## 8. 风险、回退与最终移交
- 主要风险：NIST网络或页面改变、Chrome/driver版本、第三方驱动下载、Windows进程树回收、160000点默认插值及批量内存；以上均有超时/上限/离线测试与真实验收对应。
- source保留不动；先记录哈希，只增加UI文件；确需源改动时提交可复现证据给协调者，不直接覆盖用户修改；失败回退仅撤销本次UI文件/配置备份，不动saved数据。
- GUI失败恢复到可编辑状态，保留上一成功结果和错误日志；离线功能可独立使用，但从不作为NIST模拟失败的伪成功回退。
- 当前无必须等待用户决定的事项；coder按此计划执行，不再等待二次批准。规划agent在写完本文件后停止，由协调者向既有编程pane移交该路径并安排验收。
