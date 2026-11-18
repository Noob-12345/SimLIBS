# T004 交付记录

dispatchId: 229c687f-8bda-4b35-bea4-2e7841ace916
revision: 1

## 验收标准与证据

1. 谱线位置参考面板在“加载当前谱线库”旁新增“加载 NIST 在线谱线库”，两个入口同排，440px 窄屏无溢出；展开后可选择元素并加载／刷新。
2. 后端从NIST官方周期表实际元素链接访问Persistent Lines table3/table4，真实Fe I/II、Mg I/II HTTP200；H II无持久线时明确报告缺态。
3. 在线结果保留Å原值、nm换算、Intensity、Aki倍率、Energy Levels、Configuration、Term、J、Line Ref、Aki Ref、源行号、URL、获取时间和HTML SHA256；NIST、本地、用户CSV来源隔离。
4. 7项NIST解析／安全边界单测通过，浏览器真实File查询、I/II来源、刷新去重、入口布局和根目录资源检查通过；review pass，补充审查如实列出未独立验证的组合边界。
5. Tauri/NSIS构建退出码0；用户退出后已collect到dist-desktop根目录，collection-check验证120项资源和EXE/NSIS/manifest/SHA256SUMS一致。

## 审查与最终版本

reviewer 对 dispatchId=229c687f-8bda-4b35-bea4-2e7841ace916、revision=1 的冻结版本结论为 pass；220个保护文件无变化，补充审查与根目录交付补核均为 pass，审查后源码/产物哈希未变。

## 交付结论

T004 completed。正式程序为 dist-desktop/SimLIBS.exe，安装包为同目录 SimLIBS-Setup.exe，均包含NIST在线参考后端。关闭II刷新后的勾选、失败/取消/清空迟到响应、NIST虚线实际命中tooltip以及原生WebView2／文件对话框／安装／读屏仍按review补充报告列为未测；未将这些边界冒称通过。T006方向框选任务仍未实施。
