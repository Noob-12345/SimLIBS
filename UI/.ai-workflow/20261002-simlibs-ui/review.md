# simLIBS UI 第二轮独立复验
结论：**通过**。**R1/R2/R3全部关闭，无待修问题。**

日期：2026-10-02；执行者：原reviewer。已读取rework-task.md、review-round1.md、implementation.md最新返工章节、rework-final-check.json、review-baseline-round2.json，对照实际源码独立检查。
本轮不以coder/协调者通过记录代替验收。未改业务代码/测试/基线，未创建agent、pane或新终端窗口，仅更新review.md并生成output/reviewer-round2-*证据。
首轮详细报告/复现脚本保留在review-round1.md，原review-baseline.json保留；本文件是最新结论，未改写首轮“需返工”历史。

## 1. 逐项结论

| 项目 | 结论 | 本轮独立结果 |
| --- | --- | --- |
| R1/P1 科学CSV整表补零 | **关闭** | 22个负向CSV拒绝，2个合法稀疏/单离子正向通过；实际受控worker失败/无成功manifest/保留旧结果/quit=1；真实dynamic原CSV和导出一致。 |
| R2/P2 扫描溢出与坏派生帧 | **关闭** | Te/Ne/R旧极端有限区间返回完整finite五帧；27个非法派生/精度不足用例零Popen、零requests；合法范围允许启动，没有新增物理上限。 |
| R3/P2 最小窗口控件/分页 | **关闭** | 真实950×680控件完整映射、达到请求尺寸且在全部祖先边界内；实际invoke改色/归一化/分页成功；新HWND截图已看图核对。 |

## 2. R1证据与影响核对

- adapter.py:188使用dtype=str/keep_default_na=False保留词元，原整表fillna(0)已删除；storage.py:84只允许合法离子贡献列的明确空白归零；波长/已有Sum不补零，随后严格finite检查。
- 独立22个负向：波长和Sum各测试NaN/nan/Inf/-Inf/NA/NULL/空串/空白，H I测试6个明确坏词元。实际simulate、真实源构造/getter，仅mock Selenium；全部RuntimeError，quit均1。
- 合法多离子稀疏raw=[0,2,3]；单H I缺Sum且含合法空白raw=[0,2,0]，Sum与唯一H I一致且来源明示复制；read_history也得到一致结果。
- 实际JobController/mock_dynamic_worker先成功，再提交首轮缺失波长/NaN总谱：两次FAILED，旧last_result/result_path保留，无成功manifest，quit=1。
- 新证据：output/reviewer-round2-independent/r1-checks.json；r1-worker/.jobs/9ce8c20f6c254dc298c7ab61aeb2e046及8192df9939e24ea4a8407b532aca238a下的request/events/error/mock-browser记录。
- 针对性真实dynamic核对单H I原值与完整ion导出通过（见第5节），没有伪造其他离子，也未向线上注入损坏CSV。

## 3. R2证据与正常范围

- models.py:136先形成i/(n-1)比例；checked_scan_frames(:145)检查finite/范围/端点/顺序/R类型；ScanSpec.validated(:202)逐帧检查实际轴参数。
- Te/Ne/R的1e308→1.7e308、5帧：float表示为[1e308,1.175e308,1.35e308,1.5249999999999999e308,1.7e308]，完整、finite、严格有序、两端准确；R实际为正整数。
- 合法大有限范围用mock Popen哨兵证明允许到达启动步骤，requests=0。合法范围不要求禁止启动，本轮未向NIST提交极端值。
- 25个注入坏派生帧（NaN/Inf/0/越界/倒序/重复/缺端点/R非整数）及2个实际浮点精度不足范围均ValueError：Popen=0、requests=0、job.process=None，合计27例。
- 步长模式1.12345678912345→1.42345678912345/0.1精确保留两端；资源上限/终点规则既有测试继续通过。
- 正常Te1→1.2、Ne1e17→1.2e17、R1000→1200各2帧，用operations.scan→实际simulate→真实构造/原插值，仅HTTP响应mock；每轴2次调用、2000点、来源参数=扫描值、partial=false。
- 这三项为正常范围回归，**不是本轮重新联网扫描**。首轮三轴NIST/GIF已独立通过，operations/worker/plotting未改，依用户要求不重复全量NIST。
- 新证据：output/reviewer-round2-independent/r2-checks.json、normal-Te/normal-Ne/normal-R完整CSV与manifest。

## 4. R3实际invoke与HWND图

- result_view.py采用两行grid/伸缩标题/说明折行，表格为滚动条及分页预留grid行；紧凑UI标签为Normalized I，全量导出实现未改。
- 本轮实际Application载入新smoke的历史manifest，确认950×680。颜色93×33、归一化81×23、标题93×33、上/下页93×33，均映射且满足请求尺寸，全部祖先裁剪边界通过。
- 颜色按钮实际invoke（仅mock选择对话框返回），回调一次，曲线变#ef4444；归一化invoke三次完成开/关/开，曲线max=1。
- 标签bbox=[4.167,32.410,20.167,117.535]，画布475×125，四边均在画布内。
- “下一页”invoke后首波长200→253.3，第2/15页、100行；多次invoke验证末页夹紧索引14，再“上一页”恢复第1页及原数据；取消/进度映射。
- 新证据：output/reviewer-round2-independent/r3-checks.json、plot-950.png、table-950.png；两图均按本应用HWND捕获并实际view_image核对，默认窗口smoke图也已查看。
- 未以直接修改变量代替invoke，未用coder截图或桌面坐标截图代替独立看图。

## 5. 实际命令、退出码与原输出

cwd= D:\LIBS\simLIBS-2.0.3\UI；Python固定D:\Anaconda3\envs\simLIBS\python.exe，带-B，无安装或全局设置修改。
```powershell
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\run_ui.py' --smoke-test --output '.\output\reviewer-round2-smoke'
& 'D:\Anaconda3\envs\simLIBS\python.exe' -B '.\verify_real.py' --dynamic-only --output '.\output\reviewer-round2-dynamic'
```

| 命令/检查 | exit | 本轮实际输出 | 新证据 |
| --- | --- | --- | --- |
| 完整unittest | 0 | **Ran 57 tests in 23.007s / OK**，逐条ok | 本轮工具输出；包含11新增回归及既有取消/关闭/超时/隔离/zero-GIF/schema/CLI等 |
| 新真实Tk smoke | 0 | 3页、61心跳、3.922s、error=null、new_simulation=false，后台CSV/PNG/JSON导出、自动关闭 | output/reviewer-round2-smoke/smoke.json、tk-smoke.png、history.* |
| 真实dynamic（FullAccess） | 0 | SUCCEEDED、13.125s/419心跳；raw/interpolated各49×2、ion49×3，finite；worker3800退出 | output/reviewer-round2-dynamic/real-validation.json、任务原CSV/manifest/driver日志 |
| 完整ion导出（同上命令） | 0 | SUCCEEDED、0.672s/21心跳；worker24464退出 | 同目录H-ion.csv及H-ion.csv.json |
| R1独立stdin脚本 | 0 | 22负向拒绝、2稀疏通过、两worker失败/旧结果保留/quit1 | r1-checks.json及受控worker日志 |
| R2独立stdin脚本 | 0 | 三轴大有限值稳定；27非法零Popen/零requests；正常三轴各两帧 | r2-checks.json及normal-* |
| R3独立stdin脚本 | 0 | 映射/尺寸/全部祖先边界/invoke/标签/分页边界通过 | r3-checks.json及两个950截图 |
| dynamic原数据独立stdin对照 | 0 | 原H I=返回H I=Sum=raw；导出字节相等、来源旁文件=origin；source/Ne/URL匹配 | dynamic-checks.json |
| 最终冻结/首轮保留/进程查询 | 0 | source3/3、UI29/29、首轮记录未变；Chrome/ChromeDriver count=0 | 最后只读工具输出，见第6节 |

四个补充脚本均以PowerShell here-string经现有通道调用python.exe -B -，未新增脚本或修改测试；步骤/断言详见第2–4节，JSON在output/reviewer-round2-independent下。
真实dynamic直接按持续授权require_escalated运行，避免首轮已查明的旧sandbox限制；审批获准，无阻塞。实际原CSV位于.jobs/cfa58551116d4f4a9c7bc81d0a348347/nist-dynamic.csv。
独立确认driver154.0.8037.92、--headless=new、actual_Ne="1e17"与源三位有效数字及URL eden一致；只返H I，复制来源/空白策略明确，完整ion导出与任务CSV字节一致。
工具固定independent_acceptance=false字段未改；本reviewer依据新执行及独立原CSV/hash/导出对照下结论。
报告第一次写入因嵌套here-string解析失败exit1且未执行写入，随后逐行字面量写入成功；属于reviewer记录命令错误，未重跑已完成测试，不列为业务缺陷。

## 6. 最后基线及记录保留核对

读取review-baseline-round2.json/source-baseline.json/files.json，以hashlib.sha256(Path(item['Path']).read_bytes()).hexdigest().upper()逐项比较Hash；验证29项文件集合一致，并比对首轮记录固定hash（最终exit0）。
- 新冻结：29/29匹配；相对旧冻结仅4业务+5既有测试改变、1新测试辅助，和rework-final-check.json一致。
- 源码：simulation.py=4279A121C07D88D1BEF9E6E8650B2DF77EF04A6B4CCA28B705AFC143ED2FA899；animation.py=EEE804D29155A4130FB7CA2F2C378A38BA2653B43817B1518EDC31975E296DCC；__init__.py=EA49DBDFD082A543137ED75619C18F3AA21C2B4924AB8721D0284B4A322FB24A，3/3一致。
- review-round1.md=26369F627D20DAF6067D345A8FD8143D9163E57D4F31FC517A81D588E25E2F63，review-baseline.json=B2CB3A5741167FD654533BF94C412808FDA8036F5A17CB60526E8206F76350A5，均保留不变。
- 只读Get-Process -Name chrome,chromedriver -ErrorAction SilentlyContinue查询count=0；未按名称kill。
- 新smoke历史来源SHA256仍为73cb0fbe6bd677e564945d901305671ad59a9447626d2b7c24f6882ace7bf107，parameters=null，不冒充新模拟。

## 7. 边界与移交

- 首轮静态/size2/三轴真实NIST及GIF、真实Chrome取消1.000s/关闭1.140s的独立证据仍保留，未受影响部分不无理由重跑全量NIST。
- 大有限参数生成有效不等于NIST会返回物理有效极端谱；未提交极端值，也未引入无依据物理上限。
- 坏CSV使用mock传输保留真实构造/worker路径，正常单离子另有一次真实NIST检查；色彩对话框选择mock，实际控件invoke与绘图执行。
- 未额外真实验证多元素dynamic、200帧/500万单元压力运行或开启用户其他Chrome会话；首轮边界保留，既有资源/隔离/零谱/不同网格测试本轮继续通过。
- 外部NIST/网络/Chrome版本仍可变化；本轮无待修问题、无未解决阻塞，无需planner代执行检查。

**验收完成，通过。R1/R2/R3全部关闭；停止执行，交本planner继续协调。**

