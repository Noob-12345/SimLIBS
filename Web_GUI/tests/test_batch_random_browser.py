import os,unittest
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from tests.web_browser_support import BrowserCase
from simlibs_ui.offline_database import capabilities
from simlibs_ui.settings import Settings

@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST')=='1','isolated Chrome required')
class BatchRandomBrowserTests(BrowserCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.params_reply={'params':{'mode':'local','mode_version':2,'te':1,'ne':1e17,'resolution':1000,
          'low_w':240,'up_w':260,'max_ion_charge':2,'headless':True,'resample':False,'local_broadening_enabled':False},
          'composition':[{'el':'Fe','pct':100}],'local_capabilities':capabilities(Settings().line_database)}
    def setUp(self):
        super().setUp();WebDriverWait(self.driver,5).until(lambda d:self.js('return state.localSymbols.length===31'))
        self.driver.execute_async_script("const done=arguments[0];Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))).then(()=>requestAnimationFrame(()=>requestAnimationFrame(done)));")
    def click_switch(self,id):
        input=self.driver.find_element(By.ID,id);label=input.find_element(By.XPATH,'..');self.js("arguments[0].scrollIntoView({block:'center'})",label);label.click();return input.is_selected()
    def edit(self,id,value):
        input=self.driver.find_element(By.ID,id);self.js("arguments[0].scrollIntoView({block:'center'})",input);input.send_keys(Keys.CONTROL,'a');input.send_keys(str(value));input.send_keys(Keys.TAB)
    def invoke(self,name):self.driver.execute_async_script('const done=arguments[0];'+name+'().then(done,done);')
    def test_common_layout_modes_off_default_flux_and_controls(self):
        self.assertFalse(self.driver.find_element(By.ID,'localBroadenEnabled').is_selected())
        self.assertFalse(self.driver.find_element(By.ID,'headlessControl').is_displayed());self.assertFalse(self.driver.find_element(By.ID,'localWidths').is_displayed())
        self.driver.execute_async_script('const done=arguments[0];fetchPreview().then(done,done);')
        self.assertIsNone(self.js('return specData'));self.assertIn('待运行',self.driver.find_element(By.ID,'nodeInfo').text)
        self.assertEqual(self.driver.find_element(By.ID,'localIntensity').text,'强度尺度\nPhoton Flux')
        self.assertNotIn('左键框选放大',self.js('return document.body.innerText'));self.assertNotIn('总原子数密度占比',self.js('return document.body.innerText'));self.assertNotIn('固定处理路径',self.js('return document.body.innerText'))
        self.assertTrue(self.click_switch('localBroadenEnabled'));self.assertTrue(self.driver.find_element(By.ID,'localWidths').is_displayed());self.invoke('runSingle');self.assertTrue(type(self).received[-1][1]['params']['local_broadening_enabled'])
        self.js("switchPage('batch')")
        self.driver.execute_async_script("const done=arguments[0];Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))).then(()=>requestAnimationFrame(()=>requestAnimationFrame(done)));")
        self.assertEqual([b.text for b in self.driver.find_elements(By.CSS_SELECTOR,'#batchModeSeg button')],['离线本地','在线服务器','客户端计算'])
        self.assertFalse(self.driver.find_element(By.ID,'batchBroadenEnabled').is_selected())
        self.assertFalse(self.driver.find_element(By.ID,'batchHeadlessControl').is_displayed())
        self.assertEqual(self.driver.find_element(By.ID,'batchSumVal').text,'100% ✓')
        self.edit('batchNe','1.2345678912345e17');self.assertAlmostEqual(float(self.driver.find_element(By.ID,'batchNeSlider').get_attribute('value')),17.0915149772,places=8)
        self.js("$('#batchNeSlider').value=16.5;$('#batchNeSlider').dispatchEvent(new Event('input'))")
        self.assertAlmostEqual(float(self.driver.find_element(By.ID,'batchNe').get_attribute('value')),10**16.5,delta=100)
        self.invoke('runBatch');body=type(self).received[-1][1];self.assertEqual(body['generation']['kind'],'fixed');self.assertFalse(body['params']['local_broadening_enabled'])
    def test_batch_element_mouse_keyboard_completion_and_random_bounds_independent(self):
        self.js("switchPage('batch');state.batchComp=[{el:'Fe',pct:20},{el:'Al',pct:40},{el:'Ca',pct:40}];renderBatchComposition();$('#batchGenerationSeg [data-v=random]').click()")
        self.assertTrue(self.click_switch('randomTe'));self.edit('batchTeA','1.1');self.edit('batchTeB','1.4')
        self.assertTrue(self.click_switch('randomNe'));self.edit('batchNeA','1.234e17');self.edit('batchNeB','2e17')
        for i in (1,2):self.assertTrue(self.click_switch('randomConcentration'+str(i)));self.edit('concentrationMin'+str(i),30);self.edit('concentrationMax'+str(i),50)
        self.js("$('#teInput').value='';state.comp=[{el:'bad',pct:''}]")
        self.invoke('runBatch');body=type(self).received[-1][1];self.assertEqual(body['generation']['te']['min'],1.1);self.assertEqual(body['generation']['ne']['min'],1.234e17);self.assertEqual(body['generation']['concentrations'][0]['fixed'],20)
        self.assertFalse(self.driver.find_element(By.CSS_SELECTOR,'.batch-pct').get_attribute('disabled'))
        field=self.driver.find_elements(By.CSS_SELECTOR,'.batch-el')[2];self.js("arguments[0].scrollIntoView({block:'center'})",field);field.send_keys(Keys.CONTROL,'a');field.send_keys('f')
        # Fe is already selected, so duplicate candidates are excluded.
        self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR,'#batchOptions2 button'))
        field.send_keys(Keys.CONTROL,'a');field.send_keys('c');field.send_keys(Keys.ARROW_DOWN,Keys.ENTER);self.assertEqual(field.get_attribute('value'),'Ca')
    def test_random_off_ignores_hidden_invalid_values_template_not_overridden(self):
        self.js("switchPage('batch');$('#batchGenerationSeg [data-v=random]').click();$('#batchTeA').value='bad';$('#batchNeB').value='bad';state.batchComp[0].min='bad';")
        self.invoke('runBatch');body=type(self).received[-1][1];self.assertFalse(body['generation']['te']['enabled']);self.assertFalse(body['generation']['ne']['enabled'])
        self.assertTrue(self.click_switch('randomTe'));self.invoke('runBatch');self.assertEqual(type(self).received[-1][1],body)
        self.js("$('#batchGenerationSeg [data-v=template]').click()")
        path=Path(type(self).temp.name)/'rows.csv';path.write_text('name,Fe,Te[eV],Ne[cm^-3]\na,100,1.2,1.4e17\nb,100,1.3,1.6e17\n')
        self.driver.find_element(By.ID,'templateFile').send_keys(str(path));WebDriverWait(self.driver,5).until(lambda d:'计划2谱' in self.driver.find_element(By.ID,'templateInfo').text)
        self.invoke('runBatch');request=type(self).received[-1][1];self.assertNotIn('generation',request);self.assertIn('a,100,1.2',request['template_csv'])
    def test_sticks_are_vertical_all_nodes_tooltip_normalization_and_online_flux_kept(self):
        evidence=self.js("""const xs=[240,245,250],ys=[0,2,1],result={kind:'single',xs,ys,series:{raw:{xs,ys},interpolated:{xs,ys},ions:[],elements:{raw:{xs,curves:[{label:'Fe',ys}]},interpolated:{xs,curves:[{label:'Fe',ys}]}}},meta:{source:'fixture',spectrum_style:'sticks',local_broadening_enabled:false,intensity_scale:'photon',actual_resolution:null}};renderSingleResult('fixture',result);const ctx=specCanvas.getContext('2d'),move=ctx.moveTo,line=ctx.lineTo,segments=[];let last;ctx.moveTo=function(x,y){last=[x,y];return move.call(this,x,y)};ctx.lineTo=function(x,y){if(last)segments.push([last[0],x]);return line.call(this,x,y)};try{drawSingle(specData,true);return {segments,node:$('#nodeInfo').textContent};}finally{ctx.moveTo=move;ctx.lineTo=line;}""")
        # Axes/grid also draw horizontal lines; spectral strokes contain equal-x endpoints.
        self.assertGreaterEqual(sum(a==b for a,b in evidence['segments']),6);self.assertIn('R未应用',evidence['node'])
        self.js("$('#modeSeg [data-v=client]').click();$('#intensityScale').value='energy';$('#modeSeg [data-v=local]').click();")
        self.assertEqual(self.driver.find_element(By.ID,'localIntensity').text,'强度尺度\nPhoton Flux')
        self.js("$('#modeSeg [data-v=client]').click()");self.assertEqual(self.driver.find_element(By.ID,'intensityScale').get_attribute('value'),'energy')
        self.assertFalse(self.driver.find_element(By.ID,'headlessControl').is_displayed())
if __name__=='__main__':unittest.main()
