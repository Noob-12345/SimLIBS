# T004 独立审查报告

- 结论：**pass**
- taskId：T004
- dispatchId：229c687f-8bda-4b35-bea4-2e7841ace916
- revision：1
- 审查对象：HEAD ae4b1d4db01b0042b23bb65f01728494abec5dd2 加五个允许文件的冻结 diff。

## 审查依据

已独立读取 brief、task.json、implementation.md、final-files.json、baseline.json、live-nist.json、official HTML、7 项 unit 日志、browser-check.json、cleanup-check.json、build.log、desktop-build.log 和实际 git diff --relative。五个业务文件的实际 SHA256 与 final-files.json 一致；220 个保护文件实际校验 bad=0，git diff --check 通过。T003 页面、T005 图标/图表与既有 dirty 产物未被本任务覆盖，T006 仍未实施。

## 审查结论

未发现当前冻结实现中需要返工的明确功能缺陷。

1. spectrum_nist.py 使用官方周期表元素链接定位实际 slug，再访问 table3/table4；固定官方 HTTPS Handbook 路径，校验 HTTPS、域名、路径、Content-Type、禁止重定向、TLS、connect/read/整体 deadline 和 HTML/JSON 大小限制。title 必须匹配 Persistent Lines 及元素/I/II 身份，错误页、空表和缺态不会被当作成功。
2. 解析选择具备九列表头的内层数据表，跳过嵌套布局表与 spacer。当前实现已在非数据行、空行、非法行时清除 current_wavelength；新增的 spacer 后孤立状态 fixture 单测通过，正常相邻双行仍保留。原 Å、nm=Å/10、Aki 表头倍率、Energy cm^-1、Configuration、Term、J、Line Ref、Aki Ref、原始行号和 HTML hash 均保留，空 Aki/引用不补造。
3. 实际 HTTPS 证据覆盖 Fe I/II 与 Mg I/II，均为 HTTP 200，title、URL、获取时间、HTML SHA256、首条原字段和状态计数可追溯；H II 缺态被明确报告。捕获数据与真实 HTTP 证据区分清楚。
4. 前端新增同排的本地库/NIST入口和独立元素候选；browser-check 在窄屏 440px 验证无溢出，真实 File 隔离数据加载 Fe I/II、来源 metadata、自动加入和同元素刷新去重通过。originKind 区分 configured/user/nist；同元素 NIST 刷新替换旧组，已有来源保留。
5. referenceRevision、AbortController 和 clear/cancel 的 revision 保护可阻止迟到响应回填；本地库和用户 CSV 的现有路径保留。cleanup-check 确认 Chrome/API 均退出，修正了旧 browser-check 记录中仅由夹具清理错误造成的 ownedChromeStopped=false，未篡改旧证据。

## 证据与限制

- 7/7 后端 unit tests 通过，含 nested/spacer/双行、空字段、错误页、缺态、slug/URL、TLS/重定向、timeout、响应大小和 deadline。
- browser-check 短版为 PASS、errors=0、failed=0；cleanup-check 为 errors=0、failed=0 且 Chrome/API 已退出。
- 前端 build 和最终 tauri build --bundles nsis 均 exitCode=0。未执行 collect；用户 EXE 仍占用时未覆盖根目录产物，release bundle 不被报告为本轮根目录交付。dist-desktop 仍是既有 T005/T003 版本。
- implementation.md 明确未完成失败/取消/清空共存、完整本地+用户 CSV+NIST 共存及关闭 II 刷新、实际虚线命中 tooltip 的独立行为验证；本报告保留这些限制，不把它们列为已通过。源码审查显示 revision/来源隔离路径具备保护，但上述界面组合仍需后续定向验证。
- 未测试最终 EXE 的 WebView2、原生文件对话框、NSIS 安装和屏幕阅读器播报。

## 冻结 SHA256

| 文件 | SHA256 |
| --- | --- |
| backend/simlibs_ui/spectrum_nist.py | 372dc21699f24ead352d0747cec74cdf6d1cf4209a76b66258887fe2678afa5f |
| backend/simlibs_ui/spectrum_browser.py | 207214f61b86dc7da83167f7242d64b8a9f43f17269688900e04bd37309a40dd |
| backend/tests/test_spectrum_nist.py | 34dec9e425b2620819cc1af9493c0e05db3ec013ee7355c3cafcba52c473ebe2 |
| src/lib/spectrumBrowser.ts | 2ab35242799add5e70b9387e71a9ac536e0171b36e0d74ec6555b77c91a24bf6 |
| src/components/BrowserReferencePanel.vue | fbee40adb44704ba5c470e1beee79513e0c69c91e09581a671d6039d922230cd |
| release EXE | 91bc9d2f9bc37589d96f3aa7e16c2810a3b8b5c3f95b2838e5b72db5e6fa3352 |
| release NSIS | d3f879fbd9e66df00ef548a5c38556a3470c7f04c39b35e267b487ecec2fe240 |
| 根目录 EXE（既有产物） | 4f3c96b0e5891e693e3c259cd60e06d71d6844fe33c8174dc83b146f7537ba5b |
| 根目录 NSIS（既有产物） | 3151fa632c7230af718c4f8c8d66b9cac09fb4d2adfb408b80deb06ebf6b6d2e |

REVIEW_COMPLETE taskId=T004 dispatchId=229c687f-8bda-4b35-bea4-2e7841ace916 revision=1 verdict=pass
