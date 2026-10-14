# SimLIBS Vue 真实后端资源

simlibs_ui、web API、源 simLIBS 模块/许可证及 62 份谱线 CSV 复制自原 UI/源库/线库，仅修改 Vue 副本。原样复制 SHA256 见 .ai-workflow/20261013-backend-migration/copied-files.json。data.csv 与 mock_backend 仅测试 fixture，不进入桌面资源，生产禁止 mock fallback。

Windows EXE 自动启动 owned Python，127.0.0.1 系统分配端口、随机 session token、可信 origin，Windows Job Object 管理所属进程树。服务与 worker/浏览器关闭只清理本应用拥有的树，不按进程名清理其它服务。

Python runtime 没有打包。需现有 Python 3.11 及 numpy/pandas/scipy/matplotlib/selenium/requests/beautifulsoup4/webdriver-manager 等原后端依赖。本机可复用 E:/Anaconda/envs/simLIBS/python.exe；可用 SIMLIBS_UI_PYTHON 或设置指定解释器。没有自动安装全局依赖，不保证跨机器无需 Python。

安装后配置、session、驱动缓存、日志及默认 outputs 写入当前用户 app_local_data_dir。backend 本身只读，资源解析使用 Tauri resource_dir。便携 EXE 必须与同目录 backend 一起分发。用户设置输出目录用于新任务存储与另存为起点，已保存任务保留原路径。

local 使用本地 LTE/Saha 科学计算；client 由 NIST dataSticksArray 计算线强、Python 展宽；server 使用 NIST 官方页面计算与展宽。在线模式需网络/Chrome/匹配驱动；错误直接提示，无示意数据回退。所有谱线、参数、manifest/origin、实际 R/Ne 来自真实后台。
