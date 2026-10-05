"""六项需求的实际键盘/鼠标交互；使用已有隔离 Chrome 和本地假传输。"""
import os
from pathlib import Path
import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from tests.web_browser_support import BrowserCase


@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST')=='1', '隔离 Chrome 回归须显式启用')
class WebTrainingBrowserTests(BrowserCase):
    def edit(self, selector, text):
        element=self.driver.find_element(By.CSS_SELECTOR,selector)
        self.js("arguments[0].scrollIntoView({block:'center'})",element)
        element.send_keys(Keys.CONTROL,'a');element.send_keys(text)
        return element

    def shot(self, name):
        directory=os.environ.get('SIMLIBS_WEB_SCREENSHOT_DIR')
        if directory:
            self.driver.execute_async_script("""const done=arguments[0];
              document.querySelector('#toasts').replaceChildren();
              Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))
                .then(()=>requestAnimationFrame(()=>requestAnimationFrame(done)));""")
            target=Path(directory);target.mkdir(parents=True,exist_ok=True)
            self.driver.save_screenshot(str(target/(name+'.png')))

    def invoke(self, function):
        self.driver.execute_async_script('const done=arguments[0];'+function+'().then(done,done);')

    def test_f_candidates_mouse_keyboard_escape_and_drafts(self):
        self.js("state.comp=[{el:'H',pct:100}];renderComp();")
        field=self.edit('.comp-el','f')
        options=self.driver.find_elements(By.CSS_SELECTOR,'.element-options button')
        self.assertIn('Fe',[o.text for o in options])
        self.assertEqual(field.get_attribute('aria-expanded'),'true')
        self.shot('element-completion-dark')
        next(o for o in options if o.text=='Fe').click()
        self.assertEqual(field.get_attribute('value'),'Fe')
        self.assertEqual(self.js('return state.comp[0].el'),'Fe')
        field=self.edit('.comp-el','f')
        field.send_keys(Keys.ARROW_DOWN,Keys.ARROW_DOWN,Keys.ENTER)
        self.assertEqual(field.get_attribute('value'),'Fe')
        field=self.edit('.comp-el','f');field.send_keys(Keys.ESCAPE)
        self.assertEqual(field.get_attribute('aria-expanded'),'false')
        self.js("state.comp=[{el:'H',pct:80},{el:'Fe',pct:20}];renderComp();")
        field=self.edit('.comp-el','f')
        self.assertNotIn('Fe',[o.text for o in self.driver.find_elements(By.CSS_SELECTOR,'#element-options-0 button')])
        self.js("state.comp=[{el:'H',pct:80},{el:'He',pct:20}];renderComp();")
        percent=self.driver.find_elements(By.CSS_SELECTOR,'.comp-pct')[0]
        percent.send_keys(Keys.CONTROL,'a',Keys.BACKSPACE)
        field=self.edit('.comp-el','f')
        self.driver.find_element(By.CSS_SELECTOR,'#element-options-0 button[id$="-1"]').click()
        self.assertEqual(field.get_attribute('value'),'Fe')
        self.assertEqual(percent.get_attribute('value'),'','选择元素不能清掉数字草稿')

    def test_numeric_inputs_preserve_exact_values_slider_sync_and_manual_composition(self):
        for selector,value in [('#teInput','1.137'),('#neInput','1.23e17'),('#rInput','1234')]:self.edit(selector,value)
        self.assertAlmostEqual(float(self.driver.find_element(By.ID,'teSlider').get_attribute('value')),1.137)
        self.assertAlmostEqual(float(self.driver.find_element(By.ID,'neSlider').get_attribute('value')),17.089905111439398)
        self.assertEqual(self.driver.find_element(By.ID,'rSlider').get_attribute('value'),'1234')
        self.invoke('runSingle')
        payload=type(self).received[-1][1]['params']
        self.assertEqual([payload['te'],payload['ne'],payload['resolution']],[1.137,1.23e17,1234])
        for selector,value in [('#teInput','4.137'),('#neInput','1.23e20'),('#rInput','123456')]:self.edit(selector,value)
        self.invoke('runSingle')
        payload=type(self).received[-1][1]['params']
        self.assertEqual([payload['te'],payload['ne'],payload['resolution']],[4.137,1.23e20,123456])
        self.js("for(const [id,value] of [['teSlider','1.5'],['neSlider','16.5'],['rSlider','4321']]){const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('input'));}")
        self.assertEqual(self.driver.find_element(By.ID,'teInput').get_attribute('value'),'1.5')
        self.assertAlmostEqual(float(self.driver.find_element(By.ID,'neInput').get_attribute('value')),10**16.5,delta=100)
        self.assertEqual(self.driver.find_element(By.ID,'rInput').get_attribute('value'),'4321')
        self.js("state.comp=[{el:'',pct:100}];renderComp();")
        self.edit('.comp-el','H').send_keys(Keys.TAB)
        for selector,value in [('#teInput','1'),('#neInput','1e17'),('#rInput','1000')]:self.edit(selector,value).send_keys(Keys.TAB)
        self.assertEqual(self.js('return [currentParams().te,currentParams().ne,currentParams().R]'),[1,1e17,1000])
        self.assertEqual(self.driver.find_element(By.ID,'neInput').get_attribute('value'),'1e17')

    def test_invalid_parameter_drafts_block_all_three_paths(self):
        for selector,value in [('#teInput',''),('#teInput','0'),('#teInput','-1'),('#teInput','NaN'),('#neInput','Infinity'),('#neInput',''),('#rInput','1.2'),('#rInput','0')]:
            with self.subTest(selector=selector,value=value):
                self.js('setParameterValues(1,1e17,1000)')
                self.edit(selector,value or Keys.BACKSPACE)
                type(self).received.clear()
                for function in ('runSingle','runScan'):self.invoke(function)
                self.assertFalse(type(self).received,'单次无效参数不得启动单次/扫描')
                self.invoke('runBatch')
                self.assertEqual(type(self).received[-1][0],'/api/simulate/batch','批量独立参数不受单次草稿污染')
                self.assertEqual(self.driver.find_element(By.CSS_SELECTOR,selector).get_attribute('aria-invalid'),'true')

    def test_batch_equal_ranges_pack_estimate_payload_and_old_tasks(self):
        self.js("switchPage('batch')")
        for id,value in [('batchCount','5'),('batchSize','2'),('batchTeA','1'),('batchTeB','1'),('batchNeA','17'),('batchNeB','17')]:
            self.edit('#'+id,value)
        self.assertIn('3 包',self.driver.find_element(By.ID,'batchPackageEstimate').text)
        self.assertIn('末包 1',self.driver.find_element(By.ID,'batchPackageEstimate').text)
        self.invoke('runBatch')
        payload=type(self).received[-1][1]
        self.assertEqual([payload['n_samples'],payload['batch_size']],[5,2])
        self.assertEqual(payload['te_range'],[1,1]);self.assertEqual(payload['ne_range'],[17,17])
        self.js("state.mode='client';updateModePath();document.querySelector('#resample').checked=false;")
        self.invoke('runBatch');self.assertFalse(type(self).received[-1][1]['params']['resample'])
        for id,value in [('batchCount','1.2'),('batchCount',''),('batchSize','0'),('batchSize','2.2'),('batchSize','5001')]:
            self.js("document.querySelector('#batchCount').value=5;document.querySelector('#batchSize').value=2")
            self.edit('#'+id,value or Keys.BACKSPACE);type(self).received.clear();self.invoke('runBatch')
            self.assertFalse(type(self).received)
        self.assertEqual(self.js("return KIND_PAGE['批量 dataset']"),'batch')
        self.js("renderBatchResult('old',{summary:{total:2,completed:2},samples:[],wide:{}})")
        self.assertFalse(self.driver.find_element(By.ID,'trainingDownload').is_enabled())
        self.assertIn('没有训练包',self.driver.find_element(By.ID,'trainingPackageNote').text)
        self.js("renderBatchResult('new',{summary:{total:5,completed:5},samples:[],wide:{},training_package:{available:true,packages:3,batch_size:2,source:'offline fixture'}})")
        self.assertTrue(self.driver.find_element(By.ID,'trainingDownload').is_enabled())
        self.assertEqual(self.js('return state.batchResultId'),'new')

    def test_labels_modes_theme_and_screenshots(self):
        self.assertEqual([b.text for b in self.driver.find_elements(By.CSS_SELECTOR,'#modeSeg button')],['离线本地','在线服务器','客户端计算'])
        for mode in ('server','client'):
            self.js("document.querySelector('#modeSeg button[data-v='+arguments[0]+']').click()",mode)
            self.invoke('runSingle');self.assertEqual(type(self).received[-1][1]['params']['mode'],mode)
        for theme in ('dark','light'):
            self.js("document.documentElement.dataset.theme=arguments[0];setParameterValues(1.137,1.23e17,1234)",theme)
            self.js("document.querySelector('#teInput').scrollIntoView({block:'center'})")
            self.shot('parameters-'+theme)
            self.js("switchPage('batch');document.querySelector('#trainingDownload').scrollIntoView({block:'center'})")
            self.driver.set_window_size(1366,1000)
            self.assertEqual(self.driver.find_element(By.ID,'pageTitle').text,'批量模拟')
            self.shot('batch-'+theme)
            self.js("switchPage('single')")
        self.driver.set_window_size(1024,768)
        self.js("switchPage('batch');document.querySelector('#trainingDownload').scrollIntoView({block:'center'})")
        self.shot('batch-1024-light')

    def test_reference_28_elements_can_be_configured_up_to_32_rows(self):
        self.js("state.comp=ELEMENT_SYMBOLS.slice(0,8).map((el,i)=>({el,pct:i===0?100:0}));renderComp();document.querySelector('#addEl').click()")
        self.assertEqual(self.js('return state.comp.length'),9)
        self.js("state.comp=ELEMENT_SYMBOLS.slice(0,28).map((el,i)=>({el,pct:i===0?100:0}));renderComp()")
        self.assertEqual(self.js('return compositionPayload().length'),28)
        self.js("state.comp=ELEMENT_SYMBOLS.slice(0,32).map((el,i)=>({el,pct:i===0?100:0}));renderComp();document.querySelector('#addEl').click()")
        self.assertEqual(self.js('return state.comp.length'),32)
        self.assertIn('最多 32',self.js("return document.querySelector('#toasts').textContent"))


if __name__=='__main__':unittest.main()
