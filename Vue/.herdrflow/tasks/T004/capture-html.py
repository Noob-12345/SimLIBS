from pathlib import Path
import hashlib,json,requests
from bs4 import BeautifulSoup
root=Path('.herdrflow/tasks/T004');out=root/'fixtures';out.mkdir(exist_ok=True)
urls={'periodic':'https://physics.nist.gov/PhysRefData/Handbook/periodictable.htm'}
for slug in ('iron','magnesium','hydrogen'):
    for table in (3,4):urls[f'{slug}{table}']=f'https://physics.nist.gov/PhysRefData/Handbook/Tables/{slug}table{table}.htm'
records=[]
for name,url in urls.items():
    r=requests.get(url,timeout=(8,18),verify=True,allow_redirects=False)
    (out/(name+'.html')).write_bytes(r.content)
    soup=BeautifulSoup(r.content,'html.parser')
    records.append(dict(file=name+'.html',url=url,status=r.status_code,sha256=hashlib.sha256(r.content).hexdigest(),title=soup.title.get_text(' ',strip=True) if soup.title else '',bytes=len(r.content)))
    if name in ('iron3','magnesium3','hydrogen4'):
        print(name,records[-1]['title'])
        for table in soup.find_all('table'):
            own=[tr for tr in table.find_all('tr') if tr.find_parent('table') is table]
            for i,tr in enumerate(own[:7],1):
                cells=tr.find_all(['th','td'],recursive=False)
                print(i,[(c.get_text(' ',strip=True),c.get('rowspan'),c.get('colspan')) for c in cells][:40])
(root/'captured-http.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
