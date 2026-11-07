"""Downloadable actual rows plus a template-compatible CSV, always paired with saved spectra."""
from pathlib import Path
import pandas as pd
from .storage import read_manifest,write_csv

def write_actual_parameters(directory,plan,records):
    elements=sorted({el for entry in plan['entries'] for el in entry['parameters']['elements']})
    actual=[];templates=[]
    for record in records:
        index=record['index'];sample=read_manifest(record['manifest']);origin=sample['origin'];p=origin['parameters']
        labels={el+'_at%':pct for el,pct in zip(p['elements'],p['percentages'])}
        template={'name':plan['entries'][index]['name'],**{el+'_at%':labels.get(el+'_at%',0) for el in elements},
          'Te[eV]':p['Te'],'Ne[cm^-3]':p['Ne'],'R':p['resolution'],'low_w[nm]':p['low_w'],'upper_w[nm]':p['upper_w'],
          'grid_step[nm]':p['broaden_grid_step'],'max_ion_charge':p['max_ion_charge'],
          'broaden':p.get('local_broadening_enabled',True),'resample':p['resample'],'step[nm]':p['step'],
          'doppler_mode':p.get('local_temperature_mode','manual'),'T_h[K]':p['local_temperature_K'] if p.get('local_temperature_mode','manual')=='manual' else '',
          'intensity_scale':p['intensity_scale']}
        templates.append(template)
        actual.append({'index':index+1,**template,'effective_T_h[K]':origin.get('effective_heavy_temperature_K'),
                       'effective_R':origin.get('actual_resolution'),'source_manifest':record['manifest']})
    paths={'actual_parameters':str(Path(directory)/'actual_parameters.csv'),'template_csv':str(Path(directory)/'template.csv')}
    for key,rows in [('actual_parameters',actual),('template_csv',templates)]:
        if rows:write_csv(paths[key],pd.DataFrame(rows))
    return paths if actual else {}
