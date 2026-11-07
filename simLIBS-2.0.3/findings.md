# STARK-B 诊断证据

## 代码路径

test.py 当前使用 static、stark_broadening=True、instrument_broadening=False。
resolve_stark 优先使用用户系数、内置 JSON，然后自动查询 STARK-B。
失败位置为 StarkBClient._fetch 的第一个请求：

```text
POST https://stark-b.obspm.fr/index.php
module=stark_b
action=periodictable:datasets
element=<待查询元素>
```

这一步只选择元素，尚未提交温度、密度，也未解析谱线或计算线宽。
_request 对 502 等错误最多尝试三次，重试间隔为 0.5 和 1 秒，之后保留原异常链。
默认缓存 C:\Users\32957\AppData\Local\simLIBS\stark-v1 当前无 JSON 快照。
某条线无物理系数时应产生 MissingStarkDataError，与本次 StarkDataAccessError 不同。

## 本机实时验证

- 使用 D:\Anaconda3\envs\simLIBS\python.exe 和 requests.Session(trust_env=False)。
- 首页 HTTPS、index.php GET/POST、说明页、HTTP 首页均返回 nginx 502。
- 同环境 NIST lines_form.html 返回 200。
- 更换浏览器 User-Agent、空 POST、home 路由和 TAP capabilities 均未解决；table GET 有一次超时。
- DNS 为 145.238.80.65；直接 TLS 对端证书主体是 OBSERVATOIRE DE PARIS，域名 *.obspm.fr，验证通过。
- 未设置 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY；getproxies 仅有 no 项。

## 官方资料与外部检索

- https://stark-b.obspm.fr/index.php/description 描述按元素和电离态取表；无颜色元素没有数据。
- https://vamdc.org/type_database/stark-b/ 说明 STARK-B 提供已发表的逐线/多重态展宽数据，不保证任意跃迁均有数据。
- 外部网页检索能显示首页和说明等部分内容，其抓取时间可能早于实时请求；index.php 本身仍不可访问。
- TAP 入口同属该域名，不能直接假设换 TAP 即可避开此次 502。

## 推断

补充：已核对内置表仅 31 条记录，涉及 Zn I/II、Ca I/II、Mg I/II。
修复前 STARK-B 客户端 11 项离线测试通过；全量 86 项通过。

故障在远端取数层；现有证据较强支持 STARK-B 网关/上游服务异常。
不能仅凭 502 区分 PHP 应用、数据库或远端访问策略的具体问题。
当前代码依赖在线补齐系数且无缓存，所以服务失败会终止模拟。

## 修复阶段的新证据

- subagent 查到 VAMDC 注册表的真实入口是 `/12.07/vamdc/tap/`，此前测试的 `/tap/` 路径不正确。
- 本机实际 GET `https://stark-b.obspm.fr/12.07/vamdc/tap/sync` 成功返回 200；Si II 6340–6380 Å 查询取得 8517 字节有效 XSAMS、1 条跃迁，`VAMDC-TRUNCATED=None`。
- 同站网页 PHP 表单持续 502，但版本化 VAMDC 后端仍可取数；不能把这次故障描述为整个 STARK-B 站点完全不可用。
- Si II 原始 XML 在 10000 K、1e17 cm^-3 的电子宽度为 1.93 Å，与已有官网 HTML 夹具一致；虽然 XML 名为 gammaL，该节点导出值沿用 STARK-B 的 FWHM。
- XML 保留组态/项/J、电子/离子环境和原文献。官方节点源码未导出拟合系数和 C，也未标注计算方法；这些字段不得假定为已知。
- 仅该来源允许表内温度线性插值并显式标注；HTML 无拟合时的严格行为保持。
- 默认同时接受 SCP/MSE 时允许接口未报告方法的有来源数据，标为 unreported；只选单一方法时仍拒绝未知方法。
- 主线已补并运行失败回归，随后通过 14 项客户端与 6 项身份匹配测试；官方接口适配器及回归由 subagent 在独立文件范围实现。
- 额外排查：curl、历史本机代理 7890 均未使网页接口恢复，故不修改用户代理设置。

## 已实现与验证

- 新增 stark_vamdc.py，保留原始 XML/来源，验证完整响应并补取截断分段；网页失败后自动回退，不额外配置。
- 验证后缓存，坏 XML/单位/引用/截断无法补全时拒绝写缓存；失败网页在同次模拟不反复查询。
- 首个网页元素列表探测使用 (5 秒连接、10 秒读取) 超时，其他查询默认仍为 60 秒，保留三次有限重试。
- 修正 HTML 返回密度核对，仅允许四位有效数字的显示舍入，不能把其他密度的表直接重标。
- 独立 reviewer 发现最低参考密度表可能不覆盖目标温度；已先写失败回归，再改为保留密度候选、检查温度/有效性后按同一来源选择最低可用参考密度，保留来源歧义检查。
- 当前全量 113 项通过。包含缓存复用、5000/7500/10000 K 密度选择、坏响应、单位、粒子、截断和禁外推等边界。
- 真实全链路：Si II，Te=0.86 eV，Ne=1e17 cm^-3，真空 634.886 nm，Stark FWHM=0.193439 nm，数据来源 vamdc-xsams，温度方法为表内线性插值。
- 上述真实数据已成功在禁止 Stark 网络的条件下复用缓存，重采样不联网。
- 完整首样品的 120 秒探测未跑完（停留于首个 Li I 网页请求）；未覆盖任何用户模拟 CSV。随后收紧首次网页超时，另行验证 Li I。
- Li I 全密度查询虽成功（11 条可用记录），耗时约 175 秒并需分段；加入物理上等价的 `EnvironmentTotalNumberDensity >= 目标Ne` 限制，排除本来不能向高密度外推的原表。
- 加密度过滤后的真实 Li I 新缓存取数：3.44 秒，1 个完整页面，11 条记录；未使用旧缓存。
- 最终全量 113 项通过，覆盖新密度筛选限制；代码 whitespace 检查通过。
- 复审 subagent 触发 429 限流，无法完成最终确认；主代理已核对其提出的温度/密度问题修复及回归通过，不将其描述为独立复审通过。

## 后续 Na III / NIST HTTP 522

- 用户的多元素运行推进到 NIST ASD 原子态补查（Na III，200.4363–829.584 nm），Cloudflare 返回 522；故障源为 NIST，与前面的 STARK-B 网页 502 分属两个请求阶段。
- 重放相同请求：HTTP 200、35663 字节、有效身份表头，耗时约 1.59 秒，表明本次端点已暂时恢复。
- 发现共享请求器的暂时错误列表遗漏 522，导致首次失败直接退出；错误前缀也一律写 Stark，容易误判来源。
- 已先补两项失败回归，再将 522 纳入最多三次重试，并按域名显示 NIST ASD / STARK-B 来源。
- 最新全量 115 项通过，包含 522 后成功与持续 522 达到重试上限；未改变原子态匹配或展宽数值算法。
