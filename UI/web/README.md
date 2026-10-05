# SimLIBS · SPECTRUM WORKBENCH FOR SCNU

项目根据组成及等离子体参数生成真实离线/NIST LIBS 光谱、训练数据和参数扫描；前端数据经本机 `/api/*`，进度经SSE推送，由共享Python后台和专属worker执行。

## 元素选择与参数输入

输入 `f` 可从候选中点击选择 `Fe`，也支持上下键、Enter、Esc；候选使用规范大小写并排除其他行已使用的元素。可编辑最多 32 个元素，支持完整参考 28 元素组成。`fe`/`FE` 仍在失焦或提交时规范化，重复/无效元素和无效占比草稿阻止提交。

Te [eV]、实际Ne [cm⁻³]（如1.23e17）、整数R支持直接输入与滑块双向同步，合法数字可超出滑块初始范围。空值/非正/非有限/小数R拒绝，Ne草稿保留至失焦，自动赋值科学计数。新界面发送mode_version=2和local/server/client，处理路径固定；插值有显式独立步长，批量使用批量页自己的步长。

## 真正离线 local v2

默认Fe100%，仅读取../Linedatabase的62个CSV/31种元素及simlibs-atomic-metadata.json，无HTTP/TCP状态探针，无Chrome，缺库元素拒绝且不向NIST回退。解析真实成对上下能级，识别普通头/单位头/Unnamed真实列及空行，不固定跳两行；Å转nm，Aki的10^8/s转s^-1，cm^-1乘hc/e转eV。缺Aki排除并记录文件/行/原因；可用能级按(能量,g)去重用于有限分区函数。

使用U=Σg·exp(-E/Te)、I↔II Saha（Ne从cm^-3转m^-3），线面积为原子比例×态分数×g_upper/U×exp(-E_upper/Te)×Aki，不乘光子能量、不用原Intensity排名。静态原子质量和第一至第三电离能核对Royal Society of Chemistry，各元素URL/响应SHA保存在独立JSON；runtime没有下载器。[LTE/Saha教材依据](https://www.astro.uvic.ca/~tatum/stellatm/atm8.pdf)。这是光学薄、有限已知I/II能级的相对光子近似，态分数在I/II归一；max_charge过滤可用发射态，不制造缺失III。缺绝对标定、Stark系数与完整高态库，来源和UI明确覆盖局限。

仪器Gaussian FWHM=λ/R，额外高斯按平方和，洛伦兹FWHM可调，面积归一Voigt。热Doppler由发光原子/离子的平动温度T_h决定：FWHM=λ·sqrt(8k_B T_h ln2/(mc²))，[Tatum热展宽10.3](https://www.astro.uvic.ca/~tatum/stellatm/atm10.pdf)。新UI明确发送local_temperature_mode=linked，在单温度LTE假设下T_h=Te[eV]·e/k_B；这不是普遍相等的结论。manual可独立输入K，0关闭；旧无该字段的请求/配置仍按manual处理。来源记录模式、有效K和每线thermal FWHM，旧结果不重写。模板T_h[K]覆盖自动选择manual，若同时指定doppler_mode=linked则明确拒绝冲突。全部已知有效线在目标网格评估，Gaussian截断8sigma以外，Voigt/Lorentz保留跨边界翼；所有通道共用实际网格与插值。

## 批量 checkpoint 与续跑

启动前按实际Settings.line_database预检每个正含量元素：可读有效成对谱线、I/II必要能级、有限正原子质量/第一电离能及HTTPS来源/响应SHA。单次、独立组成批量、模板实际行和扫描一致；缺失/损坏返回400且不启动worker，零含量缺库元素保留。目录缺失/空库/部分损坏仍可读取params/status并显示原因；自动补全只列真正可用元素，空列表不会放行整个周期表，可用Fe不受无关元素损坏文件阻挡。

执行前保存plan.json（全部确定样本、种子、原模板、顺序/重复、实际参数、算法和库哈希）；每完成一条即原子保存checkpoint.json、CSV和样本来源。每个sample/frame拥有独立线表/HTML/官方JS/CSV诊断目录。失败/取消保留已完成样本，完整ZIP仅成功时发布，文件继承正常输出权限。

任务记录点击“续跑”创建新任务：校验计划、算法/库版本、实际参数与全部已完成文件哈希，从第一条未完成样本继续；已完成样本引用原目录，不覆盖原任务。再次失败仍保留进度，全部样本完成但打包失败时只打包。禁止带新参数/模板续跑及同任务并发续跑。服务中断时恢复终态和磁盘checkpoint，运行中任务标记中断、可手动续跑；旧无确定计划任务仅保留已有结果，不伪造重算进度。

## 在线两路径、完整节点和元素贡献

“服务器计算”使用 NIST 页面数据，在独立 Chrome 中执行官方 JavaScript Recalculate，再读取其 CSV；这是用户定义的模式名，实际 JS 执行位置明确记为浏览器。记录请求 R、初始服务器 R、官方函数返回的重算有效 R 与内存警告，以及实际加载的官方 HTML/JS 响应哈希。有效 R 不从重算前 HTML或输入框推测。隔离浏览器可沿用当前 HTTP(S)_PROXY 环境的无认证代理，未修改全局代理或 TLS 校验。官方 JS 要求 R≥100。

“客户端计算”通过 HTTP 获取 NIST 算出的 dataSticksArray，按 500 nm 核心段和 2 nm 重叠分段，每条线只归属一个核心段；先合并再用 Python 高斯核在统一目标网格合成，不使用已展宽 Doppler 数据，无需 Chrome。Ne 请求为15有效位，默认 min_rel_int=0；强度尺度和离子上限透传。每段最多3次网络重试、间隔1秒、独立有界期限，取消会阻止后续请求。正确标签的空段允许零谱，非法数字、负离子线强和非法丰度后缀拒绝。

默认 nist 核为 `exp(-(Δλ/w)^2)`、`w=λ/R`，R表示1/e半宽约定；新版 physics 的 FWHM=λ/R，通过 `render_r=2*sqrt(log(2))*请求R` 换算。客户端直接在包含两端的目标网格合成；选中本地插值时，总谱和全部离子采用同一线性变换，范围外取零，保存 raw 与实际插值 CSV。目标网格步长、物理 R 和屏幕像素数分别记录。

Web 不再做单次6000/扫描2000显示抽样，raw/interpolated 各自传递完整实际 CSV 节点，选择哪个视图就使用哪个原网格。Canvas 绘制当前视口所有实际节点，标注完整节点数和有效 R；框选放大、平移、复原保留，放大后的刻度精度随间距变化。屏幕像素有限，一屏不保证每个节点占独立像素；tooltip 读取原节点数值。实际科学数据不会做 morph/reveal 插值动画。扫描通过 `result?frame=N` 按帧加载全量，最多缓存3个完整帧，播放等待当前帧完成，切换时不通过隐藏抽样节省数据。

元素谱来自同元素各真实离子贡献之和，排除总谱、Exp/Residual 等列。默认显示总谱和元素彩色叠加，颜色按元素稳定，图例可隐藏/显示，两主题均可读；所有曲线共用当前总谱的归一化因子，tooltip 显示实际总谱及元素值。历史只有总谱时明确不提供分量。旧 `static/dynamic + mode_version=1` 请求和已有记录继续原语义，旧物理算法/参数不重写；新界面不再允许独立展宽开关组合出违背两路径定义的路线。

## 批量模拟与训练 ZIP

“批量模拟”有独立local/server/client、Te/实际Ne/R/波段/合成步长/按需插值/离子/通量/离线宽度与温度模式及组成，不读取单次草稿。插值未选时label/input隐藏并忽略旧草稿；服务器批量需明确勾选统一网格。样本与每包均1–5000整数、余数保留，B>N只一包。无模板保留组成池随机选行和均匀Te/Ne，有模板严格行优先/行内重复。裸Ne、Te为元素；参数列Te[eV]、Ne[cm^-3]、R、low_w[nm]、upper_w[nm]、grid_step[nm]、max_ion_charge、T_h[K]、doppler_mode、intensity_scale。*_at%、name/samples有效，空值/非有限/非100%拒绝，网格不一致拒绝打包。上传文件名独立省略显示且title完整，实际文件选择、替换、校验和清除保留。

成功后“下载训练数据包 ZIP”启用，重复下载复用已生成产物。每包 `Random_spectra.csv` 无表头、无索引，每条谱按完整波长行和强度行交替写两行；配对 `Random_contents.csv` 只有一行元素表头及逐样本原子百分比，不含 name/Te/Ne。第 2、3 包分别命名 `Random_spectra_2.csv` / `Random_contents_2.csv`、`_3` 等。标签按参考 28 元素顺序 Si, Al, Fe, Ca, K, Na, Mg, Cr, Cu, Mn, Zn, Ti, Ni, Mo, C, Li, Pb, Y, Eu, Lu, Er, Ho, Yb, La, Tm, Tb, Sm, Pr；未出现者填 0，H/W 等额外元素稳定追加，保留实际标签。

CSV 使用每个样本实际保存的全量 interpolated 光谱，保持统一网格；独立 `package-manifest.json` 记录文件哈希、包/样本范围、实际参数、强度尺度、Ne、NIST 来源，`source-manifest.json` 保存原完整结果清单。CSV 和 ZIP 均在现有后台 worker 中生成，只有整个任务成功完成才可下载；失败/取消不提供完整训练包。旧任务无训练包时提示重新运行，MOCK 明确为示意且不提供真实训练包。“下载完整宽表 CSV”保留现有 dataset.csv 格式。

若要配合参考训练器的50,001点配置，选择客户端计算、200–700 nm、目标网格步长0.01 nm、R=3000、min_rel_int=0、关闭本地插值。批量勾选项不会覆盖客户端目标网格。服务器 JS 批量需要显式一致插值网格；训练打包仅使用实际保存的完整谱，不补点凑数，其他网格需匹配训练器配置。

## 当前状态：已接入真实引擎

当前支持完整CSV节点、按帧扫描、真实元素贡献、三条v2计算路径、元素补全、配比余额和训练ZIP。主题图标打开五种固定页面缩略卡，每卡展示日/夜侧栏、卡片、按钮、谱线；点击、方向键、Enter/Space可选，选中状态和偏好持久化，无自定义色输入。太阳/月亮/显示器按钮打开日间/夜间/跟系统菜单，支持方向键、Esc、外点关闭，system响应系统变化，manual保持选择，Canvas同步重绘。图标为原graduation.jpg副本；GitHub SVG链接保留访问性及真实仓库地址。原三键交互保留，显示不改变物理R或原数据；参考dashboard登录前不可见，未复制其未见布局。

配比最后一项始终为100减前项和；编辑末项超额会纠正并提示，前项超额在末项归零后仅限制本次编辑前项，其他项不缩放。编辑文字保留到失焦，空/负/NaN/Inf草稿明确拒绝，不转0、不提交；新增/删除/单元素/小数按余额规则处理。API仍严格验证100%。FE/fe在失焦/提交规范为Fe，无效和重复符号阻止请求。

在线server/client和旧在线模式支持Photon flux(int_scale=2)/Energy flux(int_scale=1)，两项来自实际NIST请求，不事后乘总谱。单次/批量/扫描/模板/训练包及PNG/GIF来源保留实际尺度。local仅相对光子且隐藏NIST选择；client只读NIST dataSticksArray，用户本地库预检不应用到client。最大电荷0–2，旧energy/max3数据只读不重标。正常离线页面省去库声明/阶段长列表，错误保留具体红色预检；成功配比只显示绿色100%✓，无组成预设，后台抓取字段内部仍headless。历史未知尺度unknown，MOCK明确示意。

科学依据：[NIST LIBS输入表](https://physics.nist.gov/PhysRefData/ASD/LIBS/libs-form.html)、[官方LIBS帮助](https://physics.nist.gov/PhysRefData/ASD/Html/libshelp.html)。NIST 阈值可能省略线；完整节点显示不会再丢掉已返回的弱峰，也不会制造未返回的线。

## v1 请求与历史兼容（详见 ../NIST_GAP_ANALYSIS.md）

以下仅为保留的旧版接口语义，新界面使用上面的固定 v2 路径。已有 manifest 的参数、算法和来源不重写：

1. **计算位置**：`static`（NIST 服务器算线强，requests）/ `dynamic`（客户端计算，Selenium）。
2. **展宽位置**：旧 nist/local 组合及约定参数保留；v1 的 physics 使用历史系数，不当作新版 FWHM 校正路径。旧 static+local 无需浏览器，dynamic+local 仍沿用旧行为。
3. **本地插值**：开=CubicSpline 到指定步长（源库上界排除语义）；关=使用数据源网格。

NIST 展宽模式下自动解析响应中的实际 R（`var resolution`），与请求不符时界面徽章+任务日志警告（实测 W/Fe/Mo 200–1000 R3000 → 实际 R=85，与 Dataset 诊断一致）。本地展宽与 NIST 实际 R=1000 的 Doppler 交叉验证：峰高 1801.58 vs 1802。

- **真实后端**（默认）：`real_backend.py` 包装 `simlibs_ui` 共享计算后台——任务跑在 `simlibs_ui.jobs.JobController` 的专属 worker 子进程中（Windows Job Object、go 启动门、协作取消 + 0.8s 宽限树清理、deadline 超时清理），结果与来源证据由 `storage.save_result` 写入 `output/.jobs/<task-id>/`。
- **运行前预览**：真实引擎不提供合成谱（`/api/preview` 返回 501，防止冒充 NIST 数据）；界面以明确标注"示意预览 · 尚未运行"的本地示意图占位，运行成功后显示真实光谱。已有真实结果时，改动参数不会覆盖图谱，直到下次运行成功。
- **引擎状态**：侧边栏显示 NIST TCP 可达性探测、Python worker 版本、Chrome 版本检测（复用 `adapter.chrome_version`，不启动浏览器）。
- **MOCK 引擎**（可选）：设置环境变量 `SIMLIBS_WEB_BACKEND=mock` 切换回演示引擎（合成谱，界面带黄色 MOCK 徽章）。
- **接口契约**：`backend_api.py` —— `SimlibsBackend` 协议 + 请求模型 + 校验规则（配比 100%±1e-6、点数/帧数/单元数上限等，与 UI README 契约一致；批量 Te/Ne 范围允许 min=max=固定值，与 BatchSpec 语义一致）。

## 启动

双击 `start_web.cmd`，或：

```bat
E:\Anaconda\envs\simLIBS\python.exe -B server.py
:: 可选：--port 8517（默认，环境变量 SIMLIBS_WEB_PORT 亦可） --no-browser
:: 可选：SIMLIBS_WEB_BACKEND=mock 切换 MOCK 演示引擎
```

启动后自动打开 `http://127.0.0.1:8517/`。直接双击 `static/index.html` 会进入"离线示意模式"（黄色横幅提示，仅看外观，不能运行任务）。

启动器和 Settings 优先使用 `SIMLIBS_UI_PYTHON`，其次使用现有 E 盘环境，再兼容仍存在的旧 D 盘环境；不会安装依赖。需 Python 3.10+。

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status[?mode=local]` | 默认离线能力、0网络；明确server/client时才探测NIST状态 |
| GET | `/api/params` | 界面初始参数与默认配比（来自 `models.Parameters()` 已验证参数） |
| GET | `/api/preview?…` | 图表预览：真实引擎返回 501（前端降级为标注的本地示意） |
| POST | `/api/simulate/single` | 单次模拟 `{params, composition, title}` → `{job_id}` |
| POST | `/api/simulate/batch` | 批量 `{params, n_samples, batch_size=32, seed, te_range, ne_range, compositions}` |
| POST | `/api/templates/validate` | `{params, template_csv, repeats=1, name_column=name}` → 行数/元素/计划数，完整校验 |
| POST | `/api/jobs/{id}/resume` | 空对象；终态checkpoint创建新任务，拒绝新参数、篡改/变更版本、活动并发 |
| POST | `/api/simulate/scan` | 扫描 `{params, axis, start, end, frames, composition}` |
| GET | `/api/jobs` · `/api/jobs/{id}` | 任务列表 / 详情（含事件回放） |
| GET | `/api/jobs/{id}/events` | **SSE 事件流**（status/log/progress，含重放与心跳） |
| GET | `/api/jobs/{id}/result[?frame=N]` | 单次全量节点；批量摘要；扫描帧目录或指定帧全量数据 |
| GET | `/api/jobs/{id}/export?kind=csv\|json\|png\|gif\|dataset\|training[&frame=N]` | 导出下载：全量 CSV、manifest JSON、PNG、GIF、批量宽表、已生成训练 ZIP |
| POST | `/api/jobs/{id}/cancel` | 协作式取消 |
| GET/POST | `/api/settings` | 设置读取 / 保存 |

事件统一为 `{seq, ts, job_id, type, message, level, status, progress, final}`；`final=true` 表示终态（completed/failed/cancelled），收到后连接可关闭。校验失败返回 `400 {"error":{"code":"validation","message":…}}`。

## 语义约定（后端实际行为）

- `start_*` 立即返回 `job_id`，任务在 `simlibs_ui.worker` 专属子进程中执行；进度经 events.jsonl → SSE 推送。
- 失败/取消**不伪造成功结果**；取消保留上一次成功结果；超时/取消由 Job Object 清理整棵进程树（含 Chrome）。
- 组成总和必须 100%（容差 1e-6）；零占比保留在配置、实际请求移除；元素符号由 `models.ELEMENTS` 严格校验。
- 单谱生成上限200,000点，离子通道上限5,000,000个单元，超限明确拒绝。Web 显示当前视图全部实际节点，完整导出不减采样。扫描≤200帧、批量≤5,000样本，总谱单元上限5,000,000；服务器 JS 批量须显式统一网格，客户端已有共同合成网格。
- raw来自真实raw.csv，interpolated来自真实interpolated.csv，离子来自真实ion.csv各贡献列，各自保留波长；没有返回的raw/ion不会伪造，Sum(calc)不会冒充单离子。运行前示意曲线只用于示意，不当作科学raw/ion。
- 任务产物（request.json / events.jsonl / worker.log / result/manifest.json）保留共享后台的原目录与格式，已有历史任务继续可读取。
