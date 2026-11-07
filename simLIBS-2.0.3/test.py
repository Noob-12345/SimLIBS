from simLIBS import SimulatedLIBS, MissingStarkDataError
from pathlib import Path
import argparse
import matplotlib.pyplot as plt
import pandas as pd


parser = argparse.ArgumentParser(description="Run the sample with Stark broadening only.")
parser.add_argument("--no-show", action="store_true", help="Save the plot without opening a window.")
args = parser.parse_args()
project_dir = Path(__file__).resolve().parent
save_dir = project_dir / "saved"
save_dir.mkdir(parents=True, exist_ok=True)
contents = pd.read_csv(save_dir / "contents.csv")

for i in range(0,1):
    elements_main=['Si', 'Al', 'Fe','Ca','K','Na','Mg','Cr','Cu','Mn','Zn','Ti','Ni','Mo','C','Li','Pb']
    elements_rareearth=['Lu','La','Y','Pr','Sm','Eu','Tb','Ho','Er','Tm','Yb']
    elements=elements_main + elements_rareearth
    file_name=contents.iloc[i, 0]
    file_name = str(contents.iloc[i, 0]).removeprefix("GBW")
    percentages_main=contents.iloc[i, 1:].tolist()
    percentages_rareearth=[0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545] 
    percentages=percentages_main + percentages_rareearth  

        # Remove elements with zero percentage
    elements = [elem for elem, perc in zip(elements, percentages) if perc > 0]
    percentages = [perc for perc in percentages if perc > 0]

    if len(percentages) > 0:
        percentages[-1] = 100.0 - sum(percentages[:-1])

    print(f"Simulating {file_name}: Stark only, 200-900 nm, {len(elements)} elements.", flush=True)
    try:
        libs = SimulatedLIBS(
            Te=0.86,
            Ne=10**17,
            elements=elements,
            percentages=percentages,
            resolution=4000,
            low_w=200,
            upper_w=900,
            max_ion_charge=2,
            webscraping='static',
            headless=True,
            keep_browser_open=False,
            detach_browser=False,
            stark_broadening=True,
            instrument_broadening=False,
            self_absorption_config={"missing_stark": "unbroadened"}
        )
    except MissingStarkDataError as error:
        missing_path = save_dir / f"{file_name}_95_missing_stark.csv"
        matched_path = save_dir / f"{file_name}_95_matched_stark.csv"
        error.missing_lines.to_csv(missing_path, index=False)
        error.matched_lines.to_csv(matched_path, index=False)
        print(f"Stark coefficients: {len(error.matched_lines)} matched, {len(error.missing_lines)} missing.")
        print(f"Missing coefficients and reasons: {missing_path}")
        print(f"Matched coefficients and sources: {matched_path}")
        raise

    # Export before the interactive plot blocks until its window is closed.
    libs.save_to_csv(save_dir / f"{file_name}_95.csv")
    print(f'{file_name}_95.csv', "saved successfully.")
    missing_path = save_dir / f"{file_name}_95_missing_stark.csv"
    libs.missing_stark_lines.to_csv(missing_path, index=False)
    libs.matched_stark_lines.to_csv(save_dir / f"{file_name}_95_matched_stark.csv", index=False)
    print(f"Stark coefficients: {len(libs.matched_stark_lines)} matched, {len(libs.missing_stark_lines)} missing.")
    if not libs.missing_stark_lines.empty:
        print("Missing-coefficient lines retain their NIST areas without Stark broadening.")
        print(f"Missing lines and reasons: {missing_path}")
    libs.plot()
    plt.savefig(save_dir / f"{file_name}_95_stark.png", dpi=150)
    if not args.no_show:
        plt.show()
    plt.close()


