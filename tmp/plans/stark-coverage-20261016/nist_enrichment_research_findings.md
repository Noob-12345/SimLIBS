# NIST enrichment：最终结论

2026-10-18，只读研究。未修改生产文件。下载使用正常 TLS 验证。未研究宽度语义。所有研究产物使用本目录 `nist_enrichment_research*` 前缀。

可行路径：现有 NIST LIBS 六列载荷 → 官方 ASD Lines TSV 补全上下态 → 按元素、电荷和完整上下态匹配 STARK-B 网站记录。波长接近不能作为身份依据。

## 精确请求

GET `https://physics.nist.gov/cgi-bin/ASD/lines1.pl`，以下为已实测完整参数：

```python
params = {
    'spectra': 'Si II', 'output_type': '0',
    'low_w': '634', 'upp_w': '638', 'unit': '1',
    'de': '0', 'plot_out': '0', 'format': '3', 'line_out': '0',
    'remove_js': 'on', 'no_spaces': 'on', 'en_unit': '0',
    'output': '0', 'bibrefs': '1', 'page_size': '100',
    'show_obs_wl': '1', 'show_calc_wl': '1', 'unc_out': '1',
    'order_out': '0', 'ids_out': '1', 'show_av': '3', 'A_out': '0',
    'allowed_out': '1', 'forbid_out': '1',
    'conf_out': 'on', 'term_out': 'on', 'enrg_out': 'on',
    'J_out': 'on', 'g_out': 'on',
}
```

`format=3` TSV；`format=2` CSV；`en_unit=0` cm^-1，`en_unit=1` eV；`unit=1` nm，`unit=0` Å；`show_av=3` 全真空；本可见光区 `show_av=2` 输出空气波长。`A_out=0` 输出 Aki，`A_out=1` 则是 gk*Aki。未传 `A8`，因此单位是 s^-1。`order_out=0` 为波长排序；`output=0` 返回全部结果。`line_out=0` 保留全部已存储匹配行，未请求生成额外 Ritz E1 跃迁。

`ids_out=1` 是表单中隐藏的 Level IDs 选项，实测返回 ID_i/ID_k，可保留作溯源；不要假定 CGI/隐藏字段具有稳定版本化 API 合约。

完整 URL、全部变体参数、时间戳和文件哈希见 `nist_enrichment_research_requests.json`。

## Si II 实测行

共同下态：`3s2.4s 2S 1/2`，gi=2，Ei=65500.47 cm^-1，ID_i=`014002.000009`。

| 名义空气线 | 观测空气 nm | Ritz 空气 nm | 观测真空 nm | Ritz 真空 nm | Ek cm^-1 | 上态 | gk | Aki s^-1 | gk*Aki s^-1 | ID_k |
|---|---|---|---|---|---|---|---|---|---|---|
| 6347 Å | 634.710 | 634.711 | 634.885 | 634.886 | 81251.32 | 3s2.4p 2P* 3/2 | 4 | 5.84e7 | 2.336e8 | 014002.000014 |
| 6371 Å | 637.136 | 637.137 | 637.312 | 637.313 | 81191.34 | 3s2.4p 2P* 1/2 | 2 | 6.80e7 | 1.360e8 | 014002.000013 |

NIST 独立 eV 导出：下态 8.121023 eV；上态分别 10.073880、10.066443 eV。TP refs 均为 `c22,T7222`，line ref 为 `L3541`；A 精度分别 B+、C+。Type 为空，官方定义为 E1。

真实现有 LIBS 请求也已下载，其关键内容：

```text
var lines = [[634.886,233600000,81251.32,14,2,65500.47],
             [637.313,136000000,81191.34,14,2,65500.47]];
var cmeV = 8065.54393734921;
```

该请求参数：`composition=Si:100, spectra=Si0-2, low_w=634, limits_type=0, upp_w=638, show_av=3, unit=1, resolution=1000, temp=1, eden=1e17, maxcharge=2, min_rel_int=0, int_scale=2, libs=1`。

AST 隔离执行当前 `parse_atomic_payload(include_levels=False)`，未导入/改写生产包。返回 lower_eV=8.121023269947882，上态为 10.073879781839457 / 10.066443209617432。

按元素/电荷、导出 **Ritz 真空**列、Ei/cmeV、Ek/cmeV、gk*Aki 联合关联，两条均恰好一个 NIST 候选。只允许四个 ULP 的浮点运算差异，无波长最近邻搜索。这证明的是本线对，其他载荷必须逐行验证，不能假定永远采用同一波长列。

保留原始 cm^-1 字符串并用同一 payload.cmeV 换算；不要通过宽松 eV 容差关联独立四舍五入的导出。对不上时报告版本变化/未匹配。若可能，后续数据结构保留原始 cm^-1、NIST IDs 和原始标签。

## 解析格式与约定

- TSV 为 UTF-8 text/plain，有表头和带引号字符串；使用 csv.reader/DictReader，delimiter 为制表符。忽略完全空的尾列和空行，按列名解析。
- 实测 Si II 即使 unc_out=1 也无显式波长误差列；Na I、Fe II 有 unc_obs_wl / unc_ritz_wl，禁止固定列位置。
- CSV 在 csv.reader 解码后值形如 `="634.885"`，只剥除此精确包装，不执行公式。已验证严格解包后与 TSV 完全一致。
- 先验证状态码、内容类型、表头、行长度。实测 format=3 加 order_out=1 返回 **HTML**，已保存为 `nist_enrichment_research_siII_multiplet_requested_tsv.html`；机器导出采用 order_out=0。
- NIST 默认 sigma>=50000 cm^-1 为真空，5000<sigma<50000 为空气，sigma<=5000 为真空；show_av=3 消除显示切换。标准空气转换采用 Peck–Reeder，lambda_air=lambda_vac/n。
- Ritz 真空 nm=1e7/(Ek-Ei)，输出再按数据精度取位；例如显示能量推得 634.8863712117 nm，而输出为 634.886 nm。不能将额外计算位数当成实测精度。
- STARK-B 自身波长介质需保留来源说明；这里通过上下态确认身份，不需要猜测其空气/真空约定。
- 多重态编号是数据库编排标签，不能跨库关联；按 multiplet 排序只显示已分类行。共享组态/项但缺 J 不等于某一细结构分量。H/D 的 configuration-average 与 resolved 子集需明确选择，本次未实验扩展。

## 严格 normalization

每个态的键包含元素、电荷、完整组态及 ancestry、项及限定符/宇称、单一精确 J；跃迁键同时包含上下态。所有原文保留。

1. 在已识别的 LS 项边界，将 `2P*`、`2Po`、HTML 的奇宇称圆圈统一为 multiplicity=2、L=P、parity=odd；不是任意删除字符 o/*。母项内部可以做同样的语法等价转换，但保留母项位置和括号结构。
2. J 用有理数，1/2=0.5、3/2=1.5；校验非负整/半整数及 g=2J+1。缺失、?、逗号列表或 or 列表不是单态，不能作通配符。
3. 组态先分词成有序的壳层占据数与母项/耦合标记，再统一分隔空格和点号；保留主量子数、占据数、顺序、母项、母项 J 和编号。
4. Fe II 的 `(5D)` 与 `(3D)`、`(1G1)` 与 `(1G2)`、`a 6D` 与 `b 6D` 都必须是不同键。不得去掉母项、编号和 a/z 等项限定符来增加命中率。来源缺这些字段时，需要有出处的 alias/crosswalk，否则身份不足。
5. 保留 Mg II/Na I 的 `2p6`、Ca II 的 `3p6` 等显式闭壳层。不得全局删除闭壳层；省略核的等价关系必须另行提供物种专属、有来源的映射，本研究未建立。
6. 非 LS、混合耦合、带不确定标记的标签保留原样或交给专门解析器。真实 Fe II 反例：上态 `3d6.(3P2<1>).4f`, `2[4]*`, J=9/2，Ritz=260.113262 nm。不能把它简化成普通 LS `2G`。
7. 构型混合和不同文献重新指认会导致物理态标签变化；词法规范化不能解决有冲突的已发表指认。不要用窄波段内恰好唯一来代替完整身份。
8. NIST 不可只按波长或 ID_i/ID_k 去重：Mg II 样本存在相同能级对与 Ritz 波长的 E1/M2 两行。保留 Type、A/gA 和各行来源，先唯一关联载荷。

真实 NIST 样本核验范围：Si II 634–638 nm 2/2 行；Mg II 279–281 nm 12/12；Ca II 393–398 nm 2/2；Na I 588–591 nm 2/2；Fe II 259.9–260.3 nm 20/21，剩余一行为上述非 LS 标签，保守拒绝。该计数验证 NIST 标签的有限语法，不声称 Mg/Ca/Na/Fe 的 STARK-B 覆盖。

## 网站表格比对及多来源

只读取用户保存 `siII_all_interp_query.html` 的 lower/upper/multiplet/wavelength 身份字段。去掉温度/拟合重复后有 23 组身份。存在：

```text
3s2.4s 2S 1/2 -> 3s2.4p 2Po 3/2, multiplet 32, raw wavelength 6347
```

与 NIST 634.886 nm 分量上下态严格一致。本保存数据集中未找到 637.313 nm 所需的上态 J=1/2；不能把 6347 的记录赋给 6371，也不能据此断言整个 STARK-B 全球缺失。

按用户指定的来源策略：**先确认身份，再按方法优先 SCP，之后才考虑 MSE；最佳方法等级仍有多个独立来源则拒绝歧义。** 即使数值相同也不能按第一条、最近波长、时间新旧选择。一个已知 dataset/transition/source 下的温度及拟合行是同一记录的结构，可按稳定键归组；不同来源不得无依据合并。保留 method、dataset/source IDs、文献、原始上下态。SCP 优先级不能覆盖身份冲突或缺 J。宽度及拟合语义留给父研究。

## 官方出处

- [NIST Lines 表单](https://physics.nist.gov/PhysRefData/ASD/lines_form.html)：参数名和枚举值。
- [NIST Lines Help](https://physics.nist.gov/PhysRefData/ASD/Html/lineshelp.html)：空气/真空、Ritz、g/A、宇称、多重态、CSV/TSV。
- [NIST Levels Help](https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html)：唯一命名需要 ancestry+term+J，不确定/多 J、构型混合、能量精度。
- [NIST T7222](https://physics.nist.gov/cgi-bin/ASBib1/get_ASBib_ref.cgi?db=tp&db_id=7222&element=Si&spectr_charge=2&ref=7222)：Matheron 等，Si II transition probabilities measurements in a laser induced plasma，2001。
- [NIST L3541](https://physics.nist.gov/cgi-bin/ASBib1/get_ASBib_ref.cgi?db=el&db_id=3541&comment_code=&element=Si&spectr_charge=2&ref=3541&type=)：Shenstone，The Second Spectrum of Silicon，1961。
- [NIST c22](https://physics.nist.gov/cgi-bin/ASBib1/get_ASBib_ref.cgi?db=tp&db_id=&comment_code=c22&element=Si&spectr_charge=2&ref=&type=)：Froese Fischer MCHF/MCDHF Collection。

验证记录：`nist_enrichment_research_parsed_validation.json` 与 `nist_enrichment_research_normalization_validation.json`。所有精确官方导出请求与哈希见 requests.json。一个文献请求曾发生 TLS unexpected EOF，随后保持正常验证重试成功；没有绕过证书验证。
