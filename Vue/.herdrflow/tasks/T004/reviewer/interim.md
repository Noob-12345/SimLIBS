# T004 临时只读预审意见（未冻结）

- taskId：T004
- dispatchId：229c687f-8bda-4b35-bea4-2e7841ace916
- revision：1
- 当前状态：implementing；本文件不是最终 review.md，也不代表 pass/changes_requested/blocked。

## 冻结前建议必须修正

### 1. spacer 行后可能错误继承上一条波长

位置：backend/simlibs_ui/spectrum_nist.py 的 parse_html 数据行循环，约在 current_wavelength、if len(values) != 9 ... continue、以及空波长状态行处理处。

当前逻辑在有效源行后设置 current_wavelength。布局 spacer／空行因列数不符或空内容被直接跳过，但不会清除 current_wavelength；随后如果出现一个九列、波长为空且有 Energy 的行，它仍会被追加到上一条跃迁。代码注释称只接受 immediately following source state row，实际没有验证中间没有 spacer 或其他非数据行。

依据：官方 Fe I/Fe II HTML 明确含 rowspan=1000 布局单元格和 colspan spacer 行；捕获数据也记录源行、后续状态行和空 spacer 的混合结构。该边界可能把异常/后续行的能级错归到前一条波长，违反 brief 对 nested table、spacer 和双行不错位的要求。

建议：把“紧邻的有效数据行”作为状态行条件；遇到布局 spacer、空行、表头或其他跳过行时清空 current_wavelength，或使用显式的上一行数据状态标记，只有紧随源行的空波长状态行才追加。补充一个“源行—spacer—空波长九列状态行”的 fixture 断言不归属上一跃迁，同时保留正常连续双行 fixture。

## 其余当前只读观察

- 后端路由只接受 source 与 element，网络客户端校验官方 HTTPS Handbook 路径、禁止重定向、验证 TLS、限制 connect/read/整体 deadline、Content-Type、16MB HTML 和 12MB JSON；不见本地回退伪装在线成功。
- parse_html 已校验 title 的 Persistent Lines 与元素/I/II 身份，保留 Å 原值、/10 的 nm、Aki 表头单位、能级、组态、Term、J、行号及两类引用；缺失值保持空字符串。
- 前端 referenceRevision、AbortController 和 clear/cancel 路径能阻止旧在线响应回填；同元素在线刷新按元素/态替换，来源类型保留为 nist，本地和用户 CSV 使用不同 originKind。
- 较低风险状态项：loadNistReferences 开始新请求时未先清空旧的 nistIssues/nistStatus，取消或失败时界面可能暂时保留上次在线状态文字；数据组不会因旧响应回填。冻结前可按产品语义决定是否在开始/取消时清理状态，当前不作为已确认的功能缺陷。

未运行浏览器或会改产物的测试，未修改业务文件或 task.json，未写最终 review.md。正式冻结后需重新读取实际 diff、测试和 HTTP 证据。
