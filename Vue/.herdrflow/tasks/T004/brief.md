# T004 — 谱线位置参考新增按元素查询NIST Handbook Persistent Lines在线来源

dispatchId: 229c687f-8bda-4b35-bea4-2e7841ace916
revision: 1
owner: implementer

## 目标与验收标准

1. 在“加载当前谱线库”旁增加“加载 NIST 在线谱线库”按钮，展开在线元素选择并查询；无需先加载本地库即可选择元素。明确在线来源是 Handbook Persistent Lines。
2. 根据官方周期表查找元素实际链接，获取该元素中性I和一次电离II的Persistent Lines（实际table3/table4）。校验页面title和元素／species身份，不将404、错误页或空表当成功。缺某态但另一态有效时明确标注可用态和缺失原因，不补造。
3. 按元素／电离态加入现有参考组，可勾选、显示虚线及悬停详情。保留原始Å数值、换算nm位置、Aki及表头倍率、能级cm^-1、组态、Term、J、行号和引用。双行结构按实际页面字段解析，不错位。来源URL、获取时间、原始HTML SHA256可追溯，不把NIST数据冒充本地CSV或科学计算结果；不擅自改变空气／真空波长约定。
4. 本地、用户CSV、在线来源互不覆盖；刷新同一NIST元素替换其旧在线组，防重复且尽可能保留勾选。在线加载后自动加入该元素并显示可用态。失败／取消／清空后旧响应不得回填，保留已有参考组；本地库重载仍可用。
5. 固定官方HTTPS域名和Handbook路径，只接受元素符号，禁止任意URL输入；网络阶段有connect/read及整体deadline和响应大小限制，保持TLS验证，错误明确；不以本地数据回退伪装在线成功。使用已有requests／bs4，不新增依赖。
6. 桌面／窄屏／明暗模式按钮和元素选择可用、无溢出，在线来源与本地来源清楚区分；T003防抽动、T005图标及原有测量数据／负值／图表交互保持。

## 输入与项目约定

用户指定官方入口 https://physics.nist.gov/PhysRefData/Handbook/periodictable.htm 。协调者已用实际HTTP读取Fe I/II及H I/He II：官方页面含嵌套table，必须选择内层具有Intensity/Wavelength/Aki表头的表，过滤布局spacer行；Fe常见数据行为9列、后续同跃迁状态行波长为空。Periodic table的Fe链接为Tables/irontable1.htm，3/4分别为Persistent Lines I/II，存在元素名称拼写差异，不能用symbol猜英文URL。
读取项目AGENTS/protocol和前端reference panel/state、backend BrowserStore/reference。已有requests与bs4；Tauri资源白名单和collector包含simlibs_ui/*.py，无需修改Rust配置。
保留当前T003/T005已验收未提交源码与产物，保存dirty基线／保护hash。T006仅已规划，尚未派code，不得顺带实施。

## 修改范围

每个业务小步最多3文件，不是任务总共3文件。步骤A（后端）允许 backend/simlibs_ui/spectrum_nist.py（新增网络与解析）、backend/simlibs_ui/spectrum_browser.py（references分支路由）、backend/tests/test_spectrum_nist.py（必要解析／网络边界测试）。步骤B（前端）允许 src/lib/spectrumBrowser.ts、src/components/BrowserReferencePanel.vue。必要README/原理说明作为独立后续小步，勿扩大。复用既有ReferenceGroup结构，使BrowserSpectrumChart不必改tooltip。
禁止改现有科学计算、Linedatabase/source、Rust/Tauri、依赖、其他页面／共享CSS、旧证据和既有dirty。spectrum_reference.py原CSV解析保持只读。任务测试夹具、截图、真实HTTP证据和报告可写本目录；不得保存token/浏览器缓存为交付。

## 验证

code：必要后端unit tests（真实捕获HTML夹具，含双行／rowspan／空Aki／缺态／错误页／timeout／非法符号URL），真实联网Fe I/II和另一个元素，原始URL/hash/首位置与字段对照；不把mock响应称真实联网。npm run build；定向浏览器验证按钮邻接、无需本地库选择元素、真实本地API请求在线获取并叠加、刷新不重复、来源隔离、失败/取消保留、勾选/虚线/详情和窄屏。完成最终源码后只做一次桌面构建／根目录收集，运行中用户应用不关闭不覆盖，遇锁记录后待用户退出再收集。review独立读原需求／实际diff／冻结hash和HTTP证据，必要定向复验，写review.md。串行会改产物的验证，勿反复重跑通过的无关矩阵。

## 交付

implementation.md：变更、文件、验证、限制、版本。
review.md：独立审查结论与依据。
acceptance.md：协调者逐项验收。

完成标记必须包含当前 taskId、dispatchId、revision；标记本身不代替报告核验。
