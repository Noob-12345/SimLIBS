# 已有证据
- 原29项桌面实现/测试/说明和原源库3项SHA256仍与上一轮冻结一致，web/design为用户新增层，本轮须新增Web验收。
- web.real_backend只读manifest.preview（最多1500）并把扫描每帧再减至400；只升前端常量不能找回已丢失的点。需要从完整CSV读取合法显示数据并保峰抽样，不能插值冒充原始数据。
- style.css body overflow:hidden；#app height100vh，#main/#content缺少min-height:0，固定侧栏/340px输入列。滚动需实际几何复现。
- style.css .comp-el text-transform:uppercase直接使Fe显示为FE；前端目前input空值用||0、只updateSum不自动余额，需要改为严格校验和明确余额逻辑。
- NIST官方表单HTML实际GET200：energy radio int_scale=1（默认），photon radio=2；源库get_site固定&int_scale=2。官方LIBS帮助与Lines帮助说明为相对单位，energy按光子能量加权。
- 官方链接：https://physics.nist.gov/PhysRefData/ASD/LIBS/libs-form.html；https://physics.nist.gov/PhysRefData/ASD/Html/libshelp.html；https://physics.nist.gov/PhysRefData/ASD/Html/lineshelp.html。
- Browser技能已读，运行时成功初始化但getForUrl无可用浏览器，按bootstrap文档list=[]。使用已安装Selenium/Chrome隔离headless仅检查localhost页面，不启动终端/新agent。
- 当前8517监听PID10504，命令D:\Anaconda3\envs\simLIBS\python.exe -B server.py --port8517 --no-browser，须重启前再次确认具体项目cwd/脚本归属。
