# SimLIBS · Windows 桌面光谱工作台

这是基于 Tauri 2、Vue 3、TypeScript 的 **Windows 桌面软件**。Vue 是原生桌面窗口中的界面层；正式程序嵌入静态界面，双击启动，无需浏览器网址或 Vite 服务；程序自动启动并管理本应用拥有的 Python 后端。Python runtime 未打包，需已有 Python 3.11 及原后端依赖，可通过 SIMLIBS_UI_PYTHON 或设置指定解释器。便携 EXE 必须与 backend 资源目录一起分发。

## 双击使用

正式产物直接收集并更新到 [`dist-desktop/`](dist-desktop/)，不使用版本子目录。覆盖前核对运行进程；遇到实际文件占用则保留用户进程并报告，不另交目录。

交付文件位于 [`dist-desktop/`](dist-desktop/)：

- **[SimLIBS.exe](dist-desktop/SimLIBS.exe)**：Windows x64 正式程序，直接双击。
- **[SimLIBS-Setup.exe](dist-desktop/SimLIBS-Setup.exe)**：NSIS 安装程序，供用户按向导安装到当前 Windows 用户。
- [启动 SimLIBS.cmd](<dist-desktop/启动 SimLIBS.cmd>)：与 EXE 位于同一目录的启动入口。
- [使用说明.txt](dist-desktop/使用说明.txt)、[SHA256SUMS.txt](dist-desktop/SHA256SUMS.txt)、[artifact-manifest.json](dist-desktop/artifact-manifest.json)：启动说明、校验值和来源产物记录。

运行需要 Windows x64 与系统 WebView2 Runtime。NSIS 采用 Tauri 默认的 WebView2 检测/引导策略，运行时缺失时安装向导可能需联网获取。构建者不执行安装包、不修改自启动，也不重启系统。当前产物未配置代码签名。

本轮输出目录、快照摘要卡与字段校验的实际 release 验收由 plan 执行，记录位于 [.ai-workflow/20261012-output-validation-layout/](.ai-workflow/20261012-output-validation-layout/)。旧原生文件对话框完整验收仍暂停，SDK模拟/浏览器导入自查不等于OS对话框全量验收；安装过程尚未测试。

## 当前功能与数据边界

已复制并连接真实 Python 后端。local 使用本地谱线库及 LTE/Saha 计算；client 在线获取 NIST 谱线跃迁与强度，由本地引擎进行线型展宽；server 由 NIST LIBS 在线服务生成光谱并进行展宽，未承诺连续谱能力。默认空谱，真实进度，失败/取消保留上一成功结果，无合成谱回退。当前源码的高级模拟默认使用 NIST 逐线自吸收（`nist-lines-self-absorption-1`），可选保留离线论文模型（`paper-eq7-stark-sa-1`），提供名义薄谱、基体薄谱、自吸收修正谱的共同尺度对照与可携带导出。参数化基体仍需实验标定。完整公式、单位、真实数据来源与适用边界见 [论文自吸收报告](../simLIBS-2.0.3/SELF_ABSORPTION_REPORT.md) 和 [功能与原理](PROJECT_FUNCTIONS_AND_PRINCIPLES.md)。本轮 Vue 实施与自测见 [.ai-workflow/20261015-paper-self-absorption/implementation.md](.ai-workflow/20261015-paper-self-absorption/implementation.md)，最终验收由原 plan 负责。

高级NIST入口在线获取线强、跃迁及全部电离阶段能级，默认Mg100%、真空285.27–285.33nm、输出步长0.001nm；任意元素或宽波段需要完整逐线Stark系数，不保证全部元素可算。仪器w=λ/R为高斯1/e半宽，FWHM=2√ln2·λ/R；输出为NIST相对光子强度，不是绝对辐亮度。默认总密度由Ne与平均电荷按电荷守恒反推，也可指定数密度，L=0可作薄谱极限。Stark CSV最大2MB、支持BOM；W为stark_width_nm，内禀FWHM=2W·Ne/Ne_ref。缺失清单保留双精度，填W后可重导入，错误/歧义不得跳线发布部分谱。失败清单和成功三谱/诊断分别绑定原job，刷新/重启后仍可导出；所有新增自吸收入口仅在高级页。新入口不使用旧5%限制；未带model的旧请求继续旧离线语义。

离线选择保留论文 Table 1 的 Mg、Ca、Zn 共31条谱线及 NIST I/II/III 能级快照。示例为 Mg 100%、284.5–286 nm；缺少必要 Stark/三态原子数据的元素（如默认数据中的 Fe）会明确拒绝。光程 L 默认0.01 m，总数密度按 `柱密度[cm⁻²] / (100 × L[m])` 换算为 cm⁻³，基体产额倍率再作用于有效数密度；Ne单独指定。逐线 SA 与吸收展宽先计算，仪器 Gaussian 在其后应用，R不进入光学厚度。旧热与附加 Gaussian/Lorentz 草稿字段不用于本模型。高级谱沿用 photon 强度约定，与论文能量式按单线光子能量换算；不声明标定探测器计数。

2026-10-16新增NIST高级入口交付源码及前端dist，未打包Windows。46项后端与8项SSR/组件/脚本检查通过，其中数学和HTTP补数闭环使用捕获夹具；另一次真实NIST窄带模拟成功得到1条跃迁、61个节点。GUI未测，未重试受拒浏览器启动。实现与冻结见 [.ai-workflow/20261016-advanced-nist/](.ai-workflow/20261016-advanced-nist/)，独立review尚待完成。

2026-10-17 高级模拟新增三卡一行布局（Te / Ne / R 方卡）、独立展宽机制（自吸收、Stark、仪器响应 3 个独立布尔开关，覆盖 6 种有效物理分支）及分元素光谱视图（元素组分与三谱对照双视图切换，默认元素组分，支持元素图例独立显示/隐藏与共同尺度展示）。后端更新源库至 ee7b66a 字节，无 Stark 时渲染纯棒状投影或仪器高斯、无需原子能级与 Stark 数据；纯 Stark 跳过全能级布居与 Saha；开启自吸收严格依赖 Stark。交付源码与前端 dist，GUI 未测。见 [.ai-workflow/20261017-advanced-broadening/](.ai-workflow/20261017-advanced-broadening/)。

2026-10-18 高级参数栏按实验参数、模型与展宽、元素组成与可选基体三组组织，Te / Ne / R 沿用单次模拟的同排方卡。模型下直接显示 Stark、自吸收和仪器展宽：NIST 关闭 Stark 时同步关闭自吸收，开启自吸收时自动开启 Stark，仪器展宽独立；离线论文模型仍为固定 Stark。隐藏细项保留草稿，参数区保持整页自然滚动。本轮已重新构建 Windows EXE、中文 NSIS 并同步 backend 到 `dist-desktop/` 根目录，替换早于 10/17 前端的旧产物。code 自测与冻结记录见 [.ai-workflow/20261018-advanced-panel/implementation.md](.ai-workflow/20261018-advanced-panel/implementation.md)；新版 GUI 由主会话另行取证，安装包未执行，最终审查由独立 review 完成。

**2026-10-15 历史交付为源码、Python 后端和 Markdown 报告。** 后端已在 Python 3.10 环境验证，Vue 类型检查与静态构建已通过；未重打包或更新 `dist-desktop/` 中的旧 EXE/NSIS。此前桌面产物和历史验收记录不能代表本轮论文引擎已进入可执行文件。Tauri 资源白名单与收集脚本均已包含 `backend/source/simLIBS/data/*.json`，实际安装包资源路径仍须在具备 Rust/Cargo 的环境重新构建后验收。

顶栏两个相邻独立按钮分别选择日间/夜间/跟随系统与五种配色，菜单互斥并支持键盘操作。顶栏配色即时保存，仅更新颜色字段；设置页其它未保存配置保留。启动时同一窗口先显示界面准备动画，偏好、字体与首次布局就绪后进入主页；减少动态时改为短静态显示。载入失败或超时提供重新载入，不表示计算引擎加载。

启动问候按本机本地小时读取一次，夜间为“夜深人静了，早点休息。”。真实UI ready后在既有最短显示基础上增加至少1秒阅读时间，减少动态也保留；ready即清初始化watchdog，不把阅读停留误判为超时。主题/配色先模糊峰值应用再清晰，透明层不拦操作、不对body加filter；快速最后请求生效，初始化及减少动态跳过。

Windows原生标题栏通过现有Tauri窗口接口同步日间/夜间；跟随系统传入null恢复系统主题。请求串行处理，媒体变化不再次触发native请求，失败显示反馈。设置中的模式预览/保存/放弃更改继续生效。

| 页面 | 功能 |
| --- | --- |
| 单次模拟 | Te / 实际 Ne / 整数 R 精确输入，波长、模式/高级参数，元素候选与配比校验，真实运行/取消，完成图谱快照 |
| 批量模拟 | 独立草稿，固定/带种子的随机/CSV 模板，CSV 结构和比例校验，样本预览/统计，真实运行/取消 |
| 参数扫描 | Te / Ne / R 轴，包含两端的逐帧数据、当前值、时间轴、播放/暂停/前后帧；离开该功能停止播放，真实后台任务继续运行 |
| 高级模拟 | NIST全阶段逐线自吸收/旧离线选择、三卡一行(Te/Ne/R)、独立展宽机制(自吸收/Stark/仪器)、元素组分与三谱对照双视图、Stark CSV补数闭环、光程/密度及未标定基体、分页诊断与完整导出、任务取消/历史 |
| 任务记录 | 真实持久化历史、刷新、详情、重开结果、取消及合法批量续跑 |
| 设置 | 日间/夜间/跟随系统，五种主题，减少动态，连接/环境检测与受控 Python 重启，本地保存/放弃更改 |

单次、批量与扫描的草稿和完成数据独立，运行时捕获有效快照。local 输出 Photon、离子上限 0–2；本地展宽默认关闭，此时 R 不用于展宽。导航随日间／夜间和当前配色响应：日间浅色、夜间石墨，暖灰画布和面板均有深色适配；系统字体、SVG 和自然过渡尊重系统与用户的减少动态偏好。

Canvas 支持高 DPI、完整实际 CSV 节点、总谱/元素图例、共同归一化、原节点悬停读值、左键框选/滚轮/按钮缩放、中键或 Alt+左键拖动平移、右键恢复全谱，以及原有键盘操作。总谱与元素谱保持实线；细点网格、等宽刻度和主题半透明虚线十字游标辅助读数。光标仅在可见曲线真实局部峰的10px屏幕距离内吸附，远处仍读取原节点；浮层同时列出原值与共同归一化值，支持多元素滚动和边界避让。元素贡献不等于谱线离子鉴定，当前数据没有离子标识时不推断 Mg I 等归属。隐藏总谱同时隐藏其填充、标记与读数，归一化尺度保持共同基准。未展宽默认按精确原始线位画竖线，sticks 不连成包络或填充；仅连续谱使用7%至透明的垂直渐变，所有实际节点仍完整绘制。

Te/Ne/R 卡使用微底色、等宽加粗数字、弱化单位与聚焦环，保持精确草稿及校验语义。共享选择器使用轻微展开过渡和选中强调条；进度扫光只在运行态，同一任务从运行转成功仅播放一次轻脉冲。单次、批量、扫描、高级与任务页共用无数据波形插画，插画仅为装饰。三级背景区分工作区、面板与浮层，保留五种配色及明暗/跟随系统；系统或应用开启减少动态时停用扫光、缩放与柄的微位移。

侧栏以 SCNU 和管理与设置分组。单次Te/Ne/R为三张横排方卡，标题尾带单位、下方数值居中；长值可水平编辑，实际Ne科学计数往返和整数R校验保持。批量/扫描保留原精确输入，均无参数滑条；扫描时间轴保留。统一选择器、元素候选与红色说明保持。高级展宽/插值/后台抓取开关提供独立说明按钮，hover/focus/click不切开关。开关文字加粗，开启使用另一个预设色。三页进度位于右侧，完成保留100%绿色，取消按钮仅运行中显示。

四页恢复原工作区面板和响应式顺序，不保留常驻参数工具栏。唯一展开/收起入口为侧边箭头：平时整个框隐藏，在窗口内移动鼠标即显现跟随当前主题配色的边框、柔光及微底色，静止约600ms后淡出；实际悬停或键盘Tab聚焦时强化同主题高亮并持续显示，普通点击不会因残留focus常驻。框长默认/上限220px、按可见工作区及视口裁切，18px加粗箭头收起朝左、展开朝右；窄窗仍保留入口，触摸可点击。位置随滚动、尺寸与动画更新，成功100%后自动收起；精确草稿、结果、扫描帧/播放、取消/失败隔离、inert/焦点保持。系统或应用减少动态时即时切换颜色/可见性，不作滑动。下拉聚焦和弹层内操作保留主题高亮。顶栏三个36px按钮8px等距，GitHub通过系统默认浏览器打开固定项目仓库。

2026-10-18 STARK-B 后端同步：高级 NIST 的 Stark 系数默认按用户 CSV、内置 JSON、STARK-B 自动补充，并通过 NIST 身份表严格匹配量子态。新增受控用户缓存、有限网络阶段与独立错误分类；缺失任务同时保留 missing/matched 诊断，成功 JSON 保留来源、温区和未知隔离上限 null。普通模拟与离线 paper 入口保持原版本。本轮源码与联网证据见 [.ai-workflow/20261018-starkb-backend/](.ai-workflow/20261018-starkb-backend/)；最终桌面构建与网站模块合并，运行中的旧 EXE/backend 暂不覆盖。

## Windows 本地文件

桌面窗口中的 CSV 模板采用 Windows“打开”对话框；图谱 CSV、来源 JSON、PNG、批量参数 CSV、示例模板采用 Windows“另存为”，选定位置后实际写入文件。取消不报失败、不写文件、不伪称保存；失败显示原因；成功显示实际路径和字节数。

使用官方 Tauri dialog/fs 插件。文件权限只开放文件打开/保存、读文本、写文本、写字节和 stat。无磁盘、HOME 或目录通配授权；访问范围是用户在对话框选择的具体文件，动态 scope 不跨应用重启保留。程序不自动修改用户选择的保存路径或追加扩展名。现有 opener 仅允许主窗口打开 `https://github.com/Noob-12345/SimLIBS`，未授予任意 URL、路径或指定程序权限。

原生主题同步仅给main窗口增加`core:window:allow-set-theme`；保留系统原生最小化/最大化/关闭按钮，不自制标题栏。

来源 JSON 包含真实 manifest/origin/参数/科学来源；CSV 保存同一真实轴、总强度和实际元素贡献；PNG 保存当前真实图谱视图。训练 CSV/ZIP、参数/模板 CSV 与 GIF 均下载真实成功任务文件。

桌面默认自动本机服务，使用系统分配的 127.0.0.1 端口、随机 session token 与可信 origin；浏览器开发可显式配置外部 endpoint/token。外部服务不由应用终止。资源通过 Tauri resource_dir 解析；安装后配置/session/驱动缓存/log/默认 outputs 写入用户 app_local_data_dir，安装资源只读。输出目录保存后用于新任务与另存为起点；旧任务保留原路径。Python 更改在保存时受控重启 owned 后端，活动任务期间拒绝重启。关闭窗口协作退出并由 Job Object 清理所属树，不按 Python/Chrome 进程名清理。

单次三方卡数字居中，参数简记为 Te / eV、Ne / cm⁻³、R (λ/Δλ)，波长简记为 λ / nm；批量/扫描同类参数单位位于输入尾部。重粒子温度的自动选项按热平衡关系将 Te 从 eV 换算为 K，保留 T[K] = Te[eV] × 11604.518。组成总和错误显示当前总计；前序比例超过 100%（沿用 1e-6 容差）时提示调小前序比例，恰好 100% 且末元素为零仍有效。谱图下三等宽等高摘要卡使用当前谱图快照：Te/Ne/R、波长窗口、彩色组成tile，草稿修改不改变旧图谱摘要。错误只标记对应字段并短抖，减少动态保留红色而跳过抖动，说明集中在工作台活动区；正确其它字段不标红，核心数值/组成/随机/CSV/扫描限制保持。批量随机Te/Ne同排；成功CSV读取后可红色清除，有效文件名绿色，清除恢复，取消/失败保留原模板。

## 后端限制

- 组成 1–32 元素，比例合计 100%；未知或缺失本地谱线在 worker 启动前拒绝。
- 批量最多 5000 样本、总谱单元 5000000，CSV 最大 2 MB；支持后台完整参数列，裸 Ne/Te 为元素，参数使用 Ne[cm^-3]/Te[eV]/R。
- 扫描 2–200 帧，单谱最多 200000 实际节点；前端最多缓存 3 完整帧，播放等帧返回。Ne API 输入指数边界，实际密度线性扫描，显示 manifest.completed_values。
- 随机 Te/实际 Ne 线性范围与浓度独立开关由 Python 生成并保存确定计划，前端不生成二次随机。
- Python 未打包、安装未实际执行；在线需网络、Chrome 与匹配驱动。本机已有解释器可用，不保证其它机器无需配置环境。
- 原生对话框旧暂停任务不自动恢复；浏览器真实下载和底层文件核对不冒称 OS 点击验收。

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

`npm run build` 只进行 Vue 类型检查和前端静态构建；正式配置的 `beforeBuildCommand` 会执行它，`frontendDist` 指向 `dist/`。正式窗口 1360×860，最小 960×640。Rust 保留原生文件插件，新增窄 owned-backend 命令、资源解析与进程树生命周期；科学计算由复制 Python 执行。

已有 `node_modules/` 和工具链时无需重新安装。其它机器缺少依赖时使用 `npm ci` 保留锁文件解析；既有本机工具链记录见 [工具链验收](.ai-workflow/20261009-tauri-prerequisites/review.md)。

## 浏览器开发辅助

`npm run dev` 与 `npm run preview` 仅供界面开发；浏览器文件选择/Blob 下载是辅助回退，不报告为原生文件写入。浏览器地址不是本软件的交付入口。

## 项目与协作

`src/pages/` 为五页界面，`src/components/` 为共享控件/Canvas/SVG，`src/lib/` 为数据、校验、任务、偏好及文件适配。`src-tauri/` 为原生外壳和最小权限，`scripts/collect-desktop.mjs` 收集桌面产物。应用图标由本项目 `public/spectrum.svg` 经 Tauri icon CLI 派生。

保留既有 plan/code 两角色，业务改动每步最多三个文件，code 实现与自测后交原 plan 独立验收。本轮核心引擎修改范围以 [论文自吸收报告](../simLIBS-2.0.3/SELF_ABSORPTION_REPORT.md) 为准；Vue code 只处理 Vue 适配、资源与文档，原 UI/CLI/WPF、旧线库及已有结果不在其修改范围。
