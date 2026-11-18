"""Planning evidence only: fetch a bounded set of public NIST Handbook pages."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

root=Path(__file__).resolve().parent/'official'
root.mkdir(exist_ok=True)
base='https://physics.nist.gov/PhysRefData/Handbook/'
targets=['periodictable.htm','Tables/irontable3.htm','Tables/irontable4.htm',
         'Tables/hydrogentable3.htm','Tables/heliumtable4.htm','Tables/leadtable3.htm']
def capture(relative):
    url=urljoin(base,relative)
    response=requests.get(url,timeout=(8,20))
    response.raise_for_status()
    data=response.content
    if len(data)>2_000_000:raise RuntimeError('Evidence response larger than 2MB')
    (root/Path(relative).name).write_bytes(data)
    soup=BeautifulSoup(data,'html.parser')
    tables=[t for t in soup.find_all('table') if not t.find('table') and 'Wavelength' in t.get_text()]
    rows=[]
    if tables:
        for index,row in enumerate(tables[0].find_all('tr')):
            cells=row.find_all(['td','th'],recursive=False)
            if len(cells) in (8,9):rows.append({'row':index+1,'cells':[c.get_text(' ',strip=True) for c in cells]})
    return {'url':url,'final_url':response.url,'status':response.status_code,'bytes':len(data),
            'sha256':hashlib.sha256(data).hexdigest(),'fetched_at':datetime.now(timezone.utc).isoformat(),
            'title':soup.title.get_text(' ',strip=True) if soup.title else '',
            'headers':[h.get_text(' ',strip=True) for h in tables[0].find_all('th')] if tables else [],
            'first_rows':rows[:6],'data_rows':len(rows),
            'medium_notes':[x.strip() for x in soup.stripped_strings if 'air' in x.lower() or 'vacuum' in x.lower()]}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    results=list(executor.map(capture,targets))
(root/'captured.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=True,indent=2))
