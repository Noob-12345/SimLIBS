import sys,json,hashlib,requests
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'backend'))
from bs4 import BeautifulSoup
from simlibs_ui.spectrum_nist import element_urls,parse_html,CONNECT_TIMEOUT,READ_TIMEOUT
result=[]
for element in ('Fe','Mg'):
    session=requests.Session();urls=element_urls(element,session);item={'element':element,'states':{}}
    for species,url in urls.items():
        try:
            response=session.get(url,timeout=(CONNECT_TIMEOUT,READ_TIMEOUT),verify=True,allow_redirects=False);body=response.content;soup=BeautifulSoup(body,'html.parser')
            state={'url':url,'status':response.status_code,'bytes':len(body),'html_sha256':hashlib.sha256(body).hexdigest(),'fetched_at':datetime.now(timezone.utc).isoformat(),'title':soup.title.get_text(' ',strip=True) if soup.title else ''}
            if response.status_code==200:
                group=parse_html(body,url,element,species);state.update(available=True,count=group['count'],first=group['positions'][0])
            else:state.update(available=False,error='HTTP '+str(response.status_code))
        except Exception as error:state={'url':url,'available':False,'error':str(error)}
        item['states'][species]=state
    session.close();result.append(item)
out=Path('.herdrflow/tasks/T004/live-nist.json')
out.write_text(json.dumps({'taskId':'T004','dispatchId':'229c687f-8bda-4b35-bea4-2e7841ace916','revision':1,'at':datetime.now(timezone.utc).isoformat(),'mode':'real requests HTTPS, no mocks','source':'NIST Handbook Persistent Lines','elements':result},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
if any(not item['states'][species].get('available') for item in result for species in ('I','II')):sys.exit(1)
