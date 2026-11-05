# SimLIBS Vue 真实后端资源

当前高级自动级联为 JSON → 在线STARK-B → NIST完整原子输入＋DK1980 → 明确missing。生产只读 source/simLIBS/data/stark_broadening.json（固定SHA256 f40995bbb87ffeedb069d29e8e42c7fa6e64d939ceaceeb19fe902b7185f5a54），不依赖开发父目录或sample；以下旧自动发现路径/CSV说明为历史，已被本段替代。原始gzip payload、rows和内嵌manifest完整校验。动态NIST能级/E1 Aki/权重/电离阈值通过有限transport/TLS/重试/大小/取消及用户state缓存。实际q2/3（III/IV）才可DK1980；HTTP不接受数据路径或原子模型，新CSV覆盖停用。逐线resolution层、来源、DOI、条件和原因进入导出，下载清单不重新导入。worker原job进度明确包含“Json抓取”和具体元素/电离阶段；缓存命中如实标记，detail不以截断badge替代。数据故障不伪missing，验证替代来源仍保留故障证据。

2026-11-05 Stark 模拟按 **STARK-B → DK1980 → 缺失** 执行，以下历史“用户 CSV / 内置 JSON 优先”的说明已被替代。源引擎解析与渲染同步核心版本，原 paper 结果容器通过 `SpectrumResult` 别名兼容。

开发仓库自动发现 `simLIBS-2.0.3/stark-b/stark_broadening.json` 和 `simLIBS-2.0.3/sample/`；独立部署须提供数据或设置受信任进程环境 `SIMLIBS_STARK_DATABASE`、`SIMLIBS_STARK_ATOMIC_DIR`。HTTP 不接受数据库路径、原子目录或模型输入，旧 Stark CSV/local 覆盖请求明确拒绝。表未命中后读取完整 NIST 原子输入构造 DK1980；q=0/1 不套用公式，q=2/3 必须满足可靠输入约束。

离线库按文件修订缓存并校验 rows。数值身份的 NIST 线仍需 ASD 身份缓存或本地原子 E1 表严格匹配；关闭 Stark 联网后不会在线补身份。缺失继续/严格失败策略保持，清单保存两层原因，未知宽度与参考密度为空。来源及归档见 [数据库说明](../../simLIBS-2.0.3/docs/STARK_DATABASE.md)。本次未构建 EXE/安装包。

2026-10-17 高级模拟新增独立展宽分支（自吸收/Stark/仪器 6 种物理组合）与元素光谱视图。SA 开启严格要求 Stark 开启；纯 Stark 跳过全阶段能级与 Saha；无 Stark 仅依赖 sticks payload。

simlibs_ui、web API、源 simLIBS 模块/许可证及 62 份谱线 CSV 复制自原 UI/源库/线库，仅修改 Vue 副本。原样复制 SHA256 见 .ai-workflow/20261013-backend-migration/copied-files.json。data.csv 与 mock_backend 仅测试 fixture，不进入桌面资源，生产禁止 mock fallback。

Windows EXE 自动启动 owned Python，127.0.0.1 系统分配端口、随机 session token、可信 origin，Windows Job Object 管理所属进程树。服务与 worker/浏览器关闭只清理本应用拥有的树，不按进程名清理其它服务。

Python runtime 没有打包。需现有 Python 3.11 及 numpy/pandas/scipy/matplotlib/selenium/requests/beautifulsoup4/webdriver-manager 等原后端依赖。本机可复用 E:/Anaconda/envs/simLIBS/python.exe；可用 SIMLIBS_UI_PYTHON 或设置指定解释器。没有自动安装全局依赖，不保证跨机器无需 Python。

安装后配置、session、驱动缓存、日志及默认 outputs 写入当前用户 app_local_data_dir。backend 本身只读，资源解析使用 Tauri resource_dir。便携 EXE 必须与同目录 backend 一起分发。用户设置输出目录用于新任务存储与另存为起点，已保存任务保留原路径。

local 使用本地 LTE/Saha 科学计算；client 由 NIST dataSticksArray 计算线强、Python 展宽；server 使用 NIST 官方页面计算与展宽。在线模式需网络/Chrome/匹配驱动；错误直接提示，无示意数据回退。所有谱线、参数、manifest/origin、实际 R/Ne 来自真实后台。

2026-10-16高级页默认NIST逐线自吸收（nist-lines-self-absorption-1），保留离线paper选择，缺省model的旧请求继续旧分支。仅按字节增补原始nist_lines.py/nist_self_absorption.py，不覆盖simulation.py/self_absorption.py，不改变普通模式。高级适配层独立获取有界NIST响应，复用原始prepare/render；NIST高级与client不需要Chrome，server仍需匹配浏览器/驱动。

Stark CSV仅接收受控上传文本，无任意路径读取；2MB上限，finite/正宽度/正参考Ne/完整标识严格校验。缺失时任务固定missing-stark.csv/json原子落盘并失败，现有export端点以stark-missing下载失败任务清单，以diagnostics下载成功高级任务完整逐线CSV。轮询只有小型摘要，重启按原job的expected_result_path恢复固定文件；禁止客户端指定文件路径。三谱/诊断绑定成功job，失败/取消不覆盖旧结果。

本轮交源码与前端dist，未打包桌面。46项后端+8项SSR/组件检查；捕获夹具不等于在线实算，另有一次真实窄带1条61点证据。GUI未测，独立review待完成，见Vue/.ai-workflow/20261016-advanced-nist/。

2026-10-18：stark_b.py、nist_stark.py、nist_self_absorption.py 按上游d7a340d工作树原字节同步；普通simulation.py、旧离线self_absorption.py保留兼容版本。高级配置支持stark_source=auto/local、stark_allow_network及有序SCP/MSE。缓存优先SIMLIBS_STATE_DIR/cache/stark-v1，否则上游用户目录；仅可信进程可用SIMLIBS_STARK_CACHE_DIR隔离测试，HTTP请求不可指定路径。每个取数阶段180–600秒，单请求沿用connect/read超时、TLS设置、最多3次尝试与响应大小限制，协作取消之外仍由独立worker进程树兜底。

MissingStarkDataError保留每条件原因和matched来源；缺失CSV按跃迁唯一化，可填W重导入。固定job导出新增stark-matched及stark-report，仍保留stark-missing/diagnostics。网络/缓存/格式错误按stark_*分类，不伪造缺系数清单；成功advanced-lines.json保留温区列表、引用、NIST身份和快照SHA，CSV与旧结果读取继续兼容。最终桌面构建待与网站模块合并；当前运行中的root EXE与backend资源不修改。
