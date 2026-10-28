"""simLIBS 对外导入入口。

常用方式：from simLIBS import SimulatedLIBS, NISTSelfAbsorptionConfig,
MissingStarkDataError。导入只暴露对象；实例化 SimulatedLIBS 时才开始取数和计算。
Stark 系数统一使用 STARK-B 数据库及其已验证响应缓存。
"""

# 公共基础参数校验；更严格的物理/数据校验由对应模型完成。
from simLIBS.simulation import validate_simulated_libs

# 主模拟类：静态普通谱、静态逐线自吸收、动态浏览器取谱的统一入口。
from simLIBS.simulation import SimulatedLIBS
# 当前 NIST 自吸收的配置对象和可导出完整缺失跃迁清单的异常类型。
from simLIBS.nist_self_absorption import NISTSelfAbsorptionConfig, MissingStarkDataError
# 自动数据源的网络/缓存异常，与确实缺少逐线系数的异常分别处理。
from simLIBS.stark_b import StarkDataAccessError
