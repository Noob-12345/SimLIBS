# SimLIBS Vue 项目协作约定

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

2026-10-12用户明确要求后续正式产物**直接更新 `D:/LIBS/SimLIBS/Vue/dist-desktop/` 根目录，禁止另交版本子目录**。此指令覆盖此前主题动画任务的版本目录交付约定，历史记录仅表示当时事实。当前任务 `.ai-workflow/20261012-compact-controls/`：独立配色按钮、紧凑三参数、处理方式逐项悬浮说明及指定文字删除。保留原plan/code两角色，不关闭用户软件；不恢复旧文件对话框任务。

## 项目边界

- `src/` 为 Vue 前端，`src-tauri/` 为 Tauri Rust 外壳、配置和权限。
- 项目命令在本目录执行；如果当前会话启动目录仍为同级 UI，显式指定本项目 workdir 和绝对文件路径。
- 保留 package-lock.json，以本项目 README 和实际配置为准。
- 当前已完成五页 Vue 前端重写，数据及任务为明确标注的 frontend_demo / illustrative。连接 Python/NIST 后台与真实数据另按用户后续需求规划，不将示意数据当作科学结果。
- 保留用户未提交修改；同级 UI、CLI、WPF、源库、线库和已有结果不在本项目修改范围。
- 数据及来源必须真实；官方演示和示例命令不能当作实际 LIBS 计算结果。
- 完成后停止业务修改并交回 plan。尚未验证的桌面构建、启动或依赖状态必须如实记录。
