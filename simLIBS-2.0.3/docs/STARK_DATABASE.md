# STARK-B 全库快照与模拟优先级

电子碰撞 Stark 展宽按 **STARK-B → DK1980 修正半经验计算 → 缺失** 逐条解析。
旧报告中的 162 条线是同时通过原子输入和模型适用性筛选的成功比较子集，
不能用作 STARK-B 的数据库规模或模拟数据范围。

## 供模拟读取的单个 JSON

文件：`stark-b/stark_broadening.json`（相对于 `simLIBS-2.0.3`）。

- `rows`：所有已下载物种的电子 FWHM 表，不按 DK1980 的 q=2/3 或原子输入筛选。
- `raw_payloads`：无损 gzip+base64 压缩的原始响应 JSON；保留 XSAMS 和补取的官方 HTML 中的其他碰撞体、位移、文献及官网拟合。解压后仍是逐物种的原始 `payload`，以 `uncompressed_sha256` 校验。
- `manifest`：官方物种发现清单、各物种状态、SHA-256、表数、点数与失败原因。
- `counts`：物种、元素、含来源身份的谱线、参考密度表、温度点的数量。
- `complete` 与 `scope`：只有 `complete=true` 且 `scope=all` 才表示发现范围内全部物种均已取回。
- `rows_sha256`：排序、紧凑 UTF-8 JSON 的 SHA-256，供读取时校验。

字段单位：`calculated_wavelength_angstrom` 与 `fwhm_angstrom` 均为 Å，
`temperature_k` 为 K，`ne` 为 cm⁻³。宽度是 **FWHM**；转换 nm 除以 10。
渲染器的 W 为参考电子密度下的 HWHM，转换时再除以 2，不能重复乘二。
不同参考密度及文献保留为不同表，同一条线的多个温度点不能当成独立谱线。

官方发布的非正宽度原样保存并添加 `nonpositive source electron width` 标记；
这些点不可用作模拟系数，不取绝对值、不补任意常数，也不因此丢弃整个物种。
VAMDC 未导出的计算方法、C 和拟合继续记为未知，不从文献标题推断。

读取全部电子表只需 `json.load(...)['rows']`，无需解压原始响应。要核对
原始出处，可使用 `json.loads(gzip.decompress(base64.b64decode(item['payload_gzip_base64'])))`。

本次采集包含 **60 个元素、172 个物种、5329 条含数据集与来源身份的谱线、
11819 张参考密度表、66851 个温度点**。发现清单全部成功取回；这描述
官方服务在采集时暴露的范围，不意味着每个温度密度点都适合所有模拟条件。
实际范围包含 q=0 至 q=12，表内温度 1000 至 6000000 K、参考电子密度
1e10 至 1e24 cm⁻³。单个物种和谱线只在其自己的表内范围及有效性条件下使用。
共21个非正原始宽度点已保留并标记不可用。

## 采集与更新

在 `simLIBS-2.0.3` 目录执行（Python 环境路径按实际安装调整）：

```powershell
& 'E:/Anaconda/envs/simLIBS/python.exe' stark_data_collect.py --workers 4 --delay 1 --export-json stark-b/stark_broadening.json
```

不传 `--elements` / `--charges` 就是全物种；截断响应按波长分区继续下载。
重复运行会校验并复用成功快照，重试失败、缺失和损坏物种。
`--refresh` 重新发现物种并重取全部表；不要同时向同一采集目录运行多个进程。
官网 VAMDC 返回 HTTP 400 时使用官方 HTML 表单逐数据集、逐发布密度补取。

下载后可完全离线重新导出：

```powershell
& 'E:/Anaconda/envs/simLIBS/python.exe' stark_data_collect.py --export-only --export-json stark-b/stark_broadening.json
```

默认拒绝导出未完整的缓存。确需部分产物时加 `--allow-partial`，产物仍会
保持 `complete=false` 和失败清单。原始分物种缓存在 `stark-b/species/`。

## 模拟与缺失

数据库表必须匹配同一元素、电荷与量子态身份，再在原表温度范围、有效密度
和警告条件内求宽度。不能按最近波长借用其他跃迁，也不能向表外温度外推。
数据库没有可用宽度时才尝试 DK1980；其实际电荷限制为 q=2/3，需要可追溯
能级、跃迁概率、有效主量子数和完整扰动阵列。缺少输入不意味着贡献为零。
两层均不可用时记录缺失，沿用模拟配置的报错或显式跳过策略。

准备 NIST 原子输入：

```powershell
& 'E:/Anaconda/envs/simLIBS/python.exe' stark_semiempirical_check.py fetch-atomic
```

`sample/models.json` 保存预构造输入和缺失原因，`sample/*_atomic.json` 保存
可复用的 NIST 原子数据与来源。模型估算会保留来源和假设；STARK-B 对照
本身也不等同于独立实验真值。

本次为5329条候选记录重新准备原子输入，其中162条满足自动模型要求。
Co III、Mn III的NIST响应没有可用的已解析LS能级，相关失败明确保留；
原子输入清单的 `complete=false` 不表示STARK-B下载失败，两份清单的
完整性描述的是不同阶段。
