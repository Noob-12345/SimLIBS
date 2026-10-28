"""当前 NIST Stark/逐线自吸收示例：联网取元素谱线并导出逐线诊断。

从项目目录运行 python examples/nist_self_absorption_demo.py --help 查看参数。
默认采用 Si II 真空波长窄窗口，Stark 系数统一查询 STARK-B。
调试顺序：config -> SimulatedLIBS -> line_diagnostics.csv。
--stark-only 关闭自吸收；--no-instrument-broadening 关闭仪器高斯响应。
系数缺失时导出 missing_stark.csv 和已匹配清单，返回 2；取数失败返回 3。
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
# 从源码运行示例时优先导入本项目的 simLIBS，便于对正在编辑的函数下断点。
sys.path.insert(0, str(ROOT))
from simLIBS import SimulatedLIBS, MissingStarkDataError, StarkDataAccessError


def main():
    """读取命令行配置，运行当前主入口，并按结果类别分别导出文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--element', default='Si', help='单元素符号，例如 Si、Fe、Al')
    parser.add_argument('--te', type=float, default=1., help='电子温度，eV')
    parser.add_argument('--ne', type=float, default=1e17, help='电子密度，cm^-3')
    parser.add_argument('--max-charge', type=int, default=2, help='最高离子电荷，0 为仅中性')
    # 默认窄窗口包含已有真实 STARK-B 响应夹具验证的 Si II 线。
    parser.add_argument('--low', type=float, default=634.88)
    parser.add_argument('--high', type=float, default=634.90)
    parser.add_argument('--step', type=float, default=.001)
    parser.add_argument('--path-length', type=float, default=.001)
    parser.add_argument('--missing-stark', choices=['error', 'unbroadened'], default='error',
                        help='数据库缺系数时：报错，或保留未展宽谱线')
    parser.add_argument('--cache-dir', type=Path, help='STARK-B 与 NIST 身份快照目录')
    parser.add_argument('--offline-stark', action='store_true', help='Stark 数据只读缓存；NIST 计算谱仍需联网')
    parser.add_argument('--stark-methods', nargs='+', choices=['SCP', 'MSE'], default=['SCP', 'MSE'])
    parser.add_argument('--stark-only', action='store_true', help='只计算 Stark 展宽，不计算自吸收')
    parser.add_argument('--no-instrument-broadening', action='store_true', help='关闭仪器高斯响应')
    parser.add_argument('--output', type=Path, default=ROOT/'output'/'nist_self_absorption')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # 光程使用 m，采样步长使用 nm；数据库响应缓存保留完整来源。
    config = dict(path_length_m=args.path_length, wavelength_step_nm=args.step,
                  missing_stark=args.missing_stark, stark_cache_dir=args.cache_dir,
                  stark_allow_network=not args.offline_stark, stark_methods=args.stark_methods)
    try:
        libs = SimulatedLIBS(Te=args.te, Ne=args.ne, elements=[args.element], percentages=[100],
                             low_w=args.low, upper_w=args.high, resolution=3000,
                             max_ion_charge=args.max_charge,
                             webscraping='static', self_absorption=not args.stark_only,
                             stark_broadening=True,
                             instrument_broadening=not args.no_instrument_broadening,
                             self_absorption_config=config)
    except MissingStarkDataError as error:
        # missing_lines 是完整缺失清单；错误消息只预览部分谱线。
        path = output/'missing_stark.csv'
        error.missing_lines.to_csv(path, index=False)
        error.matched_lines.to_csv(output/'matched_stark.csv', index=False)
        print(str(error))
        print(f'Missing STARK-B coefficients: {path}')
        print('Use --missing-stark unbroadened to retain these lines without Stark correction.')
        return 2
    except StarkDataAccessError as error:
        # 区分“数据库没有系数”和“请求/缓存失败”，避免按错误原因补数据。
        print(f'Stark data access failed: {error}')
        return 3
    # 三类排查数据：吸收/薄谱看线形，nist_sticks 看原始线强，diagnostics 看逐线物理量。
    # 仅 Stark 时使用不同文件名，明确输出未应用自吸收。
    libs.save_to_csv(output/('stark_only.csv' if args.stark_only else 'absorbed.csv'))
    libs.unabsorbed_raw_spectrum.to_csv(output/'thin_voigt.csv', index=False)
    libs.line_table.to_csv(output/'nist_sticks.csv', index=False)
    libs.self_absorption_diagnostics.to_csv(output/'line_diagnostics.csv', index=False)
    # 元数据记录模型假设、布居、总密度、光程和实际输出步长，方便复查同次模拟。
    (output/'metadata.json').write_text(
        json.dumps(libs.self_absorption_metadata, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8')
    print(f'Generated {len(libs.self_absorption_diagnostics)} transitions; results: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
