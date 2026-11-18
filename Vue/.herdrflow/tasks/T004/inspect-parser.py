import sys,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'backend'))
from simlibs_ui.spectrum_nist import parse_html
for slug,el in [('iron','Fe'),('magnesium','Mg'),('hydrogen','H')]:
    for table,species in [(3,'I'),(4,'II')]:
        try:
            group=parse_html(Path(f'.herdrflow/tasks/T004/fixtures/{slug}{table}.html').read_bytes(),f'https://physics.nist.gov/PhysRefData/Handbook/Tables/{slug}table{table}.htm',el,species)
            print(el,species,group['count'],json.dumps(group['positions'][0],ensure_ascii=False),group['metadata']['aki_header'])
        except ValueError as error:print(el,species,'ERROR',str(error))
