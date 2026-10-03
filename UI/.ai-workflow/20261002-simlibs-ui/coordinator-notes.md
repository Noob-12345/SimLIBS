# 协调者独立核对证据
2026-10-02：使用 D:\Anaconda3\envs\simLIBS\python.exe，真实请求 NIST H=100%、Te=1 eV、Ne=1e17、650–660 nm、R=1000，HTTP 200，HTML 含 var dataDopplerArray。
直接调用原始 SimulatedLIBS（仅本进程给 requests.get 加 timeout=25；源库未修改）成功：raw=(47,2)，interpolated=(2000,2)，波长650–659.995 nm，最大强度1802.0。
NIST 官方说明：https://physics.nist.gov/PhysRefData/ASD/LIBS/libs-form.html。百分比代表总原子数密度中的占比，所有组分之和应为100%；源库验证仅拒绝>100，不够严格。UI应要求总和100（容忍小浮点误差），允许零占比列用于数据集，逐行检查有限值、非负、元素符号和name。
推荐界面：左侧参数和元素配比，右侧Matplotlib图与数据表，单次模拟/批量数据集/参数扫描动画三个工作页。中文标签，清楚区分光谱分辨率R与重采样步长nm。使用微软雅黑/系统字体，窗口尺寸适应用户屏幕，后台任务进度、取消、失败恢复、CSV/PNG/JSON/GIF输出。离线导入/已有示例明确标记来源。
动态模式与离子分量必须实际适配现有Chrome/Selenium，不只放出不可用按钮；如外部依赖导致无法验证，在实现记录和验收中写出真实限制。
