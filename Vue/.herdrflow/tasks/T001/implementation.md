# T001 实现报告（冻结待 review）

- taskId：T001
- dispatchId：8e243d04-0640-4f35-841b-efb28c7198b6
- revision：1
- owner：implementer（code）
- 被审查基线 HEAD：43e2818b700f505de49de25d2c07d3912b5ce6f4
- 被审查版本：上述 HEAD 加本任务两个组件的未提交 diff。未创建提交；Git HEAD 不能单独代表本轮实现，审查应结合实际 git diff、numstat 和下列文件哈希。
- 当前状态：实现、自测、前端构建和桌面构建完成；本报告写入后停止修改业务源码与交付产物，等待 reviewer 独立审查。

## 实际修改

业务源码只修改以下两个允许文件，每个业务小步最多两个业务文件。

1. src/components/BrowserSidebar.vue：删除侧栏收起/展开按钮、Teleport、折叠状态绑定、折叠定位监听、inert 和 aria-hidden 控制；保留 controls 与结果插槽、桌面两列布局和窄屏自然纵向布局。未引入参数区限高或内部滚动。
2. src/components/BrowserSpectrumChart.vue：新增完整横轴上的当前可见曲线全局强度范围，并让主图横向滚轮、框选、Shift/中键平移及概览联动只更新横向选区。新增“显示全局”和“自适应强度”操作按钮，提供 title 与 aria-label。自适应按钮只在点击时按当前选区内真实节点及两端必要的线性插值计算有限 Y 范围并保存，后续横向操作保持该范围；概览始终使用全局 Y。显示全局、Home、Escape、右键统一清除自适应并恢复全横轴和全局 Y，即使当前已经是全谱也显式重绘。空/无有效曲线、负值、全零、常量和零宽选区均有有限范围兜底，避免 NaN、Infinity 和空白崩溃。新光谱或处理视图变化时清除旧自适应范围；曲线隐藏/恢复不自动清除已锁定范围，再次点击自适应才按当时可见曲线重算。补充画布与概览说明，并使窄屏图例和操作按钮分行。

未修改导入控制器、真实测量数组、参考线数据、处理算法、后端、Rust/Tauri 权限或依赖；保留图例隐藏、峰标记、参考线提示、逐节点读取和拖拽交互。

## dist-desktop 交付

最后一次 npm run desktop:build 已成功更新项目根目录 D:/LIBS/SimLIBS/Vue/dist-desktop/，没有创建版本子目录：

- dist-desktop/SimLIBS.exe：Windows x64 应用，5,142,016 bytes。
- dist-desktop/SimLIBS-Setup.exe：NSIS 安装包，6,007,411 bytes。
- dist-desktop/SHA256SUMS.txt 与 dist-desktop/artifact-manifest.json 已同步更新。
- 收集流程成功复制并校验既有 backend 白名单资源；backend 源文件和数据未修改。
- 最后一次构建包含窄屏图例布局修正；此前较早构建生成的产物已被最后一次构建替代，不作为审查版本。

## 实际验证

### npm run build

build.log 记录最终 npm run build 退出码 0。vue-tsc 类型检查通过，Vite 生产构建通过，106 modules transformed；最终资源为 index-DHL3y1TE.css 和 index-AKoZvB45.js。

### behavior-check.json

behavior-check.json 的 dispatchId 为 8e243d04-0640-4f35-841b-efb28c7198b6、revision 为 1，failed 为 0，errors 为空，Chrome/API 隔离进程均已退出。监督检查确认本轮 9 项行为验证均通过；实际 JSON 的 checks 数组按 7 个汇总检查组记录，7 组全部 PASS，每组覆盖一个或多个验收行为：

1. 真实文件导入；1360、440、360px 下无横向溢出，侧栏没有收起入口且始终可见，图表和两个按钮均可用。
2. 全局 Y 不随滚轮缩放、框选、Shift 平移、中键平移和概览联动变化；自适应点击后 X 保持选区，Y 锁定并贯穿这些操作；概览仍使用全局尺度。
3. 显示全局、Home、Escape、右键均恢复全 X 和全局 Y，重复全谱重置也会重绘。
4. 隐藏曲线不参与点击时自适应；恢复曲线后保留已锁定 Y，原测量数组不变。
5. 真实参考库加载 62 组，参考线命中详情包含原行和 Aki；真实本机处理 API 的处理结果、背景视图和原始视图均保持连接。
6. 选区外巨大峰不进入自适应范围；有节点和无内部节点的选区边界插值均通过；重复波长产生有限绘图坐标。
7. 负值、全零、常量、空轴、无曲线和全部隐藏均产生有限有效 Y 范围，没有 NaN、Infinity 或绘图崩溃。

测试数据仅存在 T001 任务目录，明确标为隔离 UI 夹具，不是科学模拟或实验计算结果；真实参考和处理调用沿用既有 API。

### npm run desktop:build

desktop-build.log 记录最后一次 npm run desktop:build 退出码 0：beforeBuildCommand 的前端构建通过，Tauri release 编译完成，NSIS bundle 完成，dist-desktop 根目录收集完成。未关闭用户进程，未执行安装包安装验收。

### 范围核对

最后一次 git diff --check 退出码 0。最终源码 diff 的 git diff --numstat 为 2 16 src/components/BrowserSidebar.vue 和 55 13 src/components/BrowserSpectrumChart.vue；业务 diff 只有：

- src/components/BrowserSidebar.vue
- src/components/BrowserSpectrumChart.vue

桌面构建授权更新了以下根目录交付产物：

- dist-desktop/SimLIBS.exe
- dist-desktop/SimLIBS-Setup.exe
- dist-desktop/SHA256SUMS.txt
- dist-desktop/artifact-manifest.json

src/pages/SpectrumBrowserPage.vue、src/lib/spectrumBrowser.ts、package.json、package-lock.json、src-tauri 和 backend 未出现在业务修改 diff 中。

## 最终文件哈希

以下为最后一次核对的 SHA256，按文件原始字节计算。

| 文件 | SHA256 |
| --- | --- |
| src/components/BrowserSidebar.vue | 0ca376466c59150ab113d80e9eda298e37e05115c368f3d1614ad3ec314c670f |
| src/components/BrowserSpectrumChart.vue | 8a0e12cddb32b3beca5b5b2417d653458cf8ae260d667618d15bff85f5b0d284 |
| dist-desktop/SimLIBS.exe | 824a7480ab5792a094a8829f818365c750238fcc06407c74f56672cd0ce461f6 |
| dist-desktop/SimLIBS-Setup.exe | 252107dbf3c336ad8c34ec0939aeb41d68f190bc7030899c7c4903069af66df1 |
| dist-desktop/SHA256SUMS.txt | 4e6df5e2a2ea69635c987ac6aa7bd93b5b1c524c2e083b860997784655eca369 |
| dist-desktop/artifact-manifest.json | 352452335d1ca630b0a67b06ae088a59004f7911f396e3ecd48a59a08b3e5998 |

边界文件只读快照哈希：

| 文件 | SHA256 |
| --- | --- |
| src/pages/SpectrumBrowserPage.vue | ba2a1ee98660ecb17157dfc21e44efaf7e4383fb94882d3bc7ee5e38e4b469ee |
| src/lib/spectrumBrowser.ts | d98b369c9665586dbe27ad6c364dc1d9fcce460997e38e015fad2ef3bf484ff5 |
| package.json | 7ba7aa9dd07bf6c21117c76d764180bcbebf77f0bfe0024cba953cb5445af728 |
| package-lock.json | 5c274b144e01f26ddefd1c8297eb7a88ae4d3031e9a190cde7eb09e1a1987f16 |

## 未测边界与限制

- 已完成实际 Chrome/Vite/App 定向行为验证和 Windows 构建/收集；最终根目录 EXE 的 WebView2 内实际点击、原生文件对话框完整点击和 NSIS 安装过程未测，等待 reviewer 独立验证。
- 定向回归使用 CSV 两曲线及现有真实参考/处理 API；未逐项复测 XLSX、SIF、Avantes 全格式、百万节点/16 曲线极限性能、触屏、多 DPI、全部主题和屏幕阅读器。数据导入/解析业务未修改。
- 空数据、无曲线边界使用实际图表组件隔离挂载；不声称完整页面其他控件支持绕过正常导入约束的任意状态注入。首轮夹具曾因非法页面状态触发既有 ChoiceSelect 异常，最终测试已隔离为图表组件并以 errors=[] 通过；未修改不在授权范围的控件。
- 首轮边界测试暴露零宽 view 的除零问题，已在允许组件中加入全谱回退保护；最终回归使用合法非零选区，未穷举所有非法 view 或非有限源数据。正常导入仍依赖既有校验。
- 自适应范围是图表组件内状态，不承诺页面卸载后持久保留；新光谱或处理视图变化会回到该数据的全局范围。横向操作和曲线隐藏/恢复保持锁定，符合本任务语义。
- Python runtime 仍未打包，沿用项目外部 Python 环境要求；未安装依赖或修改全局设置。

完成标记：IMPLEMENTATION_READY taskId=T001 dispatchId=8e243d04-0640-4f35-841b-efb28c7198b6 revision=1。

报告完成后停止本轮写入，等待 review；仅在新的返工分派后继续实现。
