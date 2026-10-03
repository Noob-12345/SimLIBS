# 五项 Web 改进实现记录（coder 完成，等待原 reviewer 独立验收）

## 当前进度
五项按顺序实现、自测完成；HTTP/三键/两尺度实测和最终服务确认完成。现在停止业务修改，交planner冻结并交原reviewer独立验收。本记录仅coder证据，不宣称独立通过。

## 4 末元素余额
范围仅app.js。先RED复现80/19/2不纠正、single99不补100，以及前缀100时空末项被吞0并提交。末项=100-prefix；超额把末项降0后只限本次前项，不缩放其他；新增/删除/预设/小数均重新余额。无效草稿保留原值并阻止API，输入期间不重建DOM。初次实现指数1e999中途被限额改写，回归发现后修为当前编辑文字到失焦才改写、规范数据仍按余额；防止不完整指数被误吞。包含前四项7浏览器回归GREEN，11.019s。

## 5 强度尺度
5A范围models.py/adapter.py（2）：枚举/default photon；UISimulation.get_site覆盖真实URL int_scale energy1/photon2，仍原构造/解析/getter，无事后乘谱。明确来源参数、int_scale和相对单位；旧来源可从已记录URL识别，历史无字段unknown。静态HTTP/动态driver.get mocked捕获URL回归先RED后GREEN；结合adapter/models27测试通过。
5B范围backend_api/real_backend/mock_backend（3）：API枚举/默认、单次批量扫描透传、真实结果来源尺度/各帧尺度；API仍严格100%与周期表。MOCK明确unknown/仅requested尺度，不冒充物理转换，fake yi从结果移除。API/flux/sampling13tests GREEN。
5C范围index.html/app.js（2）：photon默认选择，切换只影响下次；旧成功结果标签取其实际来源，不用当前控件覆盖；轴科学数值与a.u.，实际raw/ion按来源可用性。SSE完成/失败/取消与旧标签回归和前四项共9浏览器测试GREEN，11.763s。
5D范围plotting.py/input_views.py/result_view.py（3）：PNG/GIF逐帧从manifest原尺度绘制，unknown历史不猜；旧Tk加载energy配置保留字段，未增加或挤占UI控件。对应标签/参数回归先RED，20个flux/app/operations测试GREEN，5.528s。

唯一原 libs_coder 执行，已读 task/plan/findings/baseline-page 与当前 Web/Core 代码。沿用现有界面风格与三键交互，不创建 agent/pane/终端；源库只读。新服务8517直到最后确认归属/无活动任务后才隐藏重启。采用 TDD/系统调试/验证流程，逐项推进，每步≤3业务文件；独立验收由原 reviewer 在 coder 停止后执行。

## 1A 采样与真实序列
范围 web/sampling.py、real_backend.py、static/app.js（3业务文件）。5个Python回归先RED，确认单次仍1500、扫描375、缺ion用假零数组；Selenium本地静态/假传输回归先RED，真实raw3点被画成插值4点。随后从完整CSV读各真实序列，单次6000、扫描2000预算；峰谷、相邻点和端点优先，剩余选择最大原始间隙中的原点，不插值、不舍入、不补数据。各离子列用自己的真实波长/强度，Sum(calc)不作为单离子。
极端高峰谷数量超过预算时明确拒绝显示并提示缩小范围，不悄悄丢弱峰（科学全量文件仍可导出）；此数学边界比默默牺牲科学数据更严格。窄峰/1e-12弱峰/独立网格/少点回归通过。Canvas采用独立真实序列、非均匀最近点悬停、弱强度科学格式与有界ticks；真实数据描线呈现不做数值morph插值，保留RAF动效、闪光/主题/三键事件。高DPI按devicePixelRatio绘制，raw不再二次降到260点，光晕降低以免淹没弱峰。
Python5tests GREEN，0.414s；隔离已缓存Chrome的本地Seleniumraw回归 GREEN，5.493s。浏览器测试显式 SIMLIBS_WEB_BROWSER_TEST=1，默认unittest不启动Chrome，不调用外网；不下载驱动、不读用户profile/cookies，始终quit。

## 1B 显示预算契约
范围 backend_api.py、index.html、web/README.md（3文件）。预算API回归先RED（1500≠6000），统一Web6000说明、保峰/真实序列与不造点说明；物理200000和Core/Tk1500不改。采样/API共6测试GREEN，0.346s。

## 2 主区滚动与响应布局
范围 style.css/app.js（2文件）。四视口Selenium先RED，main933超实际inner612/564/924，真实滚动无法到runBtn。补grid/flex min-height:0、min-width:0、主区overflow与窄屏单列；侧栏内部可滚，主题令牌/动效不改。已有真实结果resize明确重绘，避免只fetchPreview返回而留旧画布尺寸。四视口用真实wheel与scrollIntoView检查开始按钮/日志、文档无水平溢出，通过。setWindowRect之后等两个RAF再记录实际inner，避免浏览器异步resize读旧尺寸。

## 3 元素大小写
范围 style.css/app.js/real_backend.py（3文件）。实际键盘Fe/FE/fe回归先RED（uppercase视觉、FE/fe不规范）；无效/重复负向首次提前读取异步请求错误地通过，修正等待runSingle Promise后确实RED（Xx、重复W实际发出）。删除CSS uppercase；按Core周期表返回element_symbols，并用同一118项离线fallback合法表规范化，失焦/提交变为Fe，非法和重复在请求前拒绝。单次/批量/扫描的提交共用严谨compositionPayload，不筛掉空行猜测合法组成。包含前三项的4个浏览器回归通过。

## 收尾小步与实际发现
- Web API自身沿用旧先乘后除扫描式：新增回归RED后改稳定比例顺序、finite派生检测，并在Ne指数溢出时400拒绝；预览查询同时透传intensity_scale；获取新结果失败时不先更新导出job ID。范围backend_api.py/server.py/app.js（3文件）。
- HTTP真实路由回归：local ThreadingHTTPServer+fake backend只验证接口，不请求NIST；三种路由energy透传、非法元素/99%/NaN组合400且零backend启动，SSE终态通过。首个测试fixture终态events为空且读EOF循环，Ctrl-C只终止该测试，补fixture与EOF断言后2tests GREEN（1.404s），未改生产科学行为。
- 安全重启需要保留原已完成任务。范围real_backend.py（1文件），新增终态会话恢复回归先RED后GREEN；只读取本项目已有manifest、拒绝活动或非合法ID，恢复终态记录而不复活进程。web/.web-session.json是运行状态，不覆盖用户输入/科学文件。
- PNG单次标题此前未读origin.parameters而显示Te/Ne=0，回归RED后读取实际来源；再看图发现Microsoft YaHei无上标负号，回归RED后导出密度单位写cm^-3，PNG重导出自既有结果、无新科学请求。显示点说明明确为interpolated CSV点，与真实raw行数分开。范围real_backend.py（1文件）。
- 真页面亮主题截图最初拍在CSS过渡中，等450ms既有动效完成再重绘/截图；业务主题令牌、动效未删。最终图片已看图核对。

## 科学实测（真正8517 HTTP→真实worker→原源类）
执行 `python -B .ai-workflow/20261002-web-improvements/verify_scales.py`。参数H100%、Te1eV、Ne1e17、R1000、400–700nm、static；成功两次分别Photon int_scale2/Energy int_scale1。不是在本地乘谱，不锁绝对强度。

| 项目 | Photon | Energy |
| --- | --- | --- |
| job ID | 6cafc9e3637d49a4aa98e0517fa81697 | 7a95c65420a844729f3d6e3bfc4986b4 |
| 完整raw行 | 246 | 246 |
| 完整interpolated行 | 60000 | 60000 |
| Web显示点 | 6000 | 6000 |
| 410/656峰比 | 0.0454661487236404 | 0.07277696793002915 |
| 434/656峰比 | 0.0916204217536071 | 0.13855685131195336 |
| 486/656峰比 | 0.2365149833518313 | 0.3194241982507289 |
| 请求及全量导出验证耗时 | 4.125s | 3.984s |
| PNG轴 | Photon flux [a.u.] | Energy flux [a.u.] |

410/656相对权重比改变约1.6006846846，证明真实NIST尺度影响各谱线权重。来源记录class/source_file/SHA256/实际Ne/NIST URL/int_scale/intensity_scale/相对单位一致。全量CSV、JSON、PNG经实际HTTP导出，PNG已开图；GIF只复用这两个已完成真实结果做两尺度对照，不伪称新Te/Ne/R扫描，也未造新科学帧。Pillow打开确认2帧并逐帧解码，各帧绘图按自身origin标尺度。
证据 scientific/checks.json、photon.csv/json/png、energy.csv/json/png、comparison.json、photon-energy-comparison.gif。verify_scales.py可复跑但会再次请求NIST；审查先看已有证据和mock URL断言即可。
首次Photon请求e87e6632e5234f169061a5a07ba166d3在00:06报TLS UNEXPECTED_EOF，真实失败记录保留；正常TLS校验下针对性重试成功，未关闭TLS、未用示意数据替代。另读官方表单GET200，脱敏确认本地代理端点；没有输出凭据/其他环境变量。只成功执行以上两次科学请求，没有重复旧完整批量/三扫描。

## 最终测试与真实页面证据
所有Python用现有D:\Anaconda3\envs\simLIBS\python.exe 3.10、-B，cwd=UI；不安装依赖。

```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v
# 在已授权Full Access通道执行浏览器专属集合，现有缓存匹配driver，无下载
$env:SIMLIBS_WEB_BROWSER_TEST='1'
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest tests.test_web_browser -v
# 只检查真实8517页面及已经完成Energy结果，不发新NIST请求
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.ai-workflow\20261002-web-improvements\verify_page.py'
```

- 完整离线集合87项，77执行通过、10浏览器项有意单独启用，23.453s、exit0；旧57项全部包含通过，记录unittest-offline.log。
- 浏览器10项单独全部通过，12.516s、exit0，记录unittest-browser.log。真实CDP左键选区缩小跨度、中键平移、右键复原，亮主题与DPR2画布像素比例，SSE完成/失败/取消和旧尺度保护，以及四项输入/布局/抽样均通过。
- page-evidence/checks.json记录新8517真实页面四种请求/实际inner尺寸和真实wheel；无水平文档溢出，main底部等于inner高度，开始按钮/图表/末日志用scrollIntoView均在视口内。读取同一已完成Energy result，未增加科学请求。

| 窗口请求 | 实际inner | content client/scroll高度 | wheel scrollTop 0→ |
| --- | --- | --- | --- |
| 1366×768 | 1340×612 | 556/896 | 340 |
| 1280×720 | 1254×564 | 508/932 | 424 |
| 1024×768 | 998×612 | 556/1671 | 1115 |
| 1920×1080 | 1894×924 | 868/870 | 2 |

截图page-evidence/home-*.png与scrolled-*.png共8张，light-spectrum.png另1张；实际查看暗1366、窄屏已滚1024、亮稳态，以及全量Energy PNG。截图仅本项目隔离浏览器，不抓用户桌面照片/其他页面，Profile使用独立临时目录，始终quit。

## 8517归属与隐藏重启
精确只读PEB当前目录/ImagePath/CommandLine，配合Get-NetTCPConnection监听PID、首页字节SHA与本地index.html相同、GET/api/jobs全部终态。原PID10504确认为D:\LIBS\simLIBS-2.0.3\UI\web，D:\Anaconda3\envs\simLIBS\python.exe -B server.py --port8517 --no-browser，无活动任务。先保存原completed ID e7a2a65dd38e4cfbab21319e5d372b87，再按精确PID/StartTime身份检查停止，仅WindowStyle Hidden启动本项目绝对server.py，未按python/chrome名字kill。
第一次新PID27644执行两尺度科学验证；导出标题缺字修正后在同样归属/无活动检查下只隐藏重启该PID，最终**PID28112，127.0.0.1:8517**。四份终态记录（旧成功、首次TLS失败、新Photon、新Energy）及全部文件保留，active_jobs=[]。没有停止旧Tk pythonw或用户浏览器/其他服务。
service-owner-before-final.json保存27644重启前状态；service-owner-after.json保存28112最终目录/命令/主页hash/终态；service-new-pid.txt与服务stdout/stderr日志可核对。第一次owner-before文件在部署后只读检查时被新PID检查覆盖，不把该文件当原10504记录；原10504证据为plan/findings基线与本轮两次实际工具输出/上述捕获内容，最终归属以after为准。

## 文件、差异、边缘情况与移交
files.json、final-checks.json列全部基线+新增实现/测试，重算源3项均未变。本轮新业务仅web/sampling.py；其他改动限UI Web/Core适配/绘图/参数兼容层，源simLIBS公式/文件不动。测试新增test_flux/test_web_sampling/test_web_api/test_web_http/test_web_browser与web_browser_support。工作流脚本inspect_service/verify_scales/verify_page仅验证，不是生产求解器。
已考虑：少点原样、各独立网格/离子弱峰/端点、原CSV而非旧preview、显式稀疏/高峰谷预算不足、科学小数不归零、有界tiny ticks、非均匀hover、高DPI；无效/重复元素、空/负/NaN/Inf草稿与指数输入中间态、末项超额/前项上限/单元素/增删/小数/DOM身份；API严格100%、flux默认/非法/旧配置/未知历史、三操作参数透传、已有成功结果与导出ID保护、SSE终态、原已完成结果恢复、精确所属服务检查。
限定：保峰预算不能在任意无限峰谷中保留全部特征；超过预算明确要求缩小波段，拒绝默默扔弱峰或伪造点。NIST原查询自身最小相对强度可能省略未返回的线，UI不编造它们。MOCK/运行前示意不提供物理Flux转换，未知历史不猜尺度；所有真实单位为相对a.u.。GIF证据为两个真实尺度结果对照，未新增扫描请求。独立验收尚未执行，本记录不宣布通过。
本轮完成、停止业务修改，交原planner冻结并交现有原reviewer独立验收，不自行操作其pane。
