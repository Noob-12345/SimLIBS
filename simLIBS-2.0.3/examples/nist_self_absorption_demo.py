"""NIST Mg example; expand the window and supply a coefficient CSV as needed."""
import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simLIBS import SimulatedLIBS, MissingStarkDataError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # 默认窄窗口包含一条有内置 Stark 数据的 Mg I 线；全波段可用 --low 280 --high 290。
    parser.add_argument('--low', type=float, default=285.27)
    parser.add_argument('--high', type=float, default=285.33)
    parser.add_argument('--step', type=float, default=.001)
    parser.add_argument('--path-length', type=float, default=.001)
    parser.add_argument('--stark-csv', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'output'/'nist_self_absorption')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = dict(path_length_m=args.path_length, wavelength_step_nm=args.step)
    if args.stark_csv:
        config['stark_data'] = pd.read_csv(args.stark_csv)
    try:
        libs = SimulatedLIBS(Te=1.0, Ne=1e17, elements=['Mg'], percentages=[100],
                             low_w=args.low, upper_w=args.high, resolution=3000,
                             webscraping='static', self_absorption=True,
                             self_absorption_config=config)
    except MissingStarkDataError as error:
        path = output/'missing_stark.csv'
        error.missing_lines.to_csv(path, index=False)
        print(str(error))
        print(f'Missing coefficient template: {path}')
        print('Fill stark_width_nm from a cited source, then rerun with --stark-csv. '
              'W is the coefficient in FWHM=2*W*Ne/Ne_ref.')
        return 2
    libs.save_to_csv(output/'absorbed.csv')
    libs.unabsorbed_raw_spectrum.to_csv(output/'thin_voigt.csv', index=False)
    libs.line_table.to_csv(output/'nist_sticks.csv', index=False)
    libs.self_absorption_diagnostics.to_csv(output/'line_diagnostics.csv', index=False)
    (output/'metadata.json').write_text(
        json.dumps(libs.self_absorption_metadata, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8')
    print(f'Generated {len(libs.self_absorption_diagnostics)} transitions; results: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
