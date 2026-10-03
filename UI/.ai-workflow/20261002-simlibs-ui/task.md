# simLIBS 桌面 UI 任务
用户原始目标：按照 D:\LIBS\herdr 中 multiagents 原则运行，并将整个 simLIBS 封装为可生成 LIBS 模拟光谱的 UI。
已确认：本地 Windows 桌面窗口；用户允许本会话从外部控制 Herdr。
目标项目：D:\LIBS\simLIBS-2.0.3\UI
源库：D:\LIBS\simLIBS-2.0.3\simLIBS-2.0.3
协作：Herdr 独立会话 simlibs-ui；workspace w1；tab w1:t1；规划 w1:p1、编程 w1:p2、验收 w1:p3。必须通过真实独立 agents 顺序交接。
源库功能：SimulatedLIBS 构造参数、static/dynamic 获取、raw/interpolated/ion 光谱、CSV 导出、create_dataset、resolution/temperature/density animations。
现有 Python：默认 D:\Anaconda3\python.exe 为 3.7，不适用源库 match 语法。使用 D:\Anaconda3\envs\simLIBS\python.exe（3.10.20），已有 tkinter/matplotlib/pandas/numpy/scipy/requests/bs4/selenium/webdriver_manager/Pillow。无 pytest，可使用 unittest。
初步实现建议：tkinter/ttk 原生桌面 GUI + Matplotlib 嵌入绘图；复用真实源库，通过 service 适配层处理参数、线程、超时与友好错误。中文 UI，完整覆盖单次模拟、离子分量、批量数据集、参数扫描及动画、导入/导出、配置、启动脚本和说明。
计划应检查 NIST 网络依赖，不把离线示例称为新生成的科学模拟。禁止覆盖源库用户修改；优先只增加 UI 目录下文件。如必须修改源库，先向协调者给出可复现证据。
工作流记录：本目录 plan.md、implementation.md、review.md；审查发现问题交原 coder 修复，再由原 reviewer 复查。
