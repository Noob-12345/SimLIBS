from simLIBS import SimulatedLIBS
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import os


project_dir = Path(__file__).resolve().parent
contents = pd.read_csv(project_dir / "saved" / "contents.csv")

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
        instrument_broadening=False
    )
    save_dir = r"D:\LIBS\simLIBS\simLIBS-2.0.3\saved"
    libs.plot()
    plt.show()
    libs.save_to_csv(os.path.join(save_dir, file_name + "_95.csv"))
    print( f'{file_name}_95.csv',"saved successfully.")


