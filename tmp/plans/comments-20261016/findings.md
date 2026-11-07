# 注释核对依据

- 当前主入口：SimulatedLIBS(static, self_absorption=True) -> retrieve_data_static -> prepare_nist_absorption -> _render_paper_model -> render_nist_absorption。
- 当前线上入口从 NIST 获取线强和能级；resolve_stark 仅匹配用户数据及本地 JSON，未接入 STARK-B 网络查询。
- self_absorption.py 同时包含共享数值工具、结果容器和独立的离线 I/II/III 论文模型；原模块首部部分描述已过时，需要澄清。
- 当前 NIST 路径的仪器宽度 lambda/R 是高斯 1/e 半宽；离线模型使用 lambda/R 作为高斯 FWHM，两者须分别注释。
- 自吸收计算使用内禀 Stark FWHM；SA 控制内禀峰高，面积需乘 SA^0.46，宽度乘 SA^-0.54；仪器展宽后的峰高比不必等于 SA。
- 注释风险主要是文档描述与实际行为不一致、误改公式、中文编码问题。使用 AST 等价、语法编译、现有离线测试和差异检查验证。
- 所有上述验证已完成：7 个源文件、65 个有文档说明的组件、47 项现有测试；实现语法树保持等价。
- 已在注释中覆盖零光程/零数密度极限、同波长多跃迁、缺失/歧义 Stark 系数、网格/资源限制及缓存重绘的行为。
