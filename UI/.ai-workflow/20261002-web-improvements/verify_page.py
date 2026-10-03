"""真实8517页面四视口/上下滚动/黑红和亮主题截图；隔离缓存Chrome，不碰用户浏览器。"""
import json
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tests.web_browser_support import BrowserCase
from urllib.request import urlopen
from simlibs_ui.storage import write_json

OUT=Path(__file__).parent/'page-evidence';OUT.mkdir(parents=True,exist_ok=True)
science=json.loads((Path(__file__).parent/'scientific'/'checks.json').read_text(encoding='utf-8'))
jid=science['requests'][1]['job_id']
with urlopen('http://127.0.0.1:8517/api/jobs/'+jid+'/result',timeout=30) as r:result=json.load(r)
BrowserCase.setUpClass()
d=BrowserCase.driver;report=[]
try:
    d.get('http://127.0.0.1:8517/')
    from selenium.webdriver.support.ui import WebDriverWait
    WebDriverWait(d,10).until(lambda d:d.execute_script("return typeof state!=='undefined'&&state.previewUnsupported"))
    d.execute_script("""document.querySelector('#lowW').value=400;document.querySelector('#upW').value=700;
      document.querySelector('#intensityScale').value='energy';document.querySelector('#chartTitle').value='H 100% - Energy flux [a.u.]';
      renderSingleResult(arguments[0],arguments[1]);drawSingle(specData,true);""",jid,result)
    for width,height in [(1366,768),(1280,720),(1024,768),(1920,1080)]:
        d.set_window_size(width,height)
        d.execute_async_script('const done=arguments[0];requestAnimationFrame(()=>requestAnimationFrame(done));')
        d.execute_script("document.querySelector('#content').scrollTop=0;drawSingle(specData,true)")
        metrics=d.execute_script("""const c=document.querySelector('#content'),m=document.querySelector('#main');return {
          inner:[innerWidth,innerHeight],mainBottom:m.getBoundingClientRect().bottom,documentWidth:document.documentElement.scrollWidth,
          clientHeight:c.clientHeight,scrollHeight:c.scrollHeight,scrollBefore:c.scrollTop,
          mode:document.documentElement.dataset.theme,scale:specData.meta.intensity_scale,points:specData.xs.length,
          rawPoints:specData.series.raw.xs.length};""")
        assert metrics['mainBottom']<=metrics['inner'][1]+1 and metrics['documentWidth']<=metrics['inner'][0]+1
        d.save_screenshot(str(OUT/f'home-{width}.png'))
        center=d.execute_script("const r=document.querySelector('#content').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}")
        d.execute_cdp_cmd('Input.dispatchMouseEvent',dict(type='mouseWheel',x=center['x'],y=center['y'],deltaX=0,deltaY=5000))
        d.execute_async_script('const done=arguments[0];requestAnimationFrame(()=>requestAnimationFrame(done));')
        metrics['scrollAfter']=d.execute_script("return document.querySelector('#content').scrollTop")
        if metrics['scrollHeight']>metrics['clientHeight']:assert metrics['scrollAfter']>0
        for selector in ['#runBtn','#logbox','#specChart']:
            d.execute_script("document.querySelector(arguments[0]).scrollIntoView({block:'center'})",selector)
            rectangle=d.execute_script("const r=document.querySelector(arguments[0]).getBoundingClientRect();return {top:r.top,bottom:r.bottom,right:r.right}",selector)
            assert rectangle['top']>=54 and rectangle['bottom']<=metrics['inner'][1]+1 and rectangle['right']<=metrics['inner'][0]+1
        d.execute_script("document.querySelector('#content').scrollTop=1e6")
        d.save_screenshot(str(OUT/f'scrolled-{width}.png'))
        report.append(dict(requested=[width,height],**metrics))
    d.set_window_size(1366,768)
    d.execute_script("document.querySelector('#themeBtn').click();document.querySelector('#specChart').scrollIntoView({block:'center'});drawSingle(specData,true)")
    d.execute_async_script('setTimeout(arguments[0],450)')
    d.execute_script('drawSingle(specData,true)')
    d.save_screenshot(str(OUT/'light-spectrum.png'))
    assert d.execute_script('return specData.meta.intensity_scale')=='energy'
    write_json(OUT/'checks.json',{'viewports':report,'live_job':jid,'source':'real energy result already generated, no extra NIST requests','light_preserves_scale':True})
    print(json.dumps(report,ensure_ascii=False,indent=2))
finally:BrowserCase.tearDownClass()
