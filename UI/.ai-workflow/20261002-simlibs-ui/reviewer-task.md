# 独立验收任务（实现完成后由协调者发送）
用户要求：按 D:\LIBS\herdr 多agent原则，将整个 simLIBS 封装成 Windows 本地桌面UI。
先读 roles/reviewer.md、task.md、plan.md、implementation.md、source-baseline.json，再独立读实际代码和差异。不要沿用coder的通过结论，不修改业务代码；发现可定位问题交回原coder。
逐项核对：真实源库调用和来源记录；源库SHA256未变；单次static/dynamic/raw/interpolated/ion；组分增删导入/主动归一化；非法值零请求；批量组成与参数透传；Te/Ne/R扫描播放、CSV/GIF；配置和所有导出；历史数据来源标记；中文窗口可用布局；启动器从任意cwd可用。
重点风险：GUI主线程网络/文件/导出阻塞，取消与关闭清理范围、迟到消息、worker及Chrome残留，坏CSV/JSON恢复，zero-spectrum归一化，动态headless真实生效及驱动匹配，导出元数据与实际生成参数一致。
必须独立运行unittest、diagnose、真实Tk smoke并实际启动窗口；真实H=100%、650–660nm静态模拟、size2批量、三类各2帧扫描及GIF、尝试动态离子并检查driver.quit/所属进程退出。线上数字可变，不能硬要求47/2000/1802原值。外部条件限制应逐项明确未验证与异常，不能伪写全功能通过。
review.md按验收标准逐项记录命令/结果/证据/未验证项；结论为通过/需返工/受阻。代码完成后才开始此任务。
