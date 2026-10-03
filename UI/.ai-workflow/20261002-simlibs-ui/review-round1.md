# simLIBS UI 独立验收

结论：**需返工**。

验收日期：2026-10-02。执行者：本轮独立 reviewer。依据：`review-handoff.md`、`D:\LIBS\herdr\coding\roles\reviewer.md`、`task.md`、`plan.md`、`reviewer-task.md`、`implementation.md`、`files.json`、`source-baseline.json`、`review-baseline.json`，以及实际实现、测试和本轮新生成的数据。

本轮重新运行的既有 **46 项 unittest 全部通过，17.121s，exit 0**；真实 static、size=2 批量、Te/Ne/R 各两帧扫描、三个 GIF、FullAccess dynamic/ion 均完成独立复验。通过这些检查仍不足以批准交付：补充检查复现了下列三项缺陷。未修改任何业务代码或既有测试，未创建 agent、pane、新终端窗口。只新增此验收文档及程序运行产生的 `output/reviewer-*` 证据；冻结业务文件仍保持原样。

## 1. 待修问题（按影响排序）

### R1 / P1：动态 CSV 缺失值被整表补零，损坏科学数据被当作成功结果

- 定位：`simlibs_ui/adapter.py:188`，`pd.read_csv(io.StringIO(csv_text)).fillna(0)`；后续 `:190` 才调用 `clean_spectrum`。
- 根因：对所有列统一补零，有限值检查看到的是替换后的零。代码注释仅许可“空白离子贡献”按零处理，实际也替换了波长、总谱和字面 `NaN`。
- 触发条件一：CSV 中 `Wavelength (nm)` 空缺，例如 `,2,2`。
- 实际结果一：真实适配层接受数据，排序后的 raw 波长为 `[0.0, 650.0, 660.0]`，强度为 `[2.0, 0.0, 0.0]`。缺失的波长被制造为 0 nm，来源仍标记为本次真实模拟。
- 触发条件二：CSV 中已有 `Sum(calc)`，中间行是 `655,2,NaN`。
- 实际结果二：raw 全部变为零强度，ion 的 H I 仍有强度 2，而 `Sum(calc)` 为 0；未报告数据获取失败。
- 影响：损坏数据可以被显示和导出为成功科学结果；存在虚构波长、错误总谱及分量/总谱矛盾。违反 plan 第 5 节非有限谱拒绝以及交接中的损坏 CSV 检查要求。
- 复现使用 mock Selenium 传输，**调用实际 `simulate`、真实源库构造及 getter**，没有修改源库/实现。两个用例都接受了数据，driver.quit 均调用一次；问题不在浏览器清理。
- 证据：`output/reviewer-independent-20261002/checks.json` 的 `missing_wavelength`、`nan_total`；本轮命令 C6，exit 0。
- 修复验收要求：缺失/非有限波长、明确 NaN/Inf 总谱必须失败；只对被确认允许为空的合法离子贡献单元作明确处理。保留当前真实 NIST 单 H I 缺 Sum 的复制规则及来源说明，不能用它掩盖损坏总谱。添加这两个负向回归用例后由原 reviewer 复查。

### R2 / P2：帧数扫描运算溢出产生 inf，却通过启动前校验

- 定位：`simlibs_ui/models.py:132`，`a + (b - a) * i / (n - 1)`；`:172` 的 `ScanSpec.validated` 没有逐帧 finite 检查；调用方 `simlibs_ui/jobs.py` 的 `start('scan', ...)` 依赖该校验。
- 触发条件：Te 或 Ne 扫描起点 `1e308`、终点 `1.7e308`、帧数 5，公共参数使用默认窄波段。
- 实际输出：`scan_values` 和 `ScanSpec.validated` 都返回 `[1e+308, 1.175e+308, 1.35e+308, inf, inf]`。起止值自身均有限，乘法中间量先溢出；后续除法无法恢复。
- 独立检查用 mock Popen 抛出 `REVIEWER_SPAWN_SENTINEL`，观察到 **Popen 被调用**，说明并未在 worker 启动前拒绝。未向 NIST 发送这些极端参数。
- 影响：违反非法/非有限/中间运算溢出参数在 worker 前拒绝的契约。该任务已可进入后台；扫描清单的非有限 values 也会与 `allow_nan=False` 的写入约束冲突。
- 证据：`output/reviewer-independent-20261002/checks.json` 的 `overflow_scan_*`；命令 C6，exit 0。
- 修复验收要求：生成扫描值时避免中间运算溢出，并逐帧检查有限性、范围及终点；无法满足时抛出可读 ValueError，断言 Popen/传输零调用。Te、Ne 帧数模式与 R 的异常转换均应复查。

### R3 / P2：950×680 下颜色/归一化及数据表分页不可访问

- 定位：`simlibs_ui/result_view.py:23` 起的固定单行 `pack(side='left')` 控制区，以及 `:46` 起数据表先占用空间、后放横向滚动条和分页按钮的 pack 顺序。
- 触发条件：实际 Tk 应用窗口设为 `950x680`（应用自定最小尺寸），载入历史光谱；打开数据表页。
- 实际结果：结果控制区宽 469 px；“颜色”按钮仅剩 16 px，“显示归一化” `winfo_ismapped=False`、尺寸 1×1；数据表“上一页”“下一页”同样 `winfo_ismapped=False`、尺寸 1×1。
- 影响：该尺寸下用户无法操作归一化，颜色按钮无法正常辨认；表格无法用分页按钮查看其他预览页。导出、取消、进度修复有效，但未覆盖结果区的这些控件。
- 证据：`output/reviewer-independent-20261002/result-950.png`、`table-950.png`、`artifact-checks.json` 的 `min_window_result_controls`、`table-pager-950.json`。截图全部由本应用 HWND 捕获；reviewer 实际看图确认。命令 C7/C9/C10，exit 0。
- 既有 `test_actions_visible_at_minimum_window_size` 检查的是批量/导出/取消/进度，不检查上述结果区控件，因此 46 项全绿并未覆盖此缺陷。
- 修复验收要求：最小窗口内结果控制区可换行或自适应，保留完整按钮和复选框；数据表预留分页空间。测试须核对实际可见尺寸与映射状态，不只验证控件存在；重新捕获最小窗口图。

## 2. 按需求和计划核对

| 验收项 | 本轮结果 | 依据与边界 |
| --- | --- | --- |
| 原需求、计划、角色约束、实现差异 | 已核对 | input_views 合并三个输入模块属文件组织变化；批量/动画用有界 GUI 适配，源码算法不改，差异有说明。未沿用 coder 通过结论。 |
| source 基线与业务冻结 | 通过 | 开始及结束重算 SHA256；源 3/3、UI 冻结清单 28/28 一致；files.json 28 项均存在且与冻结清单集合相同。C0/C11。 |
| 单次参数、配比增删编辑、100% 与主动归一化 | 常规用例通过 | 真实 Tk roundtrip、非法组成不启动、归一化仅主动按钮；读取实际输入视图代码。46 tests。 |
| 非法数值、有限性、资源限制在 worker 前拒绝 | **不通过** | 常规 NaN/Inf/95%/101%/0 Ne/负占比/重复元素/网格超限测试通过；扫描运算溢出遗漏见 R2。 |
| 真实 SimulatedLIBS 构造与插值 | 通过 | adapter 子类调用真实构造、原 CubicSpline/getter；本轮 source_file/source_sha256/NIST URL 对照及真实数据检查通过。C5/C7。 |
| static H100%、Te=1、Ne=1e17、R=1000、650–660 nm | 通过 | raw 47×2，interpolated 2000×2，均非空 finite；1500 点预览与全量 CSV 独立核对。C5。 |
| raw/interpolated/ion 视图与来源 | 正常数据通过 | static 无 ion；FullAccess dynamic raw=interpolated 的 NIST 网格明示；当前单 H I Sum 复制严格来自原捕获值。C4/C5/C7。损坏动态 CSV 不通过见 R1。 |
| 动态真实 headless、驱动匹配、退出 | 通过 | FullAccess 新运行成功；Chrome 154.0.8037.95，driver 154.0.8037.92，major.minor.build 匹配；记录 --headless=new，完整 ion 导出。C5b。 |
| 批量组成导入/名称映射/编辑/校验 | 已核对 | 真实源 data.csv 3 行、带空格 samples 的95%历史表、缺失/坏值与5000行上限测试；读取 BatchInputs；实际三页截图。 |
| size=2 真实批量、seed/schema/Te/Ne 透传 | 通过 | 本轮 2×2004 宽表；末列 H/name/Te[eV]/Ne[cm^-3]；逐样本对比谱强度、来源参数；seed和随机范围由离线测试验证。C5/C7。 |
| Te/Ne/R 各两帧实际扫描 | 常规范围通过 | 实际逐帧参数与 completed_values 对照；三个扫描曲线均有变化，见第 4 节。极端范围见 R2。 |
| 播放/暂停/逐帧不联网 | 通过 | Tk 测试以 mock jobs.start 证明播放/暂停零新任务；实际代码只换已完成帧。 |
| GIF/逐帧目录、不同网格、全零归一化 | 通过 | 三个真实 GIF 逐帧 load 成功，各两帧；目录路径重定位且 CSV存在；离线不同网格及全零 PNG/GIF 测试通过。C5/C7。 |
| CSV/PNG/JSON/目录全量与来源 | 通过（正常数据） | raw/interpolated/ion 导出与源 CSV 字节相等；PNG实际看图；JSON参数/hash/Ne/NIST URL匹配；目录不覆盖测试通过。损坏动态输入见 R1。 |
| 预览1500点、分页100行 | 数据生成通过，**交互不通过** | 历史8000行只预览1500行；程序调用切第2页能得到100行；950×680实际分页按钮不可见，见 R3。 |
| 配置/预设/恢复默认/设置 | 已核对 | JSON roundtrip/坏配置、预设参数、无联网加载测试；实际设置 HWND截图；额外检查扫描恢复到 Te 1→2/2帧/0.1步长。 |
| 历史来源与失败保留旧结果 | 通过 | smoke明示 new_simulation=false、参数未知；源历史 SHA256；失败/取消、重试、迟到消息测试及实际代码不替换旧成功谱。 |
| Tk 后台心跳与主线程响应 | 通过（测试范围） | smoke 58心跳；真实生成/导出均有心跳；未发现主线程联网、join或future.result。大CSV/科学请求/PNG/GIF在worker。 |
| 取消/关闭5秒内所属树清理、无关进程保留 | 通过（已实际测试） | 受控worker/后代/超时测试通过；另外在真实Chrome已经生成后取消1.000s、关闭1.140s，已观测所属PID全部退出，无关受控Python进程存活。C8。 |
| 真实用户其他Chrome会话不受影响 | 实现和通用进程隔离已核对；未专门开启用户会话 | 检查仅按 Job Object 清理，无按 chrome.exe 全局kill；无关受控进程已测试。本轮无已有Chrome用户会话，未操作用户浏览器会话。 |
| 任意cwd启动器与diagnose | 通过 | 两启动器从 D:\LIBS运行；Python3.10.20、10依赖、source_exists=true、network_used=false、driver_downloaded=false。C2/C3。 |
| 中文窗口、工具栏、表格、三工作页、最小布局 | 默认尺寸可用，**最小尺寸不通过** | reviewer新HWND截图实际看图，含三页/设置/绘图/表格；R3阻断颜色/归一化/分页。 |

## 3. 实际执行命令、退出码、真实输出与证据

默认 cwd=`D:\LIBS\simLIBS-2.0.3\UI`。Python 均为 `D:\Anaconda3\envs\simLIBS\python.exe`，带 `-B`，未安装任何依赖。以下 C6–C10 为 reviewer 在现有执行通道用 PowerShell here-string 经 stdin 执行的独立检查；没有新增脚本或修改业务文件。缺陷的可直接复跑脚本见第 5 节。

### C0 / C11：冻结及文件集

读取两个基线 JSON，用 `Get-FileHash -LiteralPath <基线Path> -Algorithm SHA256` 逐项比较；结束另外执行：

```powershell
@'
from pathlib import Path
import hashlib,json
b=json.loads(Path('.ai-workflow/20261002-simlibs-ui/review-baseline.json').read_text(encoding='utf-8-sig'))
s=json.loads(Path('.ai-workflow/20261002-simlibs-ui/source-baseline.json').read_text(encoding='utf-8-sig'))
f=json.loads(Path('.ai-workflow/20261002-simlibs-ui/files.json').read_text(encoding='utf-8-sig'))
assert len(f)==28 and len(b['UI'])==28
assert all((Path.cwd()/p).is_file() for p in f)
assert {str((Path.cwd()/p).resolve()) for p in f}=={str(Path(p['Path']).resolve()) for p in b['UI']}
for records in [s,b['UI']]:
    for x in records:assert hashlib.sha256(Path(x['Path']).read_bytes()).hexdigest().upper()==x['Hash']
print('FINAL_SOURCE_HASHES: 3/3 unchanged')
print('FINAL_FROZEN_UI_HASHES: 28/28 unchanged')
print('FILE_LIST: 28/28 present and identical to freeze baseline')
'@ | & 'D:\Anaconda3\envs\simLIBS\python.exe' -B -
```

exit 0，实际输出为上述三行，全部匹配。源3项实际值：

| 源文件 | SHA256 |
| --- | --- |
| simLIBS/simulation.py | 4279A121C07D88D1BEF9E6E8650B2DF77EF04A6B4CCA28B705AFC143ED2FA899 |
| simLIBS/animation.py | EEE804D29155A4130FB7CA2F2C378A38BA2653B43817B1518EDC31975E296DCC |
| simLIBS/__init__.py | EA49DBDFD082A543137ED75619C18F3AA21C2B4924AB8721D0284B4A322FB24A |

只对指定基线作一致性结论，不声称对未纳入基线的所有源目录文件作全量历史比对；无Git仓库要求，不创建Git仓库。

### C1：独立重跑46项

```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v
```

exit 0，原输出末尾：

```text
Ran 46 tests in 17.121s

OK
```

本轮逐条输出均 `ok`。覆盖 adapter 真构造+mock传输、models/storage、operations、实际 Tk app/CLI、真实受控worker/进程树。关键项包括 `test_dynamic_error_always_quits`、`test_invalid_parameters_zero_transport`、`test_actions_visible_at_minimum_window_size`、`test_window_close_cleans_running_owned_tree`、`test_tk_heartbeat_and_cancel_owned_tree_only`、`test_deadline_stops_worker_and_late_messages_ignored`、`test_failure_retains_success_and_retry`、`test_full_csv_png_and_zero_gif`、`test_bad_history_and_corrupt_json`。默认测试不执行真实NIST请求；真实请求另见 C5。

### C2 / C3：诊断及两个启动器

```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\run_ui.py' --diagnose
# 后两条执行时 cwd=D:\LIBS
cmd /c D:\LIBS\simLIBS-2.0.3\UI\start_ui.cmd --diagnose
powershell -NoProfile -ExecutionPolicy Bypass -File D:\LIBS\simLIBS-2.0.3\UI\start_ui.ps1 --diagnose
```

各诊断成功。组合启动器命令 exit 0；独立启动器退出码也由本轮 `test_windows_launchers_from_other_working_directory` 断言为0。三份输出一致：Python3.10.20，10依赖均true，`source_exists=true`，`network_used=false`，`driver_downloaded=false`。未改变系统ExecutionPolicy。

### C4：真正Tk smoke

```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B 'D:\LIBS\simLIBS-2.0.3\UI\run_ui.py' --smoke-test --output 'D:\LIBS\simLIBS-2.0.3\UI\output\reviewer-smoke-20261002'
```

exit 0：`tk_window_created=true, pages=3, new_simulation=false, heartbeats=58, elapsed=4.110000000000582, error=null`。历史来源为源库 `docs/single_simulation.csv`，SHA256=`73cb0fbe6bd677e564945d901305671ad59a9447626d2b7c24f6882ace7bf107`，parameters=null。

证据：`output/reviewer-smoke-20261002/smoke.json`、`tk-smoke.png`、`history.csv`、`history.csv.json`、`history.png`、`history.json`。截图已经 `view_image` 实际查看：三工作页、工具栏、单位、来源标记、导出/状态栏可见。本轮历史导入不是新模拟。

### C5 / C5b：真实科学流程与FullAccess补验

```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\verify_real.py' --output '.\output\reviewer-real-20261002'
# 后一条在已授权require_escalated / FullAccess执行
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\verify_real.py' --dynamic-only --output '.\output\reviewer-dynamic-fullaccess-20261002'
```

第一条 exit 1：**静态系列全部成功，最终dynamic在受限环境tab crashed**。具体异常：`WebDriverException: Message: tab crashed (Session info: chrome=154.0.8037.95)`，匹配driver154.0.8037.92。没有据此判定NIST或应用受阻，也没有把总体exit1误记为静态失败。

第二条提升执行获准，exit 0：dynamic `SUCCEEDED, elapsed=14.21900000000096, heartbeats=446, worker_exited=true`；ion导出 `SUCCEEDED, elapsed=0.7350000000005821, heartbeats=23, worker_exited=true`。无需planner协助命令，环境阻塞已经消除。

证据目录均为本轮新目录：

- `output/reviewer-real-20261002/real-validation.json`、H-raw.csv/H-interpolated.csv/H.png/H-origin.json、dataset-size2.csv、Te.gif/Ne.gif/R.gif、三个 `*-frames/manifest.json`、`.jobs/*/request.json/events.jsonl/worker.log/result/manifest.json`。
- `output/reviewer-dynamic-fullaccess-20261002/real-validation.json`、H-ion.csv/H-ion.csv.json，`.jobs/f5973f6e337d41d79e699cdf53138682/nist-dynamic.csv`、chromedriver.log、result/manifest.json。

工具报告保留原字段 `independent_acceptance=false`，因为冻结的coder工具固定如此；本review通过自行检查源代码、新执行结果、原始CSV、参数/hash/导出及额外负向检查独立作出结论，没有把该工具输出当作自我批准。

### C6：独立边界检查

命令形式：`@'<reviewer Python检查，见第5节复现脚本>'@ | & 'D:\Anaconda3\envs\simLIBS\python.exe' -B -`。实际扩展检查同时创建950×680的single/batch/scan及settings HWND截图，并将输出写入 `output/reviewer-independent-20261002/checks.json`。exit 0。

原输出关键值：

```text
overflow_scan_values = ['1e+308', '1.175e+308', '1.35e+308', 'inf', 'inf']
overflow_scan_validated = 同上
overflow_scan_start_exception = REVIEWER_SPAWN_SENTINEL
overflow_scan_Popen_called = true
missing_wavelength.accepted = true
missing_wavelength.raw.wavelength = [0.0, 650.0, 660.0]
missing_wavelength.raw.intensity = [2.0, 0.0, 0.0]
nan_total.accepted = true
nan_total.raw.intensity = [0.0, 0.0, 0.0]
nan_total.ion.H I = [0.0, 2.0, 0.0]
nan_total.ion.Sum(calc) = [0.0, 0.0, 0.0]
restore_default_scan = Te / start1 / stop2 / count2 / step0.1
```

早期仅验证scan/恢复默认的stdin探针 exit 1：因为探针在 `app.close(); root.update()` 已销毁窗口后再次 `root.destroy()`，产生 reviewer 自身的重复销毁 TclError。扫描问题此前已输出；后续 C6/C7 改为取消timer后直接destroy，exit0，复现结果一致。该探针错误未列为业务缺陷，恢复默认也没有发现缺陷。

### C7：独立导出/科学来源检查与结果区几何

命令：reviewer here-string 经同一 `python.exe -B -` 执行（exit 0），读取 C5/C5b 中本轮新 manifest、CSV、GIF 和原NIST capture，使用独立断言：

- 10份单谱/样本/扫描帧 source_sha256与实际源文件一致，输入Ne按源3位有效数字计算后等于 actual_Ne，NIST URL eden等于actual_Ne。
- 每份文件行数=counts，预览≤1500，全部finite；static网格逐点等于 `round(arange(low_w, upper_w, .005),8)`。
- 两样本宽表强度=各自完整谱，宽表Ne=对应输入Ne；每帧参数=扫描值。
- 导出raw/interpolated/ion与各任务原CSV字节相等；原动态capture只有Wavelength/H I，H I原值和返回H I/Sum逐值相等。
- 三个GIF均逐帧seek/load，n_frames=2；导出目录重定位后的每个manifest/CSV都存在。

实际输出：`export_bytes_equal=true, gif_all_frames_loaded=true, dynamic_original_single_ion_preserved=true`；所有artifact_checks passed；同时输出R3的控件几何。

证据：`output/reviewer-independent-20261002/artifact-checks.json`、`result-950.png`。完整H.png另经view_image查看，标题、单位、图例和曲线可读。

### C8：真实Chrome已启动后的取消和关闭

已授权require_escalated执行reviewer stdin Python检查，exit 0。用Windows `CreateToolhelp32Snapshot/Process32FirstW/Process32NextW` 只读枚举父子PID；启动实际Application的dynamic worker，等到其所属树中出现Chrome后分别调用 `app.jobs.cancel()` 和 `app.close()`；轮询≤5s；用进程退出码检查各已观测PID。另启动受控无关Python sleep进程，在两次任务结束后检查其仍活着，最后只清理该受控进程。

原输出：

| 操作 | 已观测所属PID | 用时 | state | 所属存活 | 无关PID20044 |
| --- | --- | --- | --- | --- | --- |
| cancel | worker15744、driver24540、Chrome1720/24932、conhost27444 | 1.000s | CANCELLED | [] | alive=true |
| close | worker8032、driver12480、Chrome24888、conhost26680 | 1.140s | CANCELLED | [] | alive=true |

均 `worker_exited=true`，证据：`output/reviewer-independent-20261002/real-chrome-lifecycle.json`。未使用按进程名终止的命令。

最后只读查询：

```powershell
$p = @(Get-Process -Name chrome,chromedriver -ErrorAction SilentlyContinue)
Write-Output ('Chrome/ChromeDriver remaining count=' + $p.Count)
```

exit0，`Chrome/ChromeDriver remaining count=0`。

### C9 / C10：实际表格页及分页可见性

两条reviewer here-string 经 `python.exe -B -` 执行，均exit0。实际Application载入本轮history.json，950×680，选择数据表；程序调用change_page(1)，然后查看实际分页按钮映射状态。

原输出：`table_page=预览第 2/15 页；每页 100 行, displayed_rows=100, first_row=['253.3','63180.728']`；随后 `上一页 mapped=false size=[1,1]`、`下一页 mapped=false size=[1,1]`。

证据：`output/reviewer-independent-20261002/table-check.json`、`table-pager-950.json`、`table-950.png`（已看图）。程序能够翻页不等于用户能操作不可见按钮。

## 4. 真实运行的关键数字

这些是本轮观测值，不是未来NIST结果必须逐值匹配的硬编码断言。

| 项目 | 数据及参数 | 用时 / 心跳 |
| --- | --- | --- |
| H static | raw47×2 / interpolated2000×2，finite，max1802，输入与actualNe一致 | 3.750s / 110 |
| size2 batch | 2×2004，2次真实调用；末列H/name/Te[eV]/Ne[cm^-3] | 4.812s / 151 |
| Te scan | 1→1.2，两帧；对应参数一致，最大帧差6437 | 4.422s / 139 |
| Ne scan | 1e17→1.2e17，两帧；actualNe分别1e17/1.2e17，最大帧差10.166544120000026 | 4.046s / 128 |
| R scan | 1000→1200，两帧；最大帧差360 | 5.828s / 185 |
| Te/Ne/R GIF | 均2帧，全部逐帧解码成功 | 分别1.563/1.562/1.547s，各50心跳 |
| H dynamic FullAccess | raw49×2、interpolated49×2、ion49×3；H I和Sum均来自原H I；--headless=new | 14.219s / 446 |
| ion CSV export | 与完整结果ion.csv字节相等，含来源旁文件 | 0.735s / 23 |

每个成功任务的 `worker_exited=true`。static默认插值和dynamic默认NIST网格区分正确。未把H I单离子复制解释为伪造H II/H III。

## 5. 三个问题的直接复验命令（不改业务文件、不联网）

cwd=UI。原coder可复制以下三个脚本；修复后应将相应观测改成拒绝/有限/可见，并补自动回归测试。脚本为reviewer已执行检查的最小重现版本。

### R1

```powershell
@'
import sys
sys.stdout.reconfigure(encoding='utf-8')
from dataclasses import replace
from unittest.mock import Mock,patch
from simlibs_ui.adapter import simulate,source_module
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings
module=source_module(Settings().source)
for csv in [
 'Wavelength (nm),H I,Sum(calc)\n650,0,0\n,2,2\n660,0,0\n',
 'Wavelength (nm),H I,Sum(calc)\n650,0,0\n655,2,NaN\n660,0,0\n']:
    driver=Mock()
    driver.window_handles=['main','csv']
    driver.page_source='<html><pre>'+csv+'</pre></html>'
    driver.find_element.return_value.is_displayed.return_value=True
    driver.find_element.return_value.is_enabled.return_value=True
    with patch('simlibs_ui.adapter.resolve_driver',return_value=('fake.exe','154.0.8037.92')), patch.object(module.webdriver,'Chrome',return_value=driver):
        try:
            frames,origin=simulate(replace(Parameters(),webscraping='dynamic'),Settings())
            print('ACCEPTED',frames['raw'].to_dict('list'),frames['ion'].to_dict('list'))
        except Exception as exc:
            print('REJECTED',str(exc))
    print('quit_count',driver.quit.call_count)
'@ | & 'D:\Anaconda3\envs\simLIBS\python.exe' -B -
```

### R2

```powershell
@'
from dataclasses import asdict,replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from simlibs_ui.models import Parameters,ScanSpec
from simlibs_ui.jobs import JobController
from simlibs_ui.settings import Settings
spec=ScanSpec(axis='Te',start=1e308,stop=1.7e308,count=5)
print('validated',spec.validated(Parameters()))
with TemporaryDirectory(dir=str(Path.cwd()/'output')) as out:
    job=JobController(replace(Settings(),output=out))
    with patch('simlibs_ui.jobs.subprocess.Popen',side_effect=RuntimeError('REVIEWER_SPAWN_SENTINEL')) as spawn:
        try:job.start('scan',parameters=Parameters().to_dict(),spec=asdict(spec))
        except Exception as exc:print(type(exc).__name__,str(exc))
        print('Popen_called',spawn.called)
'@ | & 'D:\Anaconda3\envs\simLIBS\python.exe' -B -
```

### R3

```powershell
@'
import sys
sys.stdout.reconfigure(encoding='utf-8')
import tkinter as tk
from pathlib import Path
from simlibs_ui.app import Application
root=tk.Tk();app=Application(root)
app.display_result(Path('output/reviewer-smoke-20261002/history.json').resolve())
root.geometry('950x680');root.update()
for frame in app.result.winfo_children():
    for w in frame.winfo_children():
        if w.winfo_class() in ('TButton','TCheckbutton'):
            print(w.cget('text'),'mapped',w.winfo_ismapped(),'width',w.winfo_width(),'requested',w.winfo_reqwidth())
notebook=next(w for w in app.result.winfo_children() if w.winfo_class()=='TNotebook')
notebook.select(1);root.update()
table=root.nametowidget(notebook.tabs()[1])
for frame in table.winfo_children():
    for w in frame.winfo_children():
        if w.winfo_class()=='TButton':print(w.cget('text'),'mapped',w.winfo_ismapped(),'size',w.winfo_width(),w.winfo_height())
for timer in root.tk.call('after','info'):root.after_cancel(timer)
app.jobs.force_close();root.destroy()
'@ | & 'D:\Anaconda3\envs\simLIBS\python.exe' -B -
```

## 6. 未验证范围、复查与移交

- 本轮真实联网重点按交接指定H窄波段：未另做W/Fe/Mo真实dynamic、多离子大范围、200帧/500万单元压力运行。参数/schema/不同网格/零谱/限制以实际读取代码和本轮离线测试验证；不声称穷尽所有外部NIST组合。
- 未开启或操作真实用户的其他Chrome会话。按Job Object所有权及实际无关受控进程保留证明清理隔离；真实所属Chrome的取消/关闭已亲测。没有用“没有残留”替代取消/关闭时限测试。
- 未来网络/页面/Chrome版本仍可能变化；本轮已实际消除sandbox动态阻塞，无待planner代执行的必要命令。不能把旧受限失败写成外部不可用。
- 无exe打包、安装新依赖、Git初始化/提交/合并要求；未执行这些范围外操作。
- 原coder应修复R1/R2/R3并补回归；特别复查损坏动态CSV的错误状态/旧成功结果保留、扫描Popen零调用、最小窗口绘图和分页可访问。冻结基线在修复后由planner更新，再交原reviewer复查。正常静态/批量/扫描科学证据本轮已齐全，修复未影响适配层时无需反复全量联网；R1应至少补动态针对性复验。

**移交：本轮验收完成，结论为需返工。停止业务及验收执行，交本planner协调原coder修复，再由原reviewer复查；本review不自行修复。**
