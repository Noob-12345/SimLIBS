# simLIBS 桌面 UI 交付完成

日期：2026-10-02；协调者：既有 Herdr libs_planner（simlibs-ui / w1:t1 / w1:p1）。
最终结论：整个约定范围已实现，原 reviewer 第二轮独立复验通过，R1/R2/R3 全部关闭，无待修问题或未解决外部阻碍。

## 应用与启动

目标：D:\LIBS\simLIBS-2.0.3\UI；源库：同级 simLIBS-2.0.3。
使用既有 D:\Anaconda3\envs\simLIBS 环境（Python 3.10.20）、tkinter/ttk、Matplotlib，不安装新 Python 依赖或 ImageMagick。

交付启动已实际执行，无额外终端窗口：

```powershell
& 'D:\Anaconda3\envs\simLIBS\pythonw.exe' -B 'D:\LIBS\simLIBS-2.0.3\UI\run_ui.py'
```

实际启动由 Start-Process 使用相同参数；2026-10-02 18:51 核对 PID=10340、HWND=17893510、窗口标题“simLIBS 光谱模拟工作台”、Responding=True、stderr 空。保持该应用运行供用户操作；启动本身不自动请求 NIST。证据 delivery-launch.json、delivery-stdout.log、delivery-stderr.log。
以后也可在现有终端运行 start_ui.cmd，或按 README 使用 start_ui.ps1；两启动器从其他 cwd 运行诊断已独立验证。需要新模拟时使用默认 H 窄波段预设并点击“生成单次真实光谱”。

## 实际功能

- 单次 static/dynamic；Te、Ne、R、波长上下界、最大电荷、headless、可选重采样；元素配比增删编辑、CSV导入和主动归一化。
- raw/interpolated/ion 视图、嵌入图与工具栏、标题/颜色/显示归一化、分页预览；static 无 ion 时说明原因。
- 批量组成编辑/名称映射、随机种子、Te/Ne范围、有界逐样本生成、宽表及逐样本结果。
- Te/Ne/R 参数扫描、帧数或步长、预览生成值、播放/暂停/逐帧、逐帧目录与 Pillow GIF。
- 预设、JSON配置/设置、恢复默认；离线打开已有CSV/历史样例并明示来源与参数未知。
- 完整 CSV（raw/interpolated/ion/dataset）、PNG、来源JSON、完整结果目录、GIF导出。
- 网络/浏览器/重I/O在后台子进程；输入校验、进度、超时、取消、关闭、所属树清理、旧成功结果保留和失败重试。

## 三角色实际交接与返工

沿用原三个 pane 和 Codex 会话，没有创建新 agent/pane/worktree/终端窗口。接管确认见 handoff-ack.md。
原 coder 首版完成后停止；冻结28文件交原 reviewer，首轮独立验收发现3项缺陷并给出“需返工”。原报告 review-round1.md 与原基线保留。
planner核对代码及复现后，通过 rework-task.md交原coder分3小步修复：R1 adapter/storage两业务文件，R2 models一文件，R3 result_view一文件；新增回归及一个离线测试worker。每步均先复现失败再实现，没有任何一步超过3业务文件。
原coder返工完成并停止，清单更新29项；重新冻结 review-baseline-round2.json，交原reviewer独立复验。最新 review.md为“通过”，三项缺陷关闭；不以coder或协调者结论替代独立验收。

## 验证证据

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 协调者返工后新鲜完整unittest | 57 tests，23.298s，OK，exit0 | 本pane实际命令输出；第二轮冻结记录 |
| 原reviewer第二轮完整unittest | 57 tests，23.007s，OK，exit0 | review.md |
| R1科学数据 | 22负向拒绝、2合法稀疏/单离子通过；实际worker失败无成功manifest/保留旧结果/quit1 | output/reviewer-round2-independent/r1-checks.json |
| R2扫描校验 | 三轴大有限范围完整finite；27非法派生/精度不足用例零Popen/零请求 | 同目录r2-checks.json |
| R3最小窗口 | 950×680颜色/归一化/标题/分页可见且实际invoke成功，所有祖先边界满足 | 同目录r3-checks.json、plot-950.png、table-950.png |
| 独立真实Tk smoke | 三页、3.922s/61心跳、历史来源明确、后台CSV/PNG/JSON、自动关闭 | output/reviewer-round2-smoke/smoke.json及HWND截图 |
| 独立H静态 | 47×2 raw、2000×2 interpolated；finite、参数/源hash/URL相符 | output/reviewer-real-20261002/real-validation.json |
| 独立size2批量 | 2×2004宽表、逐样本来源/强度核对通过 | 同目录dataset-size2.csv及来源 |
| 独立Te/Ne/R各2帧及GIF | 三类真实请求和参数/曲线变化确认，GIF逐帧解码通过 | 同目录三个GIF及*-frames |
| 修复后独立真实dynamic/ion | 13.125s/419心跳；raw/interpolated49×2、ion49×3；导出0.672s，原H I逐值/导出逐字节一致，worker退出 | output/reviewer-round2-dynamic/real-validation.json、H-ion.csv及来源 |
| 真实Chrome已启动后取消/关闭 | 1.000s/1.140s，所属进程全部退出，无关受控进程存活 | output/reviewer-independent-20261002/real-chrome-lifecycle.json |
| 任意cwd启动/诊断 | 两启动器通过，3.10.20、10依赖存在、不联网、不下载驱动 | review-round1.md C2/C3；既有CLI测试本轮继续通过 |
| 最后交付校验 | UI29/29与新冻结一致；源3/3与原基线一致；应用窗口正在响应 | 本pane最后只读哈希/进程检查、delivery-launch.json |

首轮全量科学流程已由原reviewer独立复验；本轮针对修过的动态路径及正常范围扫描回归，未无理由重复全量NIST。所有数字为实际观测，不要求未来数据库结果逐值相同。

## 保留边界

新模拟依赖NIST网络/页面和动态Chrome/匹配驱动；现有版本已真实验证。离线历史查看与配置/导出始终标明来源，不作为新模拟。keep_browser_open/detach固定False，浏览器纳入任务所有权。
预览最多1500等距点、表格每页100行，可能漏窄峰；完整CSV/PNG/GIF读取全量。默认资源上限单谱200000点、批量/扫描5000000单元、200帧。
真实联网验收覆盖H窄波段及小批量/两帧扫描；未穷尽多元素dynamic组合或上限压力运行，未开启用户其他Chrome会话。进程隔离有真实所属Chrome及无关受控进程检查。
源库3个关键Python文件SHA256保持原样，所有业务增量在UI；没有exe打包、Git初始化/提交/合并或其他范围外操作。

当前任务已交付。完整使用说明 README.md；实现记录 implementation.md；最新独立验收 review.md；初始计划 plan.md；历史首轮 review-round1.md；本文件为最终交付状态。
