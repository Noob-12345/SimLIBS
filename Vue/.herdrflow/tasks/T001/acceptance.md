# T001 验收报告

dispatchId: 8e243d04-0640-4f35-841b-efb28c7198b6
revision: 1

## 验收标准与证据

1. **左侧控件保持展开：通过。** BrowserSidebar.vue 已移除收起入口、折叠状态绑定、inert 和隐藏逻辑；code 的 behavior-check.json 与 reviewer 独立复验在 1360、440、360px 下确认无收起入口、无横向溢出且控件可见。
2. **横向缩放不改变强度区间：通过。** BrowserSpectrumChart.vue 将全局 Y 范围与主图横向选区分离；reviewer 独立复验滚轮、框选、Shift／中键平移及概览联动均保持 Y 刻度。
3. **两个按钮：通过。** 已加入“显示全局”和“自适应强度”，均有 title 与 aria-label；自适应是点击一次后锁定纵轴的操作。
4. **全局恢复：通过。** “显示全局”、Home、Escape 和右键均恢复完整横轴与全局强度范围，重复恢复也已验证。
5. **选区自适应：通过。** 点击自适应时按当前选区真实节点及边界线性插值计算有限 Y 范围，选区外峰值不参与；后续横向操作保持锁定。负值、全零、常量、空数据、无曲线、全部隐藏及重复波长均通过有限值检查。
6. **既有功能保持：通过。** reviewer 独立复验真实文件导入、参考线提示、处理视图、曲线隐藏、原数组保真和拖拽连接。

证据：.herdrflow/tasks/T001/behavior-check.json（7 组 PASS、errors=[]）、reviewer 独立证据 .herdrflow/tasks/T001/reviewer/behavior-check.json（7 组 PASS、errors=[]）、build.log、desktop-build.log、implementation.md 和 review.md。

## 审查与最终版本

reviewer 已对 dispatchId=8e243d04-0640-4f35-841b-efb28c7198b6、revision=1 的冻结版本独立审查，结论为 pass。审查版本为 HEAD 43e2818b700f505de49de25d2c07d3912b5ce6f4 加两个未提交业务组件 diff，以及已更新的 dist-desktop/ 根目录产物。reviewer 重新核对了源码与 EXE／NSIS 哈希，审查后没有业务变更。

## 交付结论

T001 completed。源码、前端构建、定向浏览器验证和 Windows EXE／NSIS 构建均完成，正式产物已更新到 dist-desktop/ 根目录。未执行最终 EXE WebView2 实际点击、原生文件对话框完整验收或 NSIS 安装验收；review.md 已记录这些限制，以及窄屏横轴刻度拥挤的现有可用性限制。业务修改停止，交回 plan 等待下一项需求。
