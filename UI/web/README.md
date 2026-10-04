# simLIBS Web UI（前端 + 接口层）

按 `../design/DESIGN.md` 设计稿实现的可运行网页前端。项目根据组成及等离子体参数生成真实 NIST LIBS 光谱、批量训练数据和参数扫描；前端数据经 `/api/*`，任务进度经 SSE 实时推送，由 `simlibs_ui` 共享计算后台和专属 worker 执行。

## 元素选择与参数输入

输入 `f` 可从候选中点击选择 `Fe`，也支持上下键、Enter、Esc；候选使用规范大小写并排除其他行已使用的元素。可编辑最多 32 个元素，支持完整参考 28 元素组成。`fe`/`FE` 仍在失焦或提交时规范化，重复/无效元素和无效占比草稿阻止提交。

Te [eV]、实际 Ne [cm⁻³]（如 `1.23e17`）、整数 R 支持直接输入与滑块双向同步；合法数字不受滑块初始范围限制，空值、非正数、非有限数和小数 R 会提示并拒绝。Ne 默认/预设/滑块显示使用科学计数，编辑草稿保留到失焦。新界面明确发送 `mode_version=2` 和 `server/client`，固定处理路径；本地插值是显式选项，并有独立目标步长。

## 新版两路径、完整节点和元素贡献

“服务器计算”使用 NIST 页面数据，在独立 Chrome 中执行官方 JavaScript Recalculate，再读取其 CSV；这是用户定义的模式名，实际 JS 执行位置明确记为浏览器。记录请求 R、初始服务器 R、官方函数返回的重算有效 R 与内存警告，以及实际加载的官方 HTML/JS 响应哈希。有效 R 不从重算前 HTML或输入框推测。隔离浏览器可沿用当前 HTTP(S)_PROXY 环境的无认证代理，未修改全局代理或 TLS 校验。官方 JS 要求 R≥100。

“客户端计算”通过 HTTP 获取 NIST 算出的 dataSticksArray，按 500 nm 核心段和 2 nm 重叠分段，每条线只归属一个核心段；先合并再用 Python 高斯核在统一目标网格合成，不使用已展宽 Doppler 数据，无需 Chrome。Ne 请求为15有效位，默认 min_rel_int=0；强度尺度和离子上限透传。每段最多3次网络重试、间隔1秒、独立有界期限，取消会阻止后续请求。正确标签的空段允许零谱，非法数字、负离子线强和非法丰度后缀拒绝。

默认 nist 核为 `exp(-(Δλ/w)^2)`、`w=λ/R`，R表示1/e半宽约定；新版 physics 的 FWHM=λ/R，通过 `render_r=2*sqrt(log(2))*请求R` 换算。客户端直接在包含两端的目标网格合成；选中本地插值时，总谱和全部离子采用同一线性变换，范围外取零，保存 raw 与实际插值 CSV。目标网格步长、物理 R 和屏幕像素数分别记录。

Web 不再做单次6000/扫描2000显示抽样，raw/interpolated 各自传递完整实际 CSV 节点，选择哪个视图就使用哪个原网格。Canvas 绘制当前视口所有实际节点，标注完整节点数和有效 R；框选放大、平移、复原保留，放大后的刻度精度随间距变化。屏幕像素有限，一屏不保证每个节点占独立像素；tooltip 读取原节点数值。实际科学数据不会做 morph/reveal 插值动画。扫描通过 `result?frame=N` 按帧加载全量，最多缓存3个完整帧，播放等待当前帧完成，切换时不通过隐藏抽样节省数据。

元素谱来自同元素各真实离子贡献之和，排除总谱、Exp/Residual 等列。默认显示总谱和元素彩色叠加，颜色按元素稳定，图例可隐藏/显示，两主题均可读；所有曲线共用当前总谱的归一化因子，tooltip 显示实际总谱及元素值。历史只有总谱时明确不提供分量。旧 `static/dynamic + mode_version=1` 请求和已有记录继续原语义，旧物理算法/参数不重写；新界面不再允许独立展宽开关组合出违背两路径定义的路线。

## 批量模拟与训练 ZIP

使用单次页的共同参数和当前元素配比，在“批量模拟”填写样本总数与每个 batch 的光谱数（默认 32，均为 1–5000 的整数）。Te/Ne 范围允许相等以固定值生成；Ne 范围仍以 10 的指数输入。界面显示预计包数和末包数量，余数样本保留，batch_size 大于总数时只产生一包。当前入口从所填组成池随机选行并均匀采样 Te/Ne，不自动生成新的随机组成。

成功后“下载训练数据包 ZIP”启用，重复下载复用已生成产物。每包 `Random_spectra.csv` 无表头、无索引，每条谱按完整波长行和强度行交替写两行；配对 `Random_contents.csv` 只有一行元素表头及逐样本原子百分比，不含 name/Te/Ne。第 2、3 包分别命名 `Random_spectra_2.csv` / `Random_contents_2.csv`、`_3` 等。标签按参考 28 元素顺序 Si, Al, Fe, Ca, K, Na, Mg, Cr, Cu, Mn, Zn, Ti, Ni, Mo, C, Li, Pb, Y, Eu, Lu, Er, Ho, Yb, La, Tm, Tb, Sm, Pr；未出现者填 0，H/W 等额外元素稳定追加，保留实际标签。

CSV 使用每个样本实际保存的全量 interpolated 光谱，保持统一网格；独立 `package-manifest.json` 记录文件哈希、包/样本范围、实际参数、强度尺度、Ne、NIST 来源，`source-manifest.json` 保存原完整结果清单。CSV 和 ZIP 均在现有后台 worker 中生成，只有整个任务成功完成才可下载；失败/取消不提供完整训练包。旧任务无训练包时提示重新运行，MOCK 明确为示意且不提供真实训练包。“下载完整宽表 CSV”保留现有 dataset.csv 格式。

若要配合参考训练器的50,001点配置，选择客户端计算、200–700 nm、目标网格步长0.01 nm、R=3000、min_rel_int=0、关闭本地插值。批量勾选项不会覆盖客户端目标网格。服务器 JS 批量需要显式一致插值网格；训练打包仅使用实际保存的完整谱，不补点凑数，其他网格需匹配训练器配置。

## 当前状态：已接入真实引擎

当前支持完整 CSV 节点显示、按帧扫描、真实元素贡献、两条版本化计算路径，以及元素补全、配比余额和训练 ZIP。黑红/亮主题与三键交互保留，显示不改变物理 R 或原数据。

配比最后一项始终为100减前项和；编辑末项超额会纠正并提示，前项超额在末项归零后仅限制本次编辑前项，其他项不缩放。编辑文字保留到失焦，空/负/NaN/Inf草稿明确拒绝，不转0、不提交；新增/删除/单元素/小数按余额规则处理。API仍严格验证100%。FE/fe在失焦/提交规范为Fe，无效和重复符号阻止请求。

强度默认Photon flux，沿用原库 `int_scale=2`；Energy flux通过UI子类真实NIST URL `int_scale=1`，不事后乘谱、不仅换标签。单次/批量/扫描参数、JSON来源及PNG/GIF轴均保留实际尺度，以相对 `a.u.` 表示，无绝对标定承诺。选择器改变只作用于下一次运行；旧成功图/标签不会被替换，直到新结果成功。历史未知尺度明确unknown；旧已记录NIST URL可以准确识别旧photon。MOCK只合成示意，不提供真实通量转换，实际尺度unknown、另记请求尺度。

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
| GET | `/api/status` | 引擎状态（NIST TCP 探测、Chrome 检测、Python、运行中任务数） |
| GET | `/api/params` | 界面初始参数与默认配比（来自 `models.Parameters()` 已验证参数） |
| GET | `/api/preview?…` | 图表预览：真实引擎返回 501（前端降级为标注的本地示意） |
| POST | `/api/simulate/single` | 单次模拟 `{params, composition, title}` → `{job_id}` |
| POST | `/api/simulate/batch` | 批量 `{params, n_samples, batch_size=32, seed, te_range, ne_range, compositions}` |
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
