import json
import os
from pathlib import Path
import time
import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from tests.web_browser_support import BrowserCase
from simlibs_ui.settings import UI_ROOT
from simlibs_ui.mode_engine import RECALC_OBSERVER


@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST')=='1','隔离 Chrome 完整节点验证')
class FidelityBrowserTests(BrowserCase):
    def fixture(self):
        return self.js("""const n=50001,xs=Array.from({length:n},(_,i)=>200+i/100),h=new Array(n).fill(0),fe=new Array(n).fill(0);
          h[25000]=100;h[123]=1e-12;fe[30000]=10;const ys=h.map((y,i)=>y+fe[i]);
          return {kind:'single',xs,ys,yi:[],series:{raw:{label:'raw',xs,ys,total_points:n},interpolated:{label:'interpolated',xs,ys,total_points:n},ions:[],
            elements:{raw:{xs,curves:[{label:'H',ys:h},{label:'Fe',ys:fe}]},interpolated:{xs,curves:[{label:'H',ys:h},{label:'Fe',ys:fe}]}}},
            meta:{source:'deterministic CSV fixture · offline test',intensity_scale:'photon',actual_resolution:3000}};""")

    def shot(self,name):
        directory=os.environ.get('SIMLIBS_WEB_SCREENSHOT_DIR')
        if directory:
            self.driver.execute_async_script("const done=arguments[0];document.querySelector('#toasts').replaceChildren();Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))).then(()=>requestAnimationFrame(()=>requestAnimationFrame(done)));")
            path=Path(directory);path.mkdir(parents=True,exist_ok=True);self.driver.save_screenshot(str(path/(name+'.png')))

    def test_full_50001_actual_canvas_nodes_colors_and_shared_normalization(self):
        self.driver.set_window_size(1366,1000)
        result=self.fixture()
        evidence=self.js("""const cv=specCanvas,ctx=cv.getContext('2d'),original=ctx.lineTo;let calls=0;
          ctx.lineTo=function(...args){calls++;return original.apply(this,args)};const start=performance.now();
          try{renderSingleResult('fixture',arguments[0]);return {calls,milliseconds:performance.now()-start,nodes:cv._plot.drawn_nodes};}finally{ctx.lineTo=original;}""",result)
        self.assertGreaterEqual(evidence['calls'],3*50000)
        self.assertEqual([row['count'] for row in evidence['nodes']],[50001]*3)
        buttons=self.driver.find_elements(By.CSS_SELECTOR,'#elementLegend button')
        self.assertEqual([b.text for b in buttons],['H','Fe'])
        colors=[self.js('return getComputedStyle(arguments[0]).borderLeftColor',b) for b in buttons]
        self.assertNotEqual(*colors)
        self.js("document.querySelector('#specChart').scrollIntoView({block:'center'})")
        self.shot('full-50001-dark')
        self.js("state.views.norm=true;drawSingle(specData,true)")
        factor=self.js('return specCanvas._plot.divisor')
        self.assertEqual(factor,100)
        buttons[-1].click()
        self.assertEqual(self.js('return specCanvas._plot.divisor'),factor)
        self.assertEqual(self.js('return specCanvas._plot.drawn_nodes.length'),2)
        self.js("document.documentElement.dataset.theme='light';state.hiddenElements.Fe=false;drawSingle(specData,true);renderElementLegend(specData,'elementLegend')")
        self.shot('full-50001-light')
        self.assertEqual([self.js('return getComputedStyle(arguments[0]).borderLeftColor',b) for b in self.driver.find_elements(By.CSS_SELECTOR,'#elementLegend button')],colors)
        if os.environ.get('SIMLIBS_WEB_SCREENSHOT_DIR'):
            (Path(os.environ['SIMLIBS_WEB_SCREENSHOT_DIR'])/'canvas-50001-check.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')

    def test_zoom_preserves_weak_original_node_tooltip_and_physical_r(self):
        self.js("renderSingleResult('fixture',arguments[0]);specCanvas._view={xmin:201.2,xmax:201.3,srcMin:200,srcMax:700};drawSingle(specData,true);specCanvas.scrollIntoView({block:'center'})",self.fixture())
        labels=self.js("const ctx=specCanvas.getContext('2d'),old=ctx.fillText,labels=[];ctx.fillText=function(text,...args){labels.push(String(text));return old.call(this,text,...args)};try{drawSingle(specData,true);return labels.filter(t=>t.startsWith('201'));}finally{ctx.fillText=old;}")
        self.assertGreater(len(set(labels)),1,'放大后的波长刻度不能全部舍入成同一整数')
        point=self.js("const r=specCanvas.getBoundingClientRect(),p=specCanvas._plot;return {x:r.left+p.pad.l+(201.23-p.xmin)/(p.xmax-p.xmin)*p.cw,y:r.top+p.pad.t+p.ch/2}")
        self.driver.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mouseMoved',**point})
        WebDriverWait(self.driver,5).until(lambda d:'1e-12' in d.find_element(By.ID,'tooltip').text)
        self.assertEqual(self.js('return specData.xs.length'),50001)
        self.assertEqual(self.js('return specData.meta.actual_resolution'),3000)
        self.assertLess(self.js('return specCanvas._plot.xs.length'),20)
        self.shot('weak-original-node-zoom')

    def test_lazy_scan_full_frames_and_cache_eviction(self):
        type(self).reply_result=self.fixture()
        self.js("switchPage('scan');renderScanResult({kind:'scan',axis:'te',job_id:'fixture',lazy_frames:true,frames:[1,2,3,4,5].map(value=>({value,loaded:false})),intensity_scale:'photon'})")
        self.driver.execute_async_script('const done=arguments[0];(async()=>{for(let i=0;i<5;i++)await scanSetFrame(i);done();})().catch(done)')
        self.assertEqual(self.js('return state.scanCache.frames.filter(f=>f.series).length'),3)
        self.assertEqual(self.js('return specCanvas._plot?.xs.length||0'),760)
        self.assertEqual(self.js("return document.querySelector('#scanChart')._plot.xs.length"),50001)
        self.assertIn('50001/50001',self.driver.find_element(By.ID,'frameInfo').text)
        self.shot('scan-complete-frame-cache')

    def test_official_js_memory_downgrade_observed_after_recalculate(self):
        html=(UI_ROOT/'.ai-workflow/20261004-mode-fidelity/official-page.html').read_text(encoding='utf-8')
        official=(UI_ROOT/'.ai-workflow/20261004-mode-fidelity/nist-saha_lte.js').read_text(encoding='utf-8')
        values=html[html.index('var composition'):html.index('function draw()')]
        self.driver.get('about:blank')
        self.js("document.body.innerHTML='<input id=resolution value=5000><span id=max_res_warning></span>';const script=document.createElement('script');script.textContent=arguments[0];document.head.appendChild(script);window.expSpectrum=null;window.memAvail=()=>1024;window.resolution=5000;",official+values)
        self.js(RECALC_OBSERVER)
        runtime=self.js('const result=lte_spectrum_js(spectra,composition,lines,levels,ips,expSpectrum,temp,eden,resolution,cmeV,koeff,lineOptions.hAxis.title,dataDopplerArray);return window.__simlibsRecalculated;')
        self.assertEqual(runtime['requested_r'],5000)
        self.assertEqual(runtime['global_r'],5000)
        self.assertGreater(runtime['effective_r'],0)
        self.assertLess(runtime['effective_r'],5000)
        self.assertNotEqual(runtime['effective_r'],1000,'不能使用重算前的初始R')
        self.assertIn('Resolution = '+str(runtime['effective_r']),runtime['title'])
        self.assertEqual(float(self.driver.find_element(By.ID,'resolution').get_attribute('value')),runtime['effective_r'])
        self.assertIn('maximum resolution',runtime['warning'])
        if os.environ.get('SIMLIBS_WEB_SCREENSHOT_DIR'):
            (Path(os.environ['SIMLIBS_WEB_SCREENSHOT_DIR'])/'official-js-memory-check.json').write_text(json.dumps(runtime,indent=2),encoding='utf-8')


if __name__=='__main__':unittest.main()
