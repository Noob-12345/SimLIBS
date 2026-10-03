# 第一轮独立验收返工：交原 libs_coder

原 reviewer 已完成并停止，结论需返工。原始报告保存在 review-round1.md，当前 review.md 有完整复现脚本和证据。planner 已对照实际代码核对三项定位；请使用 receiving-code-review/systematic-debugging/TDD，保持 source 不动，不启动 agent/pane/终端窗口。用户已授权直接修复，不再等批准。

按以下小步修复，每步先复现失败再实现并检查，最多3业务文件。不要扩大功能或重复已通过的全量NIST请求；实现记录补充本轮变更、测试命令/退出码和真实限制。

1. **R1/P1 科学数据完整性**：adapter.py/storage.py（最多2业务文件）及回归测试。真实动态解析整表 fillna(0) 把缺失波长变0nm、字面NaN总谱变0，是实际缺陷。按 review 第5节R1复现并验证拒绝缺失/非有限波长、总谱及明确NaN/Inf贡献；只允许有明确语义的合法离子贡献空白按0处理。保留当前单一合法H I缺Sum时原值复制与来源说明，不得掩盖已存在的损坏Sum。成功/失败都quit，获取失败保留上一成功结果，不能生成成功科学manifest。补坏数据负向与合法稀疏/单离子正向测试，并做一次针对性真实dynamic/ion复验。

2. **R2/P2 扫描数值**：models.py（1业务文件）及回归测试。Te/Ne 1e308→1.7e308、5帧会在先乘后除中产生inf，ScanSpec仍放行Popen。使用稳定扫描生成方式并逐帧校验finite、边界、顺序/终点与该轴的参数契约；无法有效生成时在worker前抛ValueError。允许合法大有限值返回完整有限帧；不要无依据增加物理上下限。测试Te/Ne帧数模式、R整数异常转换、真正非法/非有限派生结果不得启动Popen或传输。保持现有终点包含规则和最多200帧/资源上限。

3. **R3/P2 最小窗口可访问性**：result_view.py/app.py（最多2业务文件）及实际Tk回归。950×680时颜色仅16px、显示归一化未映射；表格上下页均未映射。使结果控制区自适应换行/布局，分页控制预留空间；保持绘图/数据表、导出、播放、进度/取消可用。不能仅增大最小尺寸规避。测试控件真实映射、足够可见尺寸/边界与用户翻页操作，保存本应用HWND的最小窗口绘图页/数据表页截图供原reviewer复验。

每步检查受影响集合，结束运行完整unittest与新smoke；source-baseline三哈希重新核对。不得改review.md伪装独立通过，不擅自操作reviewer。完成更新implementation.md/files.json/测试日志，停止业务修改，交本planner重新冻结并交原reviewer复查。
