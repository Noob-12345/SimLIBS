# T005 — 将光谱区显示全局和自适应强度按钮改为与重置同尺寸同风格的十字箭头和上下箭头图标

dispatchId: 16a6adbb-5162-4d9f-a23d-44b91e20f0e1
revision: 1
owner: implementer

## 目标与验收标准

1. 光谱区现有“显示全局”按钮改为图标按钮：图形为四向十字箭头，语义仍为恢复完整波长范围的全局强度范围并保持当前横向选区；title 和 aria-label 保留准确中文说明。
2. 光谱区现有“自适应强度”按钮改为图标按钮：图形为上下双向箭头，语义仍为按当前横向选区自适应并锁定强度范围；title 和 aria-label 保留准确中文说明。
3. 两个新图标按钮的尺寸、边框、圆角、颜色、hover/focus 和间距与旁边的重置 icon-btn 完全一致；不再显示“显示全局”“自适应强度”文字按钮，也不改变重置按钮。
4. 保留既有横纵轴操作逻辑、图例右上布局、窄屏不溢出、键盘可达性和功能区独立布局；不修改 NIST、本地谱线、导入、controller、后端或依赖。

## 输入与项目约定

需求来源：用户本轮明确要求将光谱区“显示全局”和“自适应强度”改为与重置标志同尺寸同风格的十字箭头和上下箭头。
读取：AGENTS.md、.herdrflow/protocol.md、src/components/AppIcon.vue、src/components/BrowserSpectrumChart.vue、T002/T003 review 与当前未提交 diff。当前工作区保留 T003 已验收但尚未推送的页面／桌面产物修改，T005 不覆盖这些已有修改。

## 修改范围

允许修改：src/components/AppIcon.vue、src/components/BrowserSpectrumChart.vue；只改图标定义和图标按钮标记／局部样式。
禁止修改：src/pages/SpectrumBrowserPage.vue、src/lib/spectrumBrowser.ts、src/styles.css、backend、src-tauri、依赖、T002/T003历史证据和用户已有修改；不改实际按钮语义和数据逻辑。

## 验证

code 运行 npm run build，并用现有隔离浏览器或最小 DOM 渲染检查确认三个 icon-btn 尺寸／class／title／aria-label、图标路径和桌面／窄屏布局；不重复 T002/T003 大矩阵。reviewer 独立读取实际 diff，复验图标形状和按钮尺寸。用户 EXE 当前运行，若 desktop:build/根目录收集被锁，记录未执行边界，不关闭用户程序。

## 交付

implementation.md：变更、文件、验证、限制、版本。
review.md：独立审查结论与依据。
acceptance.md：协调者逐项验收。

完成标记必须包含当前 taskId、dispatchId、revision；标记本身不代替报告核验。
