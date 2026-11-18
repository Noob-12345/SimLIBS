# T004 实现交接（冻结待 review）

- taskId：T004；dispatchId：229c687f-8bda-4b35-bea4-2e7841ace916；revision：1。
- 审查基线 HEAD ae4b1d4db01b0042b23bb65f01728494abec5dd2 加本轮未提交五文件；保留既有 T003/T005 dirty，T006 未实施。未 commit/push，未改 task.json/review.md。
- 小步A：新增 backend/simlibs_ui/spectrum_nist.py、backend/tests/test_spectrum_nist.py；修改 backend/simlibs_ui/spectrum_browser.py 的 references 路由，仅接受 source=nist 与 element。
- 小步B：修改 src/lib/spectrumBrowser.ts、src/components/BrowserReferencePanel.vue，增加同排两格的“加载当前谱线库／加载 NIST 在线谱线库”及独立元素候选、查询/刷新/取消、来源与原字段显示。
- requests+bs4 从官方周期表符号链接定位实际 table1 slug，读取 table3/4；固定官方 HTTPS、TLS验证、禁止重定向，校验标题元素/态、HTML类型、连接/读取/整体期限和响应大小，无本地回退。
- 按内层九列表头解析，保留原Å、nm=Å/10、Intensity、Aki及10^8倍率、Energy cm^-1、Configuration、Term、J、Line Ref、Aki Ref及源行号；各状态行独立记录，不推断跃迁配对。spacer/表头/非法行清除波长继承，正常紧邻双行保留；H II无持久线数据明确报缺态。
- 前端区分nist/configured/user，同NIST元素刷新替换旧组并保留关闭态；revision/AbortController保护失败、取消、清空后的旧响应；本地CSV解析及图表组件未修改。
- 后端unit最终7/7通过（unit-tests.log），含spacer后孤立状态不归属回归、正常双行/空值/错误页/缺态/URL/TLS/timeout/大小检查；失败与成功均finally关闭Session。
- 官方HTML夹具核对：Fe I/II计数20/13、Mg I/II计数12/10、H I计数14；H II明确无可读取持久线数据，记录parser-check.log。
- 真实HTTPS证据 live-nist.json：Fe I/II及Mg I/II均HTTP200，保存URL/获取时间/HTML SHA256/首条完整字段；捕获HTML在fixtures/，mock unit与真实HTTP明确区分。
- browser-check.json短版真实检查PASS、errors=[]、failed=0：真实File导入240–450nm隔离CSV，两个入口同row、440px无溢出，实际输入/候选Fe后查询I/II、metadata URL/hash、自动加入Fe、刷新仍两组。
- 浏览器原成功记录中的ownedChromeStopped=false属于旧call忽略socket参数的夹具清理错误；已修正并单独运行cleanup-check.json，Chrome/API均确认退出，errors=[]/failed=0。旧成功记录未篡改为清理通过。
- npm run build通过（build.log）；最终修复后tauri build --bundles nsis退出码0（desktop-build.log），beforeBuild类型检查/前端构建通过，生成最终release及NSIS；先前修复前包已被替代。
- 未执行collect，未关闭用户程序；dist-desktop根目录仍为既有版本，不能作为本轮NIST交付。最终release路径与hash见final-files.json，收集待协调安排。
- 220项范围外保护hash匹配，T003页面/T005图表图标未覆盖；git diff --relative --check退出码0；最终源码/证据hash见final-files.json，实际差异见final-source.diff（含新增文件）。
- 未测边界：完整本地+用户CSV+NIST共存及关闭II刷新、失败/取消/清空防旧响应、实际虚线命中tooltip仍需review定向复验，未将其标为行为通过；原生WebView2 GUI、对话框、NSIS安装及屏幕阅读器亦未测。

IMPLEMENTATION_READY taskId=T004 dispatchId=229c687f-8bda-4b35-bea4-2e7841ace916 revision=1

源码及release产物冻结，停止写入，等待独立review；本报告不是验收通过结论。
