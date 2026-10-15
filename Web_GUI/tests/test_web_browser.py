import os
import unittest
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from tests.web_browser_support import BrowserCase


@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST')=='1','独立隔离 Chrome 回归须显式启用；普通 unittest 不联网')
class WebBrowserTests(BrowserCase):
    def test_raw_points_use_their_actual_sequence(self):
        result=self.js("""
          const c=document.querySelector('#specChart'),ctx=c.getContext('2d'),old=ctx.arc,arcs=[];
          ctx.arc=function(x,y,...args){arcs.push([x,y]);return old.call(this,x,y,...args)};
          try {drawSpectrum(c,{xs:[651,652,653,660],ys:[10,0,5,0],yi:[],series:{
            interpolated:{xs:[651,652,653,660],ys:[10,0,5,0]},raw:{xs:[650,656,662],ys:[3,2,1]},ions:[]}},
            {views:{raw:true,interp:false,ion:false}});return arcs;}
          finally{ctx.arc=old;}
        """)
        self.assertEqual(len(result),3,'不能把插值点复制成raw')

    def test_home_scroll_and_buttons_at_four_viewports(self):
        for width,height in [(1366,768),(1280,720),(1024,768),(1920,1080)]:
            with self.subTest(size=(width,height)):
                self.driver.set_window_size(width,height)
                self.driver.execute_async_script("const done=arguments[0];requestAnimationFrame(()=>requestAnimationFrame(done));")
                self.js("document.querySelector('#content').scrollTop=0")
                geometry=self.js("""const c=document.querySelector('#content');return {
                  inner:[innerWidth,innerHeight],bottom:document.querySelector('#main').getBoundingClientRect().bottom,
                  width:document.documentElement.scrollWidth,client:c.clientHeight,scroll:c.scrollHeight};""")
                self.assertLessEqual(geometry['bottom'],geometry['inner'][1]+1,'主页不得被视口裁切')
                self.assertLessEqual(geometry['width'],geometry['inner'][0]+2,'不得横向大幅溢出')
                if geometry['scroll']>geometry['client']:
                    center=self.js("const r=document.querySelector('#content').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}")
                    self.driver.execute_cdp_cmd('Input.dispatchMouseEvent',dict(type='mouseWheel',x=center['x'],y=center['y'],deltaX=0,deltaY=5000))
                    WebDriverWait(self.driver,3).until(lambda d:d.execute_script("return document.querySelector('#content').scrollTop>0"))
                for selector in ['#runBtn','#logbox']:
                    self.js("document.querySelector(arguments[0]).scrollIntoView({block:'center'})",selector)
                    rect=self.js("const r=document.querySelector(arguments[0]).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right}",selector)
                    self.assertGreaterEqual(rect['top'],54)
                    self.assertLessEqual(rect['bottom'],geometry['inner'][1]+1)
                    self.assertLessEqual(rect['right'],geometry['inner'][0]+1)

    def test_element_case_normalized_and_submitted(self):
        for spelling in ('Fe','FE','fe'):
            with self.subTest(spelling=spelling):
                element=self.driver.find_elements(By.CSS_SELECTOR,'.comp-el')[1]
                self.js("arguments[0].scrollIntoView({block:'center'})",element)
                element.send_keys(Keys.CONTROL,'a');element.send_keys(spelling);element.send_keys(Keys.TAB)
                self.assertEqual(element.get_attribute('value'),'Fe')
                self.assertEqual(self.js('return getComputedStyle(arguments[0]).textTransform',element),'none')
                before=len(type(self).received)
                self.js("document.querySelector('#runBtn').click()")
                WebDriverWait(self.driver,3).until(lambda _:len(type(self).received)>before)
                self.assertEqual(type(self).received[-1][1]['composition'][1]['el'],'Fe')

    def test_invalid_and_duplicate_elements_block_request(self):
        for spelling in ('Xx','W'):
            with self.subTest(spelling=spelling):
                element=self.driver.find_elements(By.CSS_SELECTOR,'.comp-el')[1]
                element.send_keys(Keys.CONTROL,'a');element.send_keys(spelling);element.send_keys(Keys.TAB)
                type(self).received.clear()
                self.driver.execute_async_script("const done=arguments[0];runSingle().then(done,done);")
                self.assertFalse(type(self).received,'无效/重复符号不能发请求')

    def test_last_element_balance_and_overflow_keeps_other_entries(self):
        self.js("state.comp=[{el:'W',pct:80},{el:'Fe',pct:19},{el:'Mo',pct:1}];renderComp();")
        inputs=self.driver.find_elements(By.CSS_SELECTOR,'.comp-pct')
        last=inputs[-1]
        last.send_keys(Keys.CONTROL,'a');last.send_keys('2');last.send_keys(Keys.TAB)
        self.assertEqual(self.js('return state.comp.map(c=>Number(c.pct))'),[80,19,1])
        self.assertEqual(last.get_attribute('value'),'1')
        self.assertIn('超额',self.js("return document.querySelector('#toasts').textContent+document.querySelector('#sumVal').textContent"))
        first=inputs[0]
        first.send_keys(Keys.CONTROL,'a');first.send_keys('60');first.send_keys(Keys.TAB)
        self.assertEqual(self.js('return state.comp.map(c=>Number(c.pct))'),[60,19,21])
        first.send_keys(Keys.CONTROL,'a');first.send_keys('95');first.send_keys(Keys.TAB)
        self.assertEqual(self.js('return state.comp.map(c=>Number(c.pct))'),[81,19,0])
        self.assertTrue(self.js("return document.querySelectorAll('.comp-pct')[0]===arguments[0]",first),'输入时不得重建DOM')

    def test_invalid_ratio_draft_blocks_request_and_recovers(self):
        first=self.driver.find_elements(By.CSS_SELECTOR,'.comp-pct')[0]
        for draft in ('','-1','1e999'):
            with self.subTest(draft=draft):
                first.send_keys(Keys.CONTROL,'a');first.send_keys(Keys.BACKSPACE)
                if draft:first.send_keys(draft)
                type(self).received.clear()
                self.driver.execute_async_script('const done=arguments[0];runSingle().then(done,done);')
                self.assertFalse(type(self).received)
                self.assertTrue(self.js("return document.querySelectorAll('.comp-pct')[0]===arguments[0]",first))
        first.send_keys(Keys.CONTROL,'a');first.send_keys('50');first.send_keys(Keys.TAB)
        self.assertAlmostEqual(self.js('return compSum()'),100)
        self.assertTrue(self.js('return updateSum()'))
        self.js("state.comp=[{el:'W',pct:80},{el:'Fe',pct:20},{el:'Mo',pct:0}];renderComp();")
        last=self.driver.find_elements(By.CSS_SELECTOR,'.comp-pct')[-1]
        last.send_keys(Keys.CONTROL,'a');last.send_keys(Keys.BACKSPACE)
        type(self).received.clear()
        self.driver.execute_async_script('const done=arguments[0];runSingle().then(done,done);')
        self.assertFalse(type(self).received,'空余额草稿不能被吞成合法0%')

    def test_add_delete_single_and_decimal_balance(self):
        self.js("state.comp=[{el:'H',pct:99}];renderComp();")
        self.assertEqual(self.js('return state.comp[0].pct'),100)
        self.js("document.querySelector('#addEl').click()")
        self.assertEqual(self.js('return state.comp.map(c=>Number(c.pct))'),[100,0])
        self.js("document.querySelectorAll('.comp-del')[0].click()")
        self.assertEqual(self.js('return state.comp[0].pct'),100)
        self.js("state.comp=[{el:'W',pct:33.3333333},{el:'Fe',pct:33.3333333},{el:'Mo',pct:1}];renderComp();")
        self.assertAlmostEqual(self.js('return compSum()'),100,delta=1e-6)
        self.assertAlmostEqual(self.js('return state.comp[2].pct'),33.3333334,delta=1e-6)

    def test_flux_selection_payload_and_previous_result_label_preserved(self):
        selector=self.driver.find_elements(By.CSS_SELECTOR,'#intensityScale')
        self.assertTrue(selector,'强度尺度选择器尚未实现')
        self.assertEqual(selector[0].get_attribute('value'),'photon')
        result={'kind':'single','xs':[650,655,660],'ys':[0,2,0],'yi':[],
                'series':{'interpolated':{'xs':[650,655,660],'ys':[0,2,0]},'raw':{'xs':[650,655,660],'ys':[0,2,0]},'ions':[]},
                'meta':{'intensity_scale':'energy','source':'legacy offline transport fixture'}}
        self.js("renderSingleResult('previous',arguments[0]);",result)
        self.assertEqual(self.js("return Array.from(document.querySelector('#intensityScale').options).map(o=>o.value)"),['photon','energy'])
        self.assertEqual(self.js('return specData.meta.intensity_scale'),'energy')
        self.assertIn('Energy',self.js('return intensityLabel(specData,false)'))
        type(self).received.clear()
        self.driver.execute_async_script('const done=arguments[0];runSingle().then(done,done);')
        self.assertEqual(type(self).received[-1][1]['params']['intensity_scale'],'photon')
        self.assertEqual(self.js('return specData.meta.intensity_scale'),'energy','失败不能改旧尺度标签')

    def test_sse_completed_failed_cancelled_keep_authoritative_scale(self):
        result={'kind':'single','xs':[650,655,660],'ys':[0,2,0],'yi':[],
                'series':{'interpolated':{'xs':[650,655,660],'ys':[0,2,0]},'ions':[]},
                'meta':{'intensity_scale':'energy','source':'offline transport fixture'}}
        type(self).reply_status='completed';type(self).reply_result=result
        self.js("document.querySelector('#runBtn').click()")
        WebDriverWait(self.driver,5).until(lambda d:d.execute_script('return state.hasResult && state.currentJob===null'))
        self.assertEqual(self.js('return specData.meta.intensity_scale'),'energy')
        for status in ('failed','cancelled'):
            type(self).reply_status=status
            self.driver.execute_async_script('const done=arguments[0];runSingle().then(done,done);')
            WebDriverWait(self.driver,5).until(lambda d:d.execute_script('return state.currentJob===null'))
            self.assertEqual(self.js('return specData.meta.intensity_scale'),'energy')

    def test_three_mouse_buttons_theme_and_hidpi_preserved(self):
        self.js("""const xs=Array.from({length:101},(_,i)=>650+i/10),ys=xs.map((x,i)=>i===50?10:1);
          renderSingleResult('fixture',{xs,ys,yi:[],series:{interpolated:{xs,ys},raw:{xs,ys},ions:[]},meta:{intensity_scale:'photon'}});
          drawSingle(specData,true);document.querySelector('#specChart').scrollIntoView({block:'center'});""")
        rect=self.js("const r=specCanvas.getBoundingClientRect(),p=specCanvas._plot;return {x:r.x+p.pad.l,y:r.y+p.pad.t+p.ch/2,w:p.cw}")
        def mouse(kind,x,button='left',buttons=1):
            args={'type':kind,'x':x,'y':rect['y'],'button':button,'buttons':buttons}
            if kind!='mouseMoved':args['clickCount']=1
            self.driver.execute_cdp_cmd('Input.dispatchMouseEvent',args)
        mouse('mousePressed',rect['x']+rect['w']*.25)
        mouse('mouseMoved',rect['x']+rect['w']*.75)
        mouse('mouseReleased',rect['x']+rect['w']*.75,buttons=0)
        before=self.js('return specCanvas._view')
        self.assertIsNotNone(before)
        self.assertLess(before['xmax']-before['xmin'],10)
        mouse('mousePressed',rect['x']+rect['w']*.5,'middle',4)
        mouse('mouseMoved',rect['x']+rect['w']*.6,'middle',4)
        mouse('mouseReleased',rect['x']+rect['w']*.6,'middle',0)
        self.assertNotEqual(self.js('return specCanvas._view.xmin'),before['xmin'])
        mouse('mousePressed',rect['x']+rect['w']*.5,'right',2)
        mouse('mouseReleased',rect['x']+rect['w']*.5,'right',0)
        self.assertIsNone(self.js('return specCanvas._view'))
        self.js("document.querySelector('#themeBtn').click()")
        self.driver.find_element(By.CSS_SELECTOR,'[data-theme-mode=light]').click()
        self.assertEqual(self.js('return document.documentElement.dataset.theme'),'light')
        self.assertEqual(self.js('return specData.meta.intensity_scale'),'photon')
        self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',{'width':1366,'height':768,'deviceScaleFactor':2,'mobile':False})
        try:
            self.js('drawSingle(specData,true)')
            self.assertAlmostEqual(self.js('return specCanvas.width/specCanvas.getBoundingClientRect().width'),2,delta=.02)
        finally:self.driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride',{})


if __name__=='__main__':unittest.main()
