from simLIBS import SimulatedLIBS
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import os


contents=pd.read_csv(r"D:\LIBS\simLIBS-2.0.3\simLIBS-2.0.3\saved\contents.csv")
# elements_main=['Si', 'Al', 'Fe','Ca','K','Na','Mg','Cr','Cu','Mn','Zn','Ti','Ni','Mo','C','Li','Pb']
# elements_rareearth=['Lu','La','Y','Pr','Sm','Eu','Tb','Ho','Er','Tm','Yb']
# elements=elements_main + elements_rareearth
for i in range(0, len(contents)):
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
        webscraping='dynamic',
        headless=True,
        keep_browser_open=False,
        detach_browser=False
    )
    save_dir = r"D:\LIBS\simLIBS-2.0.3\simLIBS-2.0.3\saved"
    libs.save_to_csv(os.path.join(save_dir, file_name + "_95.csv"))
    print( f'{file_name}_95.csv',"saved successfully.")

# print(len(percentages))



# elements=['Si', 'Al', 'Fe','Ca','K','Na','Mg','Cr','Cu','Mn','Zn','Ti','Ni','Mo','C','Li','Pb',
#               'Lu','La','Y','Pr','Sm','Eu','Tb','Ho','Er','Tm','Yb']
# percentages=[54.00707155,5.7832941,7.1368921,18.57346235,0.7932652,1.6451036,6.0353367,0.00022705,0.00045315,0.9495364,0.03095955,0,0.00521645,0.0390108,0,0,0.00017005,
# 0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545,0.4545]

# # Remove elements with zero percentage
# elements = [elem for elem, perc in zip(elements, percentages) if perc > 0]
# percentages = [perc for perc in percentages if perc > 0]

# # elements=['Al', 'Fe', 'Mo']
# # percentages=[10, 80, 10]
# if len(percentages) > 0:
#     percentages[-1] = 100.0 - sum(percentages[:-1])

# # print(np.sum(percentages))
# libs = SimulatedLIBS(
#     Te=0.86,
#     Ne=10**17,
#     elements=elements,
#     percentages=percentages,
#     resolution=5000,
#     low_w=200,
#     upper_w=900,
#     max_ion_charge=2,
#     webscraping='dynamic',
#     headless=True,
#     keep_browser_open=False,
#     detach_browser=False
# )
# file_name='07141'
# save_dir = r"D:\LIBS\simLIBS-2.0.3\simLIBS-2.0.3\saved"
# libs.save_to_csv(os.path.join(save_dir, file_name + "_95.csv"))
# print("File saved successfully.")