# 原 reviewer 独立验收交接

由接管协调的 libs_planner 向既有 libs_reviewer 交接；不创建 agent/pane/终端、不修改业务代码。先读 D:\LIBS\herdr\coding\roles\reviewer.md，以及本目录 task.md、plan.md、reviewer-task.md、implementation.md、files.json、source-baseline.json；对照实际 UI 代码独立判断，不接受 coder 的结论代替验收。

范围：tkinter/Matplotlib/真实 SimulatedLIBS；static/dynamic、混合编辑、raw/interpolated/ion、批量、Te/Ne/R 扫描及 GIF、配置/预设、历史来源、CSV/PNG/JSON/目录导出、启动器。源库保持不动，UI 原本无业务代码；以源哈希基线和 UI 文件清单/冻结哈希检查，不要求创建 Git 仓库。

使用现有 D:\Anaconda3\envs\simLIBS\python.exe，独立运行 unittest、diagnose、启动器任意 cwd、实际 Tk smoke 和窗口/布局检查。真实复核 H100%/650–660nm 静态、size2 批量、Te/Ne/R 各2帧/GIF以及 dynamic/ion。实际科学数据可变化，不锁历史强度。预览为1500点、导出全量；源库Ne三位有效数字需与来源元数据对照。

重点：非法/非有限/溢出参数在 worker 前拒绝；100%总和与主动归一化；后台心跳、取消/关闭5秒内仅清理所属树、保留无关进程与旧成功结果、重试、迟到消息；损坏CSV/JSON；每帧参数、网格和导出来源；全零归一化。

动态当前 NIST 单 H I CSV 省略 Sum(calc)，只有唯一合法贡献时复制原值并说明来源；不得伪造其他离子。驱动154已匹配，测试真实headless、ion导出与quit。root拥有Full Access，而旧角色的workspace-write曾出现tab crashed/Get-Cim拒绝；不要据受限失败误判外部阻碍。确需提升执行时，给协调者准确命令和独立检查脚本，由协调者执行、你分析原输出并自行下结论。

截图只接受本应用 HWND：最终 coder 图位于 output/smoke-final-responsive/tk-smoke.png（若最终记录更新，以记录为准），早先桌面坐标截图拍到其他窗口已废弃。必须检查实际UI，不能仅以import/Tk创建标记通过。

写本目录 review.md，逐项记录命令、退出码、真实输出、证据路径、发现问题及未验证项，结论为通过/需返工/受阻；问题写明文件/定位/触发条件/影响/复现，不修业务代码。完成后停止，交本 planner 持续协调。coder 在验收期间停止业务修改；修复仍交原 coder，复查仍由你完成。
