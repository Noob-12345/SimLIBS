# 自吸收组件中文注释

## 当前目标
根据用户明确要求，为已新增的自吸收组件补充中文注释，便于追踪模块职责、调用链、物理量单位和异常。只修改注释、文档字符串，不改变计算逻辑。

## 执行批次
1. [complete] 三个计算模块：nist_lines.py、nist_self_absorption.py、self_absorption.py。AST、语法和每个函数/类的文档字符串检查通过。
2. [complete] 两个入口文件：simulation.py、__init__.py。
3. [complete] 两个示例：nist_self_absorption_demo.py、paper_self_absorption_demo.py。
4. [complete] 7 个文件的 AST、语法、UTF-8 和全部 65 个模块/类/函数文档检查通过；现有 47 项测试通过，git diff --check 通过。

## 范围与约束
- 保留用户已有的源码注释，修正文档中确实过时的模块职责描述。
- 标注 W/FWHM、nm/m、cm^-3/m^-3、eV/cm^-1 和两个入口各自的仪器宽度约定。
- STARK-B 自动查询方案仍待批准，本次不实施该功能。
- 不修改既有 CSV 删除状态、原子数据、测试行为或 Vue 副本。
