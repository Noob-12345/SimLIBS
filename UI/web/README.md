# simLIBS Web UI（前端 + 接口层）

按 `../design/DESIGN.md` 设计稿实现的可运行网页前端。**未改动 UI 目录任何现有程序文件**；前端数据全部经 `/api/*`，任务进度经 SSE 实时推送。

## 当前状态：已接入真实引擎

本轮五项改进：完整CSV保峰显示（单次6000/扫描2000预算）、可滚动响应主页、Fe等合法大小写、末元素自动100%余额、真实NIST相对Photon/Energy尺度。黑红/亮主题、RAF动效和左键框选/中键平移/右键复原保留。

配比最后一项始终为100减前项和；编辑末项超额会纠正并提示，前项超额在末项归零后仅限制本次编辑前项，其他项不缩放。编辑文字保留到失焦，空/负/NaN/Inf草稿明确拒绝，不转0、不提交；新增/删除/单元素/小数按余额规则处理。API仍严格验证100%。FE/fe在失焦/提交规范为Fe，无效和重复符号阻止请求。

强度默认Photon flux，沿用原库 `int_scale=2`；Energy flux通过UI子类真实NIST URL `int_scale=1`，不事后乘谱、不仅换标签。单次/批量/扫描参数、JSON来源及PNG/GIF轴均保留实际尺度，以相对 `a.u.` 表示，无绝对标定承诺。选择器改变只作用于下一次运行；旧成功图/标签不会被替换，直到新结果成功。历史未知尺度明确unknown；旧已记录NIST URL可以准确识别旧photon。MOCK只合成示意，不提供真实通量转换，实际尺度unknown、另记请求尺度。

科学依据：[NIST LIBS输入表](https://physics.nist.gov/PhysRefData/ASD/LIBS/libs-form.html)、[官方LIBS帮助的强度尺度说明](https://physics.nist.gov/PhysRefData/ASD/Html/libshelp.html)。NIST本身的最小相对谱线强度选项可能在服务端省略线；本UI抽样不会进一步丢掉已返回的弱峰，也不制造未返回的线。

## 数据抓取模式（2026-10-03 重塑，详见 ../NIST_GAP_ANALYSIS.md 第六节）

三个正交决策，全部写入 manifest 来源证据（`computation_location / broadening / broadening_params / actual_resolution / line_table`）：

1. **计算位置**：`static`（NIST 服务器算线强，requests）/ `dynamic`（客户端计算，Selenium）。
2. **展宽位置**：`nist`（服务端 dataDopplerArray / 页面 CSV）⇄ `local`（解析 `dataSticksArray` 未展宽线表，本地按官方 saha_lte.js 约定展宽；实现移植自已验证的 `Cross_attention/Dataset/nist_reconstruction.py`，单测 `tests/test_nist_recon.py` 9 项）。本地展宽参数：高斯约定（nist：w=λ/R 1/e 半宽 / physics：FWHM=λ/R）、合成网格步长、线中心舍入、min_rel_int；自动提供逐离子曲线与谱线存档 `line_table.csv`，static+local 无需浏览器。
3. **本地插值**：开=CubicSpline 到指定步长（源库上界排除语义）；关=使用数据源网格。

NIST 展宽模式下自动解析响应中的实际 R（`var resolution`），与请求不符时界面徽章+任务日志警告（实测 W/Fe/Mo 200–1000 R3000 → 实际 R=85，与 Dataset 诊断一致）。本地展宽与 NIST 实际 R=1000 的 Doppler 交叉验证：峰高 1801.58 vs 1802。

- **真实后端**（默认）：`real_backend.py` 包装现有 `simlibs_ui` 包——任务跑在 `simlibs_ui.jobs.JobController` 的专属 worker 子进程中（Windows Job Object、go 启动门、协作取消 + 0.8s 宽限树清理、deadline 超时清理全部复用），结果与来源证据由 `storage.save_result` 写入 `output/.jobs/<task-id>/`，**与 Tk 桌面版完全同源**。
- **运行前预览**：真实引擎不提供合成谱（`/api/preview` 返回 501，防止冒充 NIST 数据）；界面以明确标注"示意预览 · 尚未运行"的本地示意图占位，运行成功后显示真实光谱。已有真实结果时，改动参数不会覆盖图谱（与桌面版"保留上一成功图谱"语义一致），直到下次运行。
- **引擎状态**：侧边栏显示 NIST TCP 可达性探测、Python worker 版本、Chrome 版本检测（复用 `adapter.chrome_version`，不启动浏览器）。
- **MOCK 引擎**（可选）：设置环境变量 `SIMLIBS_WEB_BACKEND=mock` 切换回演示引擎（合成谱，界面带黄色 MOCK 徽章）。
- **接口契约**：`backend_api.py` —— `SimlibsBackend` 协议 + 请求模型 + 校验规则（配比 100%±1e-6、点数/帧数/单元数上限等，与 UI README 契约一致；批量 Te/Ne 范围允许 min=max=固定值，与 BatchSpec 语义一致）。

## 启动

双击 `start_web.cmd`，或：

```bat
D:\Anaconda3\envs\simLIBS\python.exe -B server.py
:: 可选：--port 8517（默认，环境变量 SIMLIBS_WEB_PORT 亦可） --no-browser
:: 可选：SIMLIBS_WEB_BACKEND=mock 切换 MOCK 演示引擎
```

启动后自动打开 `http://127.0.0.1:8517/`。直接双击 `static/index.html` 会进入"离线示意模式"（黄色横幅提示，仅看外观，不能运行任务）。

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 引擎状态（NIST TCP 探测、Chrome 检测、Python、运行中任务数） |
| GET | `/api/params` | 界面初始参数与默认配比（来自 `models.Parameters()` 已验证参数） |
| GET | `/api/preview?…` | 图表预览：真实引擎返回 501（前端降级为标注的本地示意） |
| POST | `/api/simulate/single` | 单次模拟 `{params, composition, title}` → `{job_id}` |
| POST | `/api/simulate/batch` | 批量 `{params, n_samples, seed, te_range, ne_range, compositions}` |
| POST | `/api/simulate/scan` | 扫描 `{params, axis, start, end, frames, composition}` |
| GET | `/api/jobs` · `/api/jobs/{id}` | 任务列表 / 详情（含事件回放） |
| GET | `/api/jobs/{id}/events` | **SSE 事件流**（status/log/progress，含重放与心跳） |
| GET | `/api/jobs/{id}/result` | 结果（单次：谱数据；批量：样本+宽表；扫描：帧序列） |
| GET | `/api/jobs/{id}/export?kind=csv\|json\|png\|gif\|dataset[&frame=N]` | 导出下载（复用 `operations.export_result`：全量 CSV、manifest JSON、matplotlib PNG、Pillow GIF、批量数据集） |
| POST | `/api/jobs/{id}/cancel` | 协作式取消 |
| GET/POST | `/api/settings` | 设置读取 / 保存 |

事件统一为 `{seq, ts, job_id, type, message, level, status, progress, final}`；`final=true` 表示终态（completed/failed/cancelled），收到后连接可关闭。校验失败返回 `400 {"error":{"code":"validation","message":…}}`。

## 语义约定（后端实际行为）

- `start_*` 立即返回 `job_id`，任务在 `simlibs_ui.worker` 专属子进程中执行；进度经 events.jsonl → SSE 推送。
- 失败/取消**不伪造成功结果**；取消保留上一次成功结果；超时/取消由 Job Object 清理整棵进程树（含 Chrome）。
- 组成总和必须 100%（容差 1e-6）；零占比保留在配置、实际请求移除；元素符号由 `models.ELEMENTS` 严格校验。
- 单谱 ≤200,000 点；Web从完整CSV读取，单次显示预算6,000、扫描每帧2,000原点，优先保留各序列峰谷/相邻点/端点，不插值补点、不舍入弱强度；数据不足原样显示。极端峰谷数量超过预算会明确要求缩小波段，避免静默丢弱峰。Tk原有1,500预览不变，完整导出不减采样。扫描 ≤200 帧且 R 轴取整后不得重复；批量 ≤5,000 样本 / 5,000,000 光谱单元；dynamic 批量必须统一重采样。
- raw来自真实raw.csv，interpolated来自真实interpolated.csv，离子来自真实ion.csv各贡献列，各自保留波长；没有返回的raw/ion不会伪造，Sum(calc)不会冒充单离子。运行前示意曲线只用于示意，不当作科学raw/ion。
- 任务产物（request.json / events.jsonl / worker.log / result/manifest.json）与 Tk 桌面版同目录同格式，可互相查看。
