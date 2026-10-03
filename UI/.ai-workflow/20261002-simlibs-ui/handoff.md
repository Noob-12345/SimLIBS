# 协调权交接：由 Herdr libs_planner 接管

## 用户最新指令
用户明确要求：让 Herdr 里的 planner 代替外部会话的工作，不希望开多个窗口。后续由 libs_planner 在同一个 Herdr 窗口内持续协调整个实现、独立验收与返工；外部协调会话在确认接管后结束。
本指令覆盖旧计划末尾的“规划 agent 写完计划后停止”。你现在负责规划兼协调，仍不写业务代码。

## 已有真实会话和 agent
Herdr binary: D:\herdr\herdr.exe（0.9.3）
Session: simlibs-ui；workspace w1；tab w1:t1。
规划兼协调：libs_planner / w1:p1 / Codex会话01a0fb75-a8fb-7090-94fe-90d6c5687f2e。
编程：libs_coder / w1:p2 / Codex会话01a0fb77-f8fa-7421-8f55-bb320f74af6c，当前正在实现，任务已送达。
验收：libs_reviewer / w1:p3，已启动，等待实现完成才开始检查。
这些ID和名称都来自真实CLI响应，禁止再次创建会话、pane、worktree或agent；不得启动新终端窗口。
所有控制命令明确使用 D:\herdr\herdr.exe --session simlibs-ui，不依赖用户当前焦点。

## 路径与授权
UI目标：D:\LIBS\simLIBS-2.0.3\UI；源库：D:\LIBS\simLIBS-2.0.3\simLIBS-2.0.3。
用户已确认本地桌面UI，明确授权实现和外部Herdr控制，并已开启Full Access。不再询问方案批准。
任务目录：.ai-workflow\20261002-simlibs-ui。
读 task.md、plan.md、coder-task.md、coordinator-notes.md、reviewer-task.md、source-baseline.json，以及根目录 task_plan.md/progress.md。
现有Python：D:\Anaconda3\envs\simLIBS\python.exe 3.10.20，已有tkinter/Matplotlib/pandas/numpy/scipy/requests/bs4/selenium/webdriver_manager/Pillow，无pytest。默认Python3.7不适用。
不修改源库，源库3个Python文件SHA256已记录；代码和验证产物只在UI目录。用户现有文件不可误删。

## 接管时实际进度
规划完成（plan.md已核对）。libs_coder 正在执行：已有 run_ui.py、simlibs_ui/__init__.py、models.py、settings.py、storage.py；测试已有test_models.py、test_storage.py、test_adapter.py。
模型/存储层已实现并被coder运行测试；adapter测试处于预期失败阶段，模拟适配层、后台任务与完整GUI仍在开发。不能把骨架或“working/done”状态说成全功能完成。
reviewer尚未收到验收任务。implementation.md/review.md还未生成。
独立真实源库静态H100%、650–660nm已验证成功：HTTP200，raw47行，interpolated2000行，max1802（只作既有证据，不锁定未来NIST数值）。
NIST当前动态控件：input id/name=resolution；button name=recalc、ViewDataCSV；需显式--headless=new。Chrome154，现有缓存最高152，驱动匹配和真实动态仍待验证。
最初coder模型连接短暂重试后恢复；直连端点与现有127.0.0.1:7890代理均可建立连接，不需修改用户全局代理/model设置。

## 必须持续完成的协调工作
1. 首先确认接管，在本目录写 handoff-ack.md：接管人、真实coder/reviewer状态、当前阶段及下一步。读取必要记录即可，不重复全量规划或探测。
2. libs_coder正在工作，先用 agent get/read 查看，不重复发送原始实现任务。用 agent wait libs_coder --timeout 30000 分段等待，每次超时核对状态与新增产物并继续。必要时有证据地提供具体纠正指令，不抢写业务代码。
3. 不把 idle/done 当作实现完成。实现交接必须存在真实业务代码及implementation.md，核对功能和实际检查输出。若缺失或coder早停，将明确未完成项交回同一coder，让其继续。
4. 代码和实现记录齐全后，再用 agent prompt libs_reviewer 将原始需求、plan.md、implementation.md、reviewer-task.md、真实代码与source-baseline.json交给独立reviewer。等待review.md；此阶段coder停止修改，避免读写冲突。
5. review.md为需返工：把可定位问题交回原libs_coder，修复后让原libs_reviewer复查，直到通过或出现确实外部阻碍。不得以自己或coder的结论代替独立验收。
6. 独立验收核对真实Tk窗口/三个工作页、非法参数零请求、后台响应、取消关闭与所属进程清理、CSV/PNG/JSON/GIF、真实H静态、size2批量、Te/Ne/R各2帧扫描、动态离子尝试。网络/驱动导致未验证时记录准确范围，不虚构通过。
7. 维护根目录task_plan.md/progress.md及任务记录；最终在Herdr的planner pane向用户报告启动方式、功能、验证证据、独立验收结论和剩余限制，链接plan/implementation/review，并写 completion.md。用户只需保留一个Herdr窗口，最终应用窗口可在验收完成时展示；测试辅助窗口优先隐藏/自动关闭。
8. 持续推进到完整UI交付。不要在仅确认接管、发出一个prompt、等到一次timeout、写完一个记录后结束任务。若CLI出现额度/权限/认证阻碍，先读实际输出；不要擅自批准危险操作或改全局设置，明确记录具体阻碍及已完成状态。

## 已准备的CLI形式
D:\herdr\herdr.exe --session simlibs-ui agent get libs_coder
D:\herdr\herdr.exe --session simlibs-ui agent read libs_coder --source recent-unwrapped --lines 60
D:\herdr\herdr.exe --session simlibs-ui agent wait libs_coder --timeout 30000
D:\herdr\herdr.exe --session simlibs-ui agent prompt libs_reviewer <验收任务文本>
D:\herdr\herdr.exe --session simlibs-ui agent get libs_reviewer
所有超时只表示等待未完成，不能盲目重复发送prompt。
