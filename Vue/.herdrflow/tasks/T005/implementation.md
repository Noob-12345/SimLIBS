# T005 实现报告（冻结待 review）

- taskId：T005；dispatchId：16a6adbb-5162-4d9f-a23d-44b91e20f0e1；revision：1。
- 仅修改两个允许业务文件：src/components/AppIcon.vue、src/components/BrowserSpectrumChart.vue。未修改脚本功能、T003 页面、controller、数据、后端、Rust、依赖或历史证据。
- AppIcon 新增四向十字箭头 cross-arrows 和上下双向箭头 vertical-arrows SVG path。显示全局/自适应强度替换为 AppIcon，重置保持不变；三个轴按钮统一 icon-btn，保留原 title、aria-label 与 click 函数。
- 移除轴按钮的文字 btn/窄屏 flex:1 拉伸样式；三个按钮保持与 reset 同 33×33，默认 SVG 18×18，边框/圆角/hover/focus/间距沿用 icon-btn。
- npm run build：退出码0；最终脚本为三宽度最小 CDP 检查。1360/440/360 均 PASS，checks=3，errors=0，failed=0。DOM 断言覆盖四向/上下路径、三个按钮33×33、SVG18×18、title/aria、样式一致、无溢出和 reset/global/adaptive 功能。
- 最终 tauri build --bundles nsis：退出码0；release EXE 与 NSIS bundle 生成成功。未运行 collect，因为用户运行中的根目录 EXE 保持不关闭；dist-desktop 根目录既有 T003 产物保持不变。
- T003 页面保护 hash：8f1cd1f84e61a5a3bdee53d2c8f048c97c0ac7bf0c5bee0f141030a105ac931d；根目录 EXE：8946bb31c78821e9370b2866109951a496a60f9b34ab65026ca59ea7e802a1a5；NSIS：dfb5b13e1345fc9ae0b936f825573f6882af0960a0ab4387dc2e7a0a3e848a76。
- T005 源码 hash：AppIcon.vue 3740cc164626481a805b5dc3709c4996b930bef83deac0ac42e5c6b215dd5752；BrowserSpectrumChart.vue cd9ece43e63293047a8e46853c7bd8f6b31a39cbafe3d74e00df5f61752c6d41。
- git diff --relative --check 通过。实际业务 diff 含本轮两个允许图标文件和既有 T003 页面 dirty；未提交、未 commit、未 push。
- 未测边界：最终 EXE WebView2 原生 GUI、文件对话框、NSIS 安装过程；本轮也未重新收集根目录产物以避免关闭运行中用户软件。

IMPLEMENTATION_READY taskId=T005 dispatchId=16a6adbb-5162-4d9f-a23d-44b91e20f0e1 revision=1
