# T003 — 修复数据选择自动更新时提示和取消控件引发的页面布局抽动

dispatchId: 489619a1-691c-44b3-8a87-1687dcb4f081
revision: 1
owner: implementer

## 目标与验收标准

1. 成功导入后更改数据选择时，不再因“正在更新光谱选择…”段落的挂载／卸载而推拉整个页面。更新状态使用不占布局高度的 aria-live/sr-only 或工具栏内预留位置，不新增整行高度。
2. pending 的取消按钮出现／消失也不得使工具栏换行或改变下方布局。取消操作仍可访问，空闲时无不可见的Tab焦点。取消／正常完成的状态消息同样不引入临时整行跳动；实际错误可清晰显示。
3. 真实CSV导入后，用可控延迟保持请求pending，测量选择前／pending中／完成后，toolbar、侧栏、chart/canvas的top和高度以及scrollY在同一窗口宽度下稳定；覆盖1360、960、440、360px。改变强度列或重复值规则（不改变轴长度或元数据行数），避免把合法结果布局变化误认为本缺陷。自动更新完成、快速选择最新值获胜和取消保留旧图仍可用。
4. 保持空态中央导入、成功绿色打开文件、真实节点和负值、现有轴操作／图例／hover尺寸，不改controller、图表组件或数据业务。

## 输入与项目约定

基线 ae4b1d4db01b0042b23bb65f01728494abec5dd2，工作区业务干净。遵循AGENTS.md、.herdrflow/protocol.md及角色文件。现有T002已完成并推送，证据只读。

## 修改范围

唯一允许业务文件 src/pages/SpectrumBrowserPage.vue。可在本任务目录写定向验证、实现与冻结证据，按项目原流程生成dist-desktop根目录EXE/中文NSIS。
禁止修改其余业务源码、controller、图表、后端／Rust／依赖、旧任务证据；不关闭用户应用，不另建版本交付子目录。

## 验证

复用T002隔离浏览器设施，只新增本缺陷的定向几何验证，不重做无关矩阵。延迟请求时断言实际pending=true，记录前／中／后矩形和scrollY。code最终源码验证后串行npm run desktop:build（含前端类型与构建），报告实际结果／SHA256，冻结交review。review独立读diff、证据并做必要复验，写review.md，不改业务。

## 交付

implementation.md：变更、文件、验证、限制、版本。
review.md：独立审查结论与依据。
acceptance.md：协调者逐项验收。

完成标记必须包含当前 taskId、dispatchId、revision；标记本身不代替报告核验。
