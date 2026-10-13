# SimLIBS Vue 项目协作约定

2026-10-13最新 `.ai-workflow/20261013-revert-parameter-height/` 已完成，见state/review。用户明确要求完整回退“左侧参数区过长”对应的高度方案及全部配套，本指令撤销sidebar-height第二项：三页恢复自然长高／整页滚动／controls末尾生成按钮，内部scroll／限高／sticky／footer和定位helper撤销；七组件／页面与核实的fffe3cd高度前修订一致，工作台样式匹配前快照，README仅删相关段。日间导航与后续独立设置预览／sticky保存栏／Jobs统一筛选保留，Settings／Jobs源hash不动，仅Jobs局部对齐旧相对菜单。原plan/code、每步最多三业务文件、dist-desktop根目录交付保持；code四组与Windows EXE/中文NSIS，plan七项实际release、37保护／参考hash及恢复／冻结核对通过。最终根目录EXE为ba0f0b98版；源码／产物冻结，不自动恢复已撤销高度方案，不恢复旧原生I/O任务。历史完成记录仅代表当时事实。

2026-10-12最新 `.ai-workflow/20261012-desktop-front-refine/` 已完成，state.json/review.md为最终状态。用户选择继续桌面前端，本轮三项：设置日间缩略导航与实际主题一致、sticky可见保存／放弃操作条并避开聚焦字段与解释、Jobs类型／状态统一ChoiceSelect。原三明暗模式及图标完整保留，只改三个指定业务文件；code五组自查／根目录Windows EXE与中文NSIS完成，plan七项实际release、43项保护／参考与三冻结源hash通过。正式根目录EXE最终460ec188版，无新版交付子目录；沿用原plan/code、每步最多三业务文件。源码／产物冻结，旧原生I/O任务不恢复，未接真实引擎。

2026-10-12最新任务 `.ai-workflow/20261012-sidebar-height/` 已完成，最终状态与独立验收见state.json/review.md。日间完整左侧导航随日夜／五配色；用户明确确认三页参数面板内滚动、窗口限高／sticky与固定底部生成按钮，模式／高级不折叠，弹层不裁切。原plan/code、每步最多3业务文件与dist-desktop根目录交付保持。首版的箭头过渡重叠及实际EXE首次scroll footer下移8px已返工；code完成业务修正／自查后遇服务capacity，plan仅完成最终构建／独立验收，不写业务源码。最终8bfd144版根目录EXE／中文NSIS已更新，16项实际release、24项保护及10项冻结hash通过；本任务plan-ready/review为最终交付依据，旧code-ready首版4f71已被替代。源码和产物冻结，旧原生I/O任务不恢复。

项目根目录：`D:\LIBS\SimLIBS\Vue`。技术栈：Tauri 2、Vue 3、TypeScript、Vite、npm。

## 两角色工作流

- plan 负责需求、方案、验收标准、协调和最终验收，不替代 code 编写业务代码。
- code 负责实现和自测，完成后提交 `implementation.md`，由 plan 核对实际代码、执行必要验收并写 `review.md`。
- 顺序为用户需求 → plan 方案 → code 实现与自测 → plan 验收。返工交回同一 code，再由 plan 复验；不新增独立 review 角色。
- 官方模板首次生成属于本次已授权的初始化操作。后续每个业务实现小步最多修改 3 个业务文件，验证与改动风险相称。

初始化材料位于 `.ai-workflow/20261009-tauri-vue-init/`，详细角色和交接规则见其中 `workflow.md`。历史材料仅供参考，不自动恢复旧任务。

最新前端与角色状态见 `.ai-workflow/20261009-vue-frontend/state.json`、`review.md`；此前续接见 `.ai-workflow/20261009-herdr-resume/`，工具链验收见 `.ai-workflow/20261009-tauri-prerequisites/review.md`。已经通过的安装和构建不重复执行，后续操作前核对实时 Herdr 角色和任务范围。

当前 Windows 桌面前端交付见 `.ai-workflow/20261010-desktop-delivery/state.json`、`review.md`。产品入口为 `dist-desktop/SimLIBS.exe` 与中文 NSIS 安装包；Vue 嵌入 Tauri 窗口，网页仅作开发辅助。独立 release 验收通过；完整原生文件对话框点击及安装过程的验证边界按 review.md 如实保留。

最新八项桌面界面调整于2026-10-11完成，状态及独立验收见 `.ai-workflow/20261010-desktop-polish/state.json`、`review.md`。新版 EXE / NSIS 已更新到同一 `dist-desktop/`；太阳/月亮图标、中键平移/右键全谱、侧栏分组与右侧完成100%绿色进度已通过定向及实际release检查。原 plan/code pane 不变，保持已验证的业务源码与产物，等待用户新需求。

最新主题菜单/紧凑参数/文字体系调整见 `.ai-workflow/20261011-desktop-layout-type/state.json`、review.md：顶栏单入口选择日间/夜间/跟随系统，模式/高级选项常驻，五页字体与文案统一，新版桌面产物已更新。code用量限制后的验证脚本修正、构建与独立验收由plan完成，未代写业务源码；交接事实以该review为准。`.ai-workflow/20261011-desktop-file-qa/`因用户Esc停止电脑操作而暂停，本轮未恢复原生文件对话框验收。

最新主题配色与启动动画见 `.ai-workflow/20261011-theme-startup/state.json`、`review.md`，两项需求已完成，原 plan/code pane 不变。五种配色与实际EXE启动先载入后主页通过独立release验收。**本轮新版入口为 `dist-desktop/20261011-theme-startup/SimLIBS.exe`，安装包位于同一版本目录**；根目录旧EXE因用户正在运行而保留，不关闭、不覆盖。原文件对话框任务仍暂停，后续不得将旧根目录产物或该暂停任务误判为本轮交付。

2026-10-12用户明确要求后续正式产物**直接更新 `D:/LIBS/SimLIBS/Vue/dist-desktop/` 根目录，禁止另交版本子目录**。此指令覆盖此前主题动画任务的版本目录交付约定，历史记录仅表示当时事实。当前任务 `.ai-workflow/20261012-compact-controls/`：独立配色按钮、紧凑三参数、处理方式逐项悬浮说明及指定文字删除；用户续加单次成功100%后动画收起参数/边缘展开与右上角GitHub仓库入口，本轮共10项。允许为固定仓库URL新增精确opener权限，其余数据/Rust/依赖不变。保留原plan/code两角色，不关闭用户软件；不恢复旧文件对话框任务。

最新任务 `.ai-workflow/20261012-edge-focus-lines/` 五项已完成，状态及独立验收见state.json/review.md：视口居中的面板侧缘收起/展开按钮、删除指定长完成段落、下拉聚焦高亮与光谱实线。plan 19项实际release检查、22项保护哈希通过，正式EXE/中文NSIS已直接更新dist-desktop根目录。基于已完成controls-unify，保留最新统一控件、无滑条及原生标题栏主题。用户本次明确要求删除完成长段落，workbench.ts唯一差异为该detail文案；其余数据/任务/进度/I/O/权限/依赖保持。原plan/code与固定根目录交付约定不变，源码和产物冻结，旧I/O任务仍暂停。

最新 `.ai-workflow/20261012-welcome-theme-cards/` 七项已完成，状态及独立验收见state.json/review.md：高级开关说明、本机时间启动问候、主题模糊过渡、单次三横排方形输入卡，以及收起左/展开右、2.5加粗且完全不叠面板的侧缘按钮。原编号1/2/3/4/5/6/8。plan完整21项实际release和27项保护哈希通过，根目录EXE/中文NSIS已更新。基于edge-focus-lines保留实线/删除文案/下拉高亮/居中滚动；模型/任务/I/O/Rust/权限/依赖不变，存储/原生主题串行和数据边界保持。原plan/code和固定根目录交付不变，源码/产物冻结，旧I/O任务仍暂停。

最新 `.ai-workflow/20261012-output-validation-layout/` 十项已完成，状态及独立验收见state.json/review.md：单次数值居中/标题单位、默认Vue/outputs及设置、三等大摘要卡、删计时字/ready后额外1s、批量尾单位/展宽对齐、字段红色抖动及活动提示、同排随机开关/CSV红清除绿文件名。plan完整18项实际release与18项保护哈希通过，根目录EXE/中文NSIS已更新，outputs已创建并native读回；CSV post-import是实际File/控制器证据，原生I/O完整验收仍暂停。只新增main固定默认目录命令，不接路径参数/新依赖/通配权限，核心生成/校验/随机/扫描保持。原plan/code、每步最多3业务文件和固定根目录交付不变，源码/产物冻结。

## 项目边界

上述20261012十项任务现已完成，最终状态与独立验收见 `.ai-workflow/20261012-compact-controls/state.json`、`review.md`。根目录EXE/中文NSIS已更新且与最终十项release哈希一致；plan 24项实际桌面检查通过，单次成功收起/悬停箭头展开、减少动态和GitHub原生打开均已核对。后续保持本根目录交付约定，不自动恢复旧任务或历史版本产物。

- `src/` 为 Vue 前端，`src-tauri/` 为 Tauri Rust 外壳、配置和权限。
- 项目命令在本目录执行；如果当前会话启动目录仍为同级 UI，显式指定本项目 workdir 和绝对文件路径。
- 保留 package-lock.json，以本项目 README 和实际配置为准。
- 当前已完成五页 Vue 前端重写，数据及任务为明确标注的 frontend_demo / illustrative。连接 Python/NIST 后台与真实数据另按用户后续需求规划，不将示意数据当作科学结果。
- 保留用户未提交修改；同级 UI、CLI、WPF、源库、线库和已有结果不在本项目修改范围。
- 数据及来源必须真实；官方演示和示例命令不能当作实际 LIBS 计算结果。
- 完成后停止业务修改并交回 plan。尚未验证的桌面构建、启动或依赖状态必须如实记录。


2026-10-12最新短侧栏/等距图标/手动收起三项已完成，见 .ai-workflow/20261012-sidebar-refine/state.json、review.md。展开入口22×96px，三个36px图标8px等距，未运行也可手动收起/展开。用户确认退出旧程序后已直接更新dist-desktop根目录，plan14项实际release与22项保护哈希通过；保持既有自动成功收起、动画/减少动态及固定根目录交付约定。旧文件对话框任务仍暂停，不恢复历史等待文件锁状态。



2026-10-12最新11项统一控件/原生主题任务已完成，见 .ai-workflow/20261012-controls-unify/state.json、review.md。原生标题栏随日夜/系统模式，main只加allow-set-theme，串行模式同步避免媒体回路；通用ChoiceSelect/ElementCandidate/WorkbenchLayout已接三页。精确输入不再含Te/Ne/R滑条，开关600字重并使用其它预设色，红详情、选择后收起和五页文案精简已完成。三页成功100%收起，96px短柄/手动/取消/时间轴保持。正式根目录EXE/中文NSIS已更新，plan24项真实程序检查及夜间完整原生窗口截图通过，数据/I/O/依赖/Rust保护。心跳1-2同需求重放时先核对完成状态/产物，不重复实现；旧I/O任务不自动恢复。

