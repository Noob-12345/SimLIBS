"""当前 NIST Stark/逐线自吸收示例：联网取 Mg 谱线并导出逐线诊断。

从项目目录运行 python examples/nist_self_absorption_demo.py --help 查看参数。
默认采用真空波长窄窗口，便于检查一条有内置 Stark 系数的跃迁；扩大窗口后
可能需要 --stark-csv。调试顺序：config -> SimulatedLIBS -> line_diagnostics.csv。
--stark-only 关闭自吸收；--no-instrument-broadening 关闭仪器高斯响应。
系数缺失时只导出 missing_stark.csv 模板，并以状态码 2 返回。
"""
import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# 从源码运行示例时优先导入本项目的 simLIBS，便于对正在编辑的函数下断点。
sys.path.insert(0, str(ROOT))
from simLIBS import SimulatedLIBS, MissingStarkDataError


def main():
    """读取命令行配置，运行当前主入口，并按结果类别分别导出文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    # 默认窄窗口包含一条有内置 Stark 数据的 Mg I 线；全波段可用 --low 280 --high 290。
    parser.add_argument('--low', type=float, default=285.27)
    parser.add_argument('--high', type=float, default=285.33)
    parser.add_argument('--step', type=float, default=.001)
    parser.add_argument('--path-length', type=float, default=.001)
    parser.add_argument('--stark-csv', type=Path)
    parser.add_argument('--stark-only', action='store_true', help='只计算 Stark 展宽，不计算自吸收')
    parser.add_argument('--no-instrument-broadening', action='store_true', help='关闭仪器高斯响应')
    parser.add_argument('--output', type=Path, default=ROOT/'output'/'nist_self_absorption')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # 光程使用 m，采样步长使用 nm；CSV 中 W 的约定为 FWHM=2*W*Ne/Ne_ref。
    config = dict(path_length_m=args.path_length, wavelength_step_nm=args.step)
    if args.stark_csv:
        config['stark_data'] = pd.read_csv(args.stark_csv)
    try:
        libs = SimulatedLIBS(Te=1.0, Ne=1e17, elements=['Mg'], percentages=[100],
                             low_w=args.low, upper_w=args.high, resolution=3000,
                             webscraping='static', self_absorption=not args.stark_only,
                             stark_broadening=True,
                             instrument_broadening=not args.no_instrument_broadening,
                             self_absorption_config=config)
    except MissingStarkDataError as error:
        # missing_lines 是完整缺失清单；错误消息只预览部分谱线，补数应以 CSV 为准。
        path = output/'missing_stark.csv'
        error.missing_lines.to_csv(path, index=False)
        print(str(error))
        print(f'Missing coefficient template: {path}')
        print('Fill stark_width_nm from a cited source, then rerun with --stark-csv. '
              'W is the coefficient in FWHM=2*W*Ne/Ne_ref.')
        return 2
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
