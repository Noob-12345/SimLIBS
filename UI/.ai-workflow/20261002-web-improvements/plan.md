# Web五项改进执行方案
状态：规划完成，交现有coder逐项执行，再交现有reviewer独立验收。用户已授权直接修改，不要求二次方案批准。

## 目标、证据与固定边界
- 目标当前web/主页，保留用户黑红/亮色主题、动效、SSE、Canvas三键交互；原simLIBS源目录保持不动，必要能力仅在UI适配层添加。
- 同一Herdr simlibs-ui/w1:t1：planner协调，原libs_coder编码，停止后原libs_reviewer验收。禁止新agent/pane/终端窗口。
- 本轮baseline.json保存33项现有Web/核心/测试哈希；source-baseline.json保存源3项；尊重用户刚做的修改。
- 当前Web取manifest.preview≤1500，再把扫描减至400；原数据已在完整CSV中，不能只升显示常量或把稀疏旧预览补点假装更多原数据。
- 实际headlessChrome基线baseline-page.json及四张图：1366×768实际inner1340×612，main933、content877且scrollTop300请求仍0，下方runBtn887；body隐藏溢出和flex/grid自动最小高度组合导致裁切。
- .comp-el强制uppercase；配比代码用||0并只提示总和，不按末元素自动平衡。
- 官方表单GET200确认Energy flux int_scale=1（NIST默认），Photon flux int_scale=2（当前源库固定值）；LIBS/Lines官方帮助明确相对单位及光子能量加权。
- 引用：https://physics.nist.gov/PhysRefData/ASD/LIBS/libs-form.html；https://physics.nist.gov/PhysRefData/ASD/Html/libshelp.html；https://physics.nist.gov/PhysRefData/ASD/Html/lineshelp.html。

## 用户可观察的结果（按1→2→3→4→5）
1. 单次默认显示预算6000点、扫描每帧2000点（数据不足则原样）；从完整CSV读数并采用保峰抽样保留端点/窄峰，不人为平滑或制造新科学数据。移除不必要的波长/强度小数截断。高DPI图清晰、线宽/光晕适度。完整导出不减采样。
   处理原始/插值数据时不得把同一插值数组的点画成“真实raw”；若同时展示离子分量，应有各自的实际数据/波长，不能把Sum(calc)标成单个ion。可向旧xs/ys接口兼容地新增真实序列。
2. 主页内容在视口内合理分配，内容区真能上下滚动；小宽度变为可读布局，按钮/日志/图表均能通过滚动访问，无水平大幅裁切；保留侧栏与主题。
3. 显示/输入/提交均采用Fe、Si、He这种合法元素符号；删除CSS强制大写，输入FE/fe可在提交/失焦时规范化成Fe，不猜测无效符号；复用周期表校验，避免重复符号。
4. 末元素是余额项，始终100减前项和。前两项总99，末项填2→1并明确toast/内联提示超额；改前项后末项自动增减，总和不足也补足末项。
   末项减少到0仍超额时，仅限制本次编辑前项至其他前项剩余额度，保留其他项且提示，禁止负比例或静默缩放整个组成。单元素100；增加/删除/预设/失焦均保持合法规则。
   不在每次输入时重建整个DOM导致光标/焦点丢失。空值/负数/NaN/Inf为无效草稿，明确显示并阻止请求，不用||0吞掉。用户正常清空再输入可以完成；API仍严格100%校验。
5. 加入Photon flux / Energy flux选择，默认photon保持旧源参数int_scale=2；energy实际请求NIST int_scale=1。单次、批量、扫描透传，返回/来源JSON/PNG/GIF轴标签都标真实强度尺度与a.u.，不宣称绝对标定单位。
   用适配层UISimulation.get_site覆盖/构造真实URL参数，仍调用原SimulatedLIBS构造与getter，不改源文件；不能只在前端改标签、直接事后乘总谱或伪造转换。
   切换控件只影响下次运行/示意预览；已有结果保持原数据和原尺度标签直至新结果成功。旧配置/历史缺字段保持兼容，历史未知尺度须说明未知，不能猜成energy。

## 实现小步（每小步最多3业务文件；测试/工作流记录同步）
- 1A：web/sampling.py（可新增）、web/real_backend.py、web/static/app.js：完整数据显示/保峰抽样/独立实际序列、扫描密度，先用窄峰/弱峰/不等波长/少点用例复现旧稀疏缺陷再修。
- 1B：web/backend_api.py、web/static/index.html、web/README.md：显示预算与提示契约统一（必要时分更小步）。不改变物理计算点数上限200000及Core旧Tk预览策略。
- 2：web/static/style.css、index.html、app.js（只需的文件）：min-height/min-width/overflow与响应布局/resize重绘；先断言旧scroll0和被截控件，再验证实际wheel/page滚动。
- 3：style.css、app.js：元素大小写及输入规范化、无效/重复校验；先复现Fe显示FE，后检查真实输入值/CSS/请求body。
- 4：app.js及可选composition.js/index.html（最多3）：末项余额/上限调整/提示与输入草稿，先测试99+2、更改前项、前缀超过100、删增行/单元素/小数容差/空负NaN，后实现。
- 5A：simlibs_ui/models.py、adapter.py（2）：强度尺度枚举/default photon、源URL参数与真实来源记录；旧57测试保持通过，mock HTTP捕获两模式int_scale。
- 5B：web/backend_api.py、real_backend.py、mock_backend.py（3）：请求/默认参数/结果/批量扫描透传及明确MOCK语义；不得默认从代码物理转换真实结果。
- 5C：web/static/index.html、app.js、style.css（最多3）：选择器、标签、图例和保留旧结果尺度、正确Y轴数值格式。
- 5D：simlibs_ui/plotting.py、web/README.md及必要第三文件：完整PNG/GIF读取manifest真实尺度，旧history未知兼容；是否需Tk额外入口不在本轮重点，不破坏旧GUI。
- 收尾：更新本目录implementation.md、文件清单、测试/截图证据，coder停止业务修改交planner；有review问题仍原coder小步修复、原reviewer复验。

## 可操作验收
- 复用Python3.10/unittest、已有Chrome/Selenium。Browser运行时无实例(list=[])已证实，不装新框架；隔离headless只控制本地页面，截图只含本项目，不读取用户profiles/cookies。
- 补Python抽样/flux/API单元测试与Selenium真实Web交互回归；默认不请求外网。旧unittest完整复跑保证科学CSV严格性、取消关闭/进程隔离无回归。
- task1：完整谱超过1500时返回真实更多点（上限6000），扫描超过400返回更多点（上限2000）；窄峰/弱峰幅度和位置保留、无新增数值、端点排序正确；稀疏真实NIST不伪装高采样。
- task2：1366×768、1280×720、1024×768、1920×1080以及实际inner尺寸；content.scrollTop实际能改变，真实wheel可到开始按钮/末日志；图无横向裁切，滚动不改变任务/旧结果。
- task3/4：实际键盘编辑Fe/FE/fe、80+19+2→80/19/1、更改前项→末项缩减/增加、前缀>100处理、增加删除、single100、小数、空/负/非有限拒绝；检查提示、focus/selection稳定与真正发送API payload=100。
- task5：mock传输断言int_scale1/2和来源一致，Single/Batch/Scan不同模式透传；实际NIST至少两种模式各一次（可用H400–700nm含多条线或其他小谱，不向外网发送无效极端值），不锁绝对强度，核对非空finite和不同谱线相对权重变化。
- 校验SSE完成/失败/取消、旧成功结果与flux标签保留、static无离子、新旧配置/历史兼容、PNG/CSV/JSON/GIF全量与尺度标签。新增Node/浏览器测试若已有工具可用就复用，不安装jsdom/Playwright依赖来走捷径。
- 本地8517可能正在使用：检查GET/api/jobs无运行中任务且首页字节/进程命令属于本项目后，才停止精确PID并隐藏重启原服务；不按python/chrome进程名kill，不开终端窗口，不重开agent。
- 原reviewer逐项重新运行检查、看截图和科学来源、重算源码3哈希，写review.md通过/需返工/受阻；未验证项必须具体说明。planner持续到完整交付，保存completion.md。
