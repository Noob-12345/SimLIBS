# 独立规划 agent 源码证据

- task.md：默认 Python 3.7 不适用；使用 D:\Anaconda3\envs\simLIBS\python.exe 3.10.20；不装 pytest，使用 unittest。
- planner.md：只写计划和证据；计划写入 .ai-workflow/<任务>/plan.md；编码及验收由独立 agents 执行。
- README：公开功能为 SimulatedLIBS 参数、static/dynamic、raw/interpolated/ion、CSV、create_dataset、Te/Ne/分辨率动画。
- simulation.py：构造即联网；static requests.get 缺 timeout，verify=False；返回 HTML 找 dataDopplerArray，CubicSpline 默认 0.005 nm。
- simulation.py：dynamic 使用 ChromeDriverManager().install()、Selenium Chrome、固定 XPath 及 CSV 窗口；ion 数据仅动态获取可用。
- simulation.py：validate_simulated_libs 未覆盖零 Ne、空 composition、负百分比、非有限值、分辨率等；Ne=0 会在 log10 失败。
- simulation.py：create_dataset 以 size 创建线程，composition 最后一列依赖 name，构造使用固定默认波长/分辨率；需要适配层提供受控排队、输入规范化和同网格检查。
- simulation.py：Ne 被保存为字符串，__repr__/__str__ 使用数值格式，UI 不应以 str(libs) 构建摘要。
- animation.py：get_intensity 固定动态获取、max_ion_charge=3，zip 静默截断；归一化除以最大值，零谱会产生 NaN；animate_* 使用全局 pyplot、固定路径和 imagemagick。适配扫描与 Pillow GIF，逐帧仍调用真实 SimulatedLIBS。
- tests/test_SimulatedLIBS.py：pytest 测试依赖真实网络，部分硬编码谱值；当前环境缺 pytest。UI 新增 unittest mock 本地传输/浏览器，不运行这些测试来声称离线验证通过。
- 环境实测：Python 3.10.20、tkinter/Matplotlib/pandas/numpy/scipy/requests/bs4/selenium/webdriver_manager/Pillow 均可发现；从 UI 目录找不到 simLIBS 包，需要启动器按源目录定位导入。
- Chrome 实测存在于 C:\Program Files\Google\Chrome\Application\chrome.exe；驱动是否匹配仍需检查。
- data.csv、tests/data.csv：3×4，W,H,He,name，所有组分行合计 100%。
- docs/single_simulation.csv：8000×3，包含历史索引列；docs/output.csv：100×8007，历史批量宽表；saved/03124_95.csv：70587×2，wavelength,intensity。都只能作为已保存数据。
- saved/contents.csv：13×18，首列含前导空格的 samples，组分列 *_at%；不是原 create_dataset 标准输入，需显式导入映射及总和校验，不能悄悄补差到最后一种元素。
- 根目录 task_plan.md/findings.md/progress.md 属协调者已有记录，保持不动。
