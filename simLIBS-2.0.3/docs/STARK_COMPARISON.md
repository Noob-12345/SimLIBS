# STARK-B 与修正半经验模型的批量比较

2026-11-04：用户已授权运行，已实际采集 STARK-B/NIST、计算误差并生成图片。
全库采集范围与失败/未完成情况以 stark-b/manifest.json 为准；当前可比较
子集结果见 stark-b/comparison/report.md，不代表所有元素均有可用原子输入。

## 文件与目录

| 文件/目录 | 用途 |
| --- | --- |
| stark_data_collect.py | 全物种发现、完整分区采集、断点续取与离线校验 |
| stark_atomic_data.py | NIST 能级、E1 跃迁概率和电离阈值；严格构造模型输入 |
| stark_semiempirical_check.py | 分阶段入口、计算、统计、绘图与分析报告 |
| stark-b/ | 原始 XSAMS、电子宽度表、物种清单和 manifest |
| sample/ | NIST 原始响应、标准原子数据、模型输入和缺失原因 |
| stark-b/comparison/ | 比较 CSV、跳过清单、统计 JSON、分析报告和图片 |

依赖 requests，出图另需 matplotlib；使用项目已有的 simLIBS 环境。
新工具独立加载既有 VAMDC 客户端，不需要启动主模拟器或浏览器。

## 执行命令

在项目目录打开 PowerShell，依次执行：

    & 'D:/Anaconda3/envs/simLIBS/python.exe' stark_semiempirical_check.py fetch-stark
    & 'D:/Anaconda3/envs/simLIBS/python.exe' stark_semiempirical_check.py fetch-atomic
    & 'D:/Anaconda3/envs/simLIBS/python.exe' stark_semiempirical_check.py compare

主动执行三个阶段使用 all。fetch-stark 默认全部元素和电离态，不设元素
清单或电离态上限；可先用以下筛选检查服务响应与格式：

    & 'D:/Anaconda3/envs/simLIBS/python.exe' stark_semiempirical_check.py all --elements C Si --charges 3

这个示例仅用于首次验证流程，不代表全元素覆盖。--refresh 重新采集，
默认校验后续用快照；--delay 1.0 控制请求间隔。默认拒绝不完整快照，
--allow-partial 显式允许成功子集。不要并发向同一目录写入。
默认数据目录均相对于脚本位置，不依赖启动程序时的当前目录。
--workers 4 启用最多四个物种并发；请求共享节流。单次响应最大 20 MiB，
从请求开始到流式读完检查 120 秒总时限，超限记失败，不保存部分数据。

## 比较口径

1. STARK-B 本节点电子宽度是 FWHM，单位 Å；转 nm 除以 10，不能乘二。
2. 每个样本使用原表的温度 T 与电子密度 Ne，两边使用相同的数据库计算
   波长。不按最近波长匹配，不对温度插值或外推。
3. 系数 alpha_nm_cm3 = FWHM_nm / Ne_cm^-3；另给乘以 1e17 后的归一化
   宽度。这只是比较系数的写法，不证明参考密度下近似依然有效。
4. 有符号相对偏差 = 100 × (模型/数据库 - 1)。正值表示模型偏宽。
   同时输出绝对相对偏差、比值和 log10(模型/数据库)。
5. 抓取全物种，现有模型只计算实际电荷 q=2/3；其他电荷在跳过清单中。
6. 任何非空原表警告默认排除。C 未导出则隔离条件未知；无警告不等于
   碰撞近似已验证。VAMDC 未导出方法时记 unreported，不能推定为 SCP。
7. 明确为 MSE 的来源另行分层。STARK-B 对照不等于实验真值，与同源 MSE
   一致也不能证明独立实验精度；引用时仍需核对每条数据的原始文献。

## 原子数据与覆盖率

只对 STARK-B 已有且当前模型支持的候选物种获取 NIST 数据。目标上下
能级还与其他扰动能级耦合，故同物种需批量下载完整能级与 E1 线表，
随后只构造目标谱线及其扰动阵列，不查询无关元素。

能级本身不足以确定矩阵元；从 NIST 跃迁概率换算：

    S_JJ' (a0²) = Aki (s^-1) × g_upper × lambda_A³ / 2.02613e18
    R²_array = sum(S_JJ') / [(2L+1)(2S+1)]

自动模式只处理明确闭壳层芯+单价电子、完整双重态 LS 阵列。能量重心按
2J+1 加权，允许的 E1 精细结构分量必须完整。同 n 的 l±1 阵列若物理存在
必须有数据，有效主量子数由电离阈值减去项重心能量求得。

这种用 Aki 构造 LS 阵列的方法，与原文 Bates–Damgaard 径向积分表不是
逐项完全相同的原子输入，报告会标注 atomic_quality=nist-aki-complete。
复杂组态、缺失 Aki、非明确 LS 项、歧义阈值、未匹配状态均列原因；
不取最近能级、不默认为 phi=1、不把未知贡献当零。

## 补充复杂离子的输入

从 sample/models.json 复制目标表的 key，创建 sample/manual_inputs.json：

    {
      "models": [{
        "key": "复制目标表的完整key",
        "atomic_source": "原子结构计算/文献/数据文件的可核查出处",
        "lower": {
          "n_eff": 3.0, "l": 0,
          "same_n": [{"delta_e_ev": 2.0, "matrix_element_sq_a0": 18.0}]
        },
        "upper": {
          "n_eff": 3.0, "l": 1,
          "same_n": [
            {"delta_e_ev": 2.0, "matrix_element_sq_a0": 6.0},
            {"delta_e_ev": 2.0, "matrix_element_sq_a0": 7.5}
          ]
        }
      }]
    }

数值只演示结构，不能作为真实离子参数。手工数据来源不可空，阵列
完备性需自行核对；统计标注 manual，并与自动构造结果分开。

## 输出分析

- comparison.csv：逐点系数、误差、原子输入质量和出处。
- skipped.csv：超适用电荷、原表警告、缺数据、歧义身份、计算失败等原因。
- summary.json：覆盖率、点等权与谱线等权统计，按元素、电荷、来源方法
  和原子质量分层。唯一线身份含来源/数据集，不代表独立实验次数。
- comparison.png：对角比较图、温度残差、对数比值分布、元素误差。
  无成功比较点时只给报告，不生成虚假占位图。
- report.md：根据实际运行结果描述偏差、覆盖和主要缺失原因。

离线回归测试可运行：

    & 'D:/Anaconda3/envs/simLIBS/python.exe' -m unittest discover -s tests -p test_stark_comparison.py -v

首次联网仍需检查 NIST 导出格式、数据完整性、物种发现截断，并人工
查看成图。静态检查不能代替这些运行验证。
