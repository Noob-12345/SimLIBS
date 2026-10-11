# SimLIBS · Windows 桌面光谱工作台

这是基于 Tauri 2、Vue 3、TypeScript 的 **Windows 桌面软件**。Vue 是原生桌面窗口中的界面层；正式程序嵌入静态界面，双击启动，不需要浏览器网址、Vite 服务或 Python 进程。

## 双击使用

正式产物直接收集并更新到 [`dist-desktop/`](dist-desktop/)，不使用版本子目录。覆盖前核对运行进程；遇到实际文件占用则保留用户进程并报告，不另交目录。

交付文件位于 [`dist-desktop/`](dist-desktop/)：

- **[SimLIBS.exe](dist-desktop/SimLIBS.exe)**：Windows x64 正式程序，直接双击。
- **[SimLIBS-Setup.exe](dist-desktop/SimLIBS-Setup.exe)**：NSIS 安装程序，供用户按向导安装到当前 Windows 用户。
- [启动 SimLIBS.cmd](<dist-desktop/启动 SimLIBS.cmd>)：与 EXE 位于同一目录的启动入口。
- [使用说明.txt](dist-desktop/使用说明.txt)、[SHA256SUMS.txt](dist-desktop/SHA256SUMS.txt)、[artifact-manifest.json](dist-desktop/artifact-manifest.json)：启动说明、校验值和来源产物记录。

运行需要 Windows x64 与系统 WebView2 Runtime。NSIS 采用 Tauri 默认的 WebView2 检测/引导策略，运行时缺失时安装向导可能需联网获取。构建者不执行安装包、不修改自启动，也不重启系统。当前产物未配置代码签名。

本轮独立菜单、紧凑参数与提示精简的实际 release 验收由 plan 执行，记录位于 [.ai-workflow/20261012-compact-controls/](.ai-workflow/20261012-compact-controls/)。原生文件对话框验收任务仍暂停，安装程序的实际安装过程尚未测试；历史交付边界见 [.ai-workflow/20261010-desktop-delivery/](.ai-workflow/20261010-desktop-delivery/)。

## 当前功能与数据边界

当前为**界面演示阶段**，所有图谱、任务、进度和导出均为 `frontend_demo / illustrative`。未连接 Python、NIST、线库或真实计算服务。峰位、强度、Te/Ne 相对峰权重响应仅作确定性的视觉编排，没有真实物理意义，不做帧间谱线 morph。

顶栏两个相邻独立按钮分别选择日间/夜间/跟随系统与五种配色，菜单互斥并支持键盘操作。顶栏配色即时保存，仅更新颜色字段；设置页其它未保存配置保留。启动时同一窗口先显示界面准备动画，偏好、字体与首次布局就绪后进入主页；减少动态时改为短静态显示。载入失败或超时提供重新载入，不表示计算引擎加载。

| 页面 | 功能 |
| --- | --- |
| 单次模拟 | Te / 实际 Ne / 整数 R 输入与滑块，波长、模式/高级参数，元素补全与配比校验，演示运行/取消，完成图谱快照 |
| 批量模拟 | 独立草稿，固定/带种子的随机/CSV 模板，CSV 结构和比例校验，样本预览/统计，演示运行/取消 |
| 参数扫描 | Te / Ne / R 轴，包含两端的逐帧数据、当前值、时间轴、播放/暂停/前后帧；离开该功能自动停止播放与生成 |
| 任务记录 | 本次应用会话的实际演示操作，筛选、刷新、详情和关联示意结果；重启应用后清空 |
| 设置 | 日间/夜间/跟随系统，五种主题，减少动态，未来连接/环境草稿，本地保存/放弃更改 |

单次、批量与扫描的草稿和完成数据独立，运行时捕获有效快照。local 输出 Photon、离子上限 0–2；本地展宽默认关闭，此时 R 不用于展宽。深石墨侧栏、暖灰画布和白色面板均有完整深色适配；系统字体、SVG 和自然过渡尊重系统与用户的减少动态偏好。

Canvas 支持高 DPI、完整示意节点、总谱/元素图例、共同归一化、原节点悬停读值、左键框选/滚轮/按钮缩放、中键或 Alt+左键拖动平移、右键恢复全谱，以及原有键盘操作。默认 Te/Ne 扫描的视觉变化在归一化后仍可见。

侧栏以 SCNU 和软件日志分组。三项主要参数采用名称/单位与精确输入同行、滑块紧贴下方的紧凑布局，计算模式与高级选项常驻显示。处理方式展开后，每项末尾的说明图标支持悬停和焦点，不会选中模式。页面标题、控件、提示、数字及 Canvas 使用统一 Windows 中文字体体系。单次、批量、扫描的进度均显示在右侧工作台活动区，完成后保留100%绿色；取消/失败有独立状态，取消按钮仅运行中显示。

## Windows 本地文件

桌面窗口中的 CSV 模板采用 Windows“打开”对话框；图谱 CSV、来源 JSON、PNG、批量参数 CSV、示例模板采用 Windows“另存为”，选定位置后实际写入文件。取消不报失败、不写文件、不伪称保存；失败显示原因；成功显示实际路径和字节数。

使用官方 Tauri dialog/fs 插件。主窗口只开放文件打开/保存、读文本、写文本、写字节和 stat。无磁盘、HOME 或目录通配授权；访问范围是用户在对话框选择的具体文件，动态 scope 不跨应用重启保留。程序不自动修改用户选择的保存路径或追加扩展名。

可保存的文件都明确标注示意来源。来源 JSON 包含生成说明和采样限制；CSV 保存原始示意节点、总强度和元素贡献；PNG 保存当前图谱视图。

真实训练 CSV/ZIP、结果目录、续跑、环境检测、引擎连接和 GIF 尚未接入，相关操作禁用。未来连接草稿默认 `http://127.0.0.1:8517`，已存用户地址保留，不发起连接请求。

## 演示限制

- 组成 1–32 个元素，比例合计 100%；超额或非法输入阻止运行，不静默归一化。
- 批量最多 500 个样本；UTF-8 CSV 最大 2 MB / 500 行。参数列使用 `Te[eV]`、`Ne[cm^-3]`、`R`，元素列如 `Fe_at%`。
- 扫描 2–80 帧；单图为 600–12000 网格区间，扫描按帧数和元素数限制每帧规模。全部生成节点完整绘制/保存，限制说明在来源 JSON 的 `samplingNote`。
- CSV 校验仅覆盖结构、数值和比例，不校验真实谱线可用性。
- 草稿/任务保留在当前应用会话，重启后清空；主题与未来连接配置通过本地存储保存。

## 桌面开发与构建

所有命令在本项目根目录执行：

```powershell
Set-Location -LiteralPath 'D:\LIBS\SimLIBS\Vue'
$taskCargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
$env:Path = $taskCargoBin + ';' + $env:Path
npm run desktop:dev
```

`desktop:dev` 打开原生开发窗口，并启动仅用于开发热更新的 Vite。正式 EXE 不运行该开发服务器。如果已有开发服务器，应复用它并用临时配置覆盖 `beforeDevCommand`，避免重复启动。

```powershell
npm run desktop:build
```

此入口执行 release 编译、只生成 NSIS（不生成 MSI），然后将正式 EXE、安装程序、启动说明及 SHA256 收集到 `dist-desktop/`。源产物为 `src-tauri/target/release/simlibs-vue.exe` 与 `src-tauri/target/release/bundle/nsis/`。已经成功构建后可用 `npm run desktop:collect` 重新收集。

`npm run build` 只进行 Vue 类型检查和前端静态构建；正式配置的 `beforeBuildCommand` 会执行它，`frontendDist` 指向 `dist/`。正式窗口 1360×860，最小 960×640。Rust 仅增加原生文件插件初始化，保留已有命令，不接真实模拟算法。

已有 `node_modules/` 和工具链时无需重新安装。其它机器缺少依赖时使用 `npm ci` 保留锁文件解析；既有本机工具链记录见 [工具链验收](.ai-workflow/20261009-tauri-prerequisites/review.md)。

## 浏览器开发辅助

`npm run dev` 与 `npm run preview` 仅供界面开发；浏览器文件选择/Blob 下载是辅助回退，不报告为原生文件写入。浏览器地址不是本软件的交付入口。

## 项目与协作

`src/pages/` 为五页界面，`src/components/` 为共享控件/Canvas/SVG，`src/lib/` 为数据、校验、任务、偏好及文件适配。`src-tauri/` 为原生外壳和最小权限，`scripts/collect-desktop.mjs` 收集桌面产物。应用图标由本项目 `public/spectrum.svg` 经 Tauri icon CLI 派生。

保留既有 plan/code 两角色，业务改动每步最多三个文件，code 实现与自测后交原 plan 独立验收。原 UI/Python/CLI/WPF、源库、线库与已有结果均不在本项目写入范围。
