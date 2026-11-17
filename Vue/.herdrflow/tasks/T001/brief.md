# T001 — 光谱浏览：保持左侧效果控件展开；横向放大缩小时保持强度轴区间；增加显示全局与自适应强度按钮。

dispatchId: 8e243d04-0640-4f35-841b-efb28c7198b6
revision: 1
owner: implementer

## 目标与验收标准

1. 光谱浏览页左侧“数据选择／光谱预处理／参考谱线”等效果控件始终展开，不再显示或执行收起左侧控件的入口；桌面和窄屏布局均不因本次修改丢失控件。
2. 光谱主图默认使用当前可见曲线在完整波长范围上的强度上下界；放大、缩小、平移和概览联动只改变横轴选区，强度轴刻度和范围保持不随横向选区自动变化。
3. 光谱区提供“显示全局”和“自适应强度”两个可操作按钮，有准确的 title／aria-label；两者是操作按钮，不是持续自动缩放开关。
4. “显示全局”恢复完整波长范围，并恢复默认的全局强度区间；效果等同于原右上角恢复全谱操作。Home、Escape、右键恢复全谱等既有快捷操作也应保持该全局语义。
5. “自适应强度”仅在点击时按当前主图横向选区内的可见曲线重新计算并保存强度区间，保持横轴选区不变；之后横向缩放、平移或概览联动均保持该纵轴范围，直到再次点击或重置。按真实选区内节点及必要的边界插值计算，不把选区外巨大峰值算入强度范围。没有有效曲线／区间无节点／负值／全零或常量均须有有限有效范围，不产生 NaN／空白崩溃；概览仍使用全局范围。
6. 不改变真实数据、导入选择、参考谱线、处理结果、曲线隐藏和拖拽交互；按钮和画布具备可读的 aria-label／title。

## 输入与项目约定

需求来源：用户本轮关于光谱浏览交互的明确要求。
读取：AGENTS.md、.ai-workflow/herdr-three-role/workflow.md、.herdrflow/protocol.md、src/components/BrowserSidebar.vue、src/components/BrowserSpectrumChart.vue、src/pages/SpectrumBrowserPage.vue、src/lib/spectrumBrowser.ts。
当前基线：git HEAD 43e2818b700f505de49de25d2c07d3912b5ce6f4；工作区初始仅有本轮 Herdr 配置未跟踪文件，无业务源码未提交改动。

## 修改范围

允许修改：src/components/BrowserSidebar.vue、src/components/BrowserSpectrumChart.vue；实现报告位于 .herdrflow/tasks/T001/implementation.md。
禁止修改：其余业务源码、Rust/Tauri 权限、后端／数据／依赖、用户已有文件；不得恢复左侧控件收起效果或引入参数区限高滚动。允许按项目既有 npm run desktop:build 流程生成并交付 dist-desktop 根目录 EXE／NSIS，保留运行中的用户应用，遇锁记录而不关闭用户进程；不得另建版本交付子目录。

## 验证

实现者运行 npm run build，并用项目现有浏览器测试设施做定向行为验证（可在本任务目录写临时验证与证据），覆盖固定 Y、一次自适应、重置、选区边界和负值／零值；npm run desktop:build 交付根目录正式产物。reviewer 独立阅读实际 diff、报告和本 brief，复验行为、源码及产物哈希。所有会改写产物的验证串行执行；真实计算数据不造假，隔离 UI 测试数据明确标为测试。

## 交付

implementation.md：变更、文件、验证、限制、版本。
review.md：独立审查结论与依据。
acceptance.md：协调者逐项验收。

完成标记必须包含当前 taskId、dispatchId、revision；标记本身不代替报告核验。
