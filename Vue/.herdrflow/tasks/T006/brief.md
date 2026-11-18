# T006 — 统一全部光谱区方向框选：左向右放大，右向左缩小

dispatchId: 09c2198a-eba1-4236-bca0-379723d27c79
revision: 1
owner: implementer

## 目标与验收标准

1. 所有光谱区框选交互统一按拖拽方向解释：左向右拖拽把框内波长范围设置为当前视图，实现放大；右向左拖拽把框选宽度作为缩小尺度，围绕框选中点向外扩展当前视图，实现缩小。
2. 覆盖 SpectrumChart.vue（单次、批量、扫描、高级共用）和 BrowserSpectrumChart.vue（光谱浏览主图）；两者方向语义、最小阈值、边界夹紧和全谱上限一致。
3. 右向左缩小时不能越过完整波长范围；左向右放大不能产生零宽／NaN；拖拽方向反转不会改变中键／Alt／Shift 平移、滚轮、键盘、右键重置和概览联动语义。
4. 保留光谱数据、负值、纵轴范围、hover、参考线、图例和导出行为；只修改框选视图计算，不改后端、Rust、依赖或当前 T003/T005 其他 dirty 变更。

## 输入与项目约定

需求来源：用户本轮要求所有光谱区左向右框选放大、右向左框选缩小。
读取：AGENTS.md、.herdrflow/protocol.md、src/components/SpectrumChart.vue、src/components/BrowserSpectrumChart.vue、当前T003/T005实现与review证据。
基线保留当前工作区已有 dirty：T003 页面／桌面产物与T005 AppIcon／图表图标。T006只新增两个图表文件的框选方向修改。

## 修改范围

允许修改：src/components/SpectrumChart.vue、src/components/BrowserSpectrumChart.vue；任务证据写入本目录。
禁止修改：src/pages/SpectrumBrowserPage.vue、src/lib/spectrumBrowser.ts、src/components/AppIcon.vue、src/styles.css、backend、src-tauri、依赖、T003/T005历史证据和用户已有 dirty 文件。

## 验证

code 运行 npm run build，并在任务目录用最小隔离图表挂载／CDP或等价验证覆盖两个组件的左右方向、边界夹紧、重复方向、平移与重置回归；不重做T002/T003/T005无关矩阵。reviewer独立读取实际diff和证据，复验两个组件。用户EXE正在运行，本轮不关闭应用；如不重新收集桌面产物须如实记录。

## 交付

implementation.md：变更、文件、验证、限制、版本。
review.md：独立审查结论与依据。
acceptance.md：协调者逐项验收。

完成标记必须包含当前 taskId、dispatchId、revision；标记本身不代替报告核验。
