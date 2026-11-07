import os,unittest
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from tests.web_browser_support import BrowserCase
from simlibs_ui.settings import Settings
from simlibs_ui.offline_database import capabilities

@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST')=='1','isolated Chrome required')
class PolishBrowserTests(BrowserCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params_reply={'params':{'mode':'local','mode_version':2,'te':1,'ne':1e17,'resolution':1000,'low_w':240,'up_w':260,
                 'max_ion_charge':2,'headless':True,'resample':False,'local_temperature_mode':'linked'},'composition':[{'el':'Fe','pct':100}],
                 'local_capabilities':capabilities(Settings().line_database)}
    def invoke(self,name):self.driver.execute_async_script('const done=arguments[0];'+name+'().then(done,done);')
    def setUp(self):
        super().setUp()
        WebDriverWait(self.driver,10).until(lambda d:self.js('return state.localSymbols.length===31 && state.mode==="local"'))
        self.driver.execute_async_script("const done=arguments[0];Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))).then(()=>requestAnimationFrame(()=>requestAnimationFrame(done)));")
    def change(self,id,value):self.js("const el=$('#'+arguments[0]);el.value=arguments[1];el.dispatchEvent(new Event('change',{bubbles:true}));",id,value)
    def mode(self,mode):self.js("$('#modeSeg [data-v='+arguments[0]+']').click()",mode)
    def test_quiet_local_balance_no_presets_background_label_and_linked_input(self):
        self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR,'[data-preset],.presets'))
        self.assertEqual(self.driver.find_element(By.ID,'sumRow').text,'100% ✓')
        self.assertFalse(self.driver.find_element(By.ID,'localCapability').is_displayed())
        self.assertFalse(self.driver.find_element(By.ID,'nistIntensityControl').is_displayed())
        self.assertNotIn('headless',self.js('return document.body.innerText'))
        self.assertNotIn('62 CSV',self.js('return document.body.innerText'))
        self.assertEqual(self.driver.find_element(By.ID,'localTemperatureMode').get_attribute('value'),'linked')
        self.assertFalse(self.driver.find_element(By.ID,'localTemperatureInput').is_displayed())
        switch=self.driver.find_element(By.ID,'localBroadenEnabled').find_element(By.XPATH,'..');self.js("arguments[0].scrollIntoView({block:'center'})",switch);switch.click()
        input=self.driver.find_element(By.ID,'teInput');input.send_keys(Keys.CONTROL,'a');input.send_keys('2');input.send_keys(Keys.TAB)
        self.assertIn('2.3209e+4',self.driver.find_element(By.ID,'localLinkedTemperature').text)
        self.invoke('runSingle');body=type(self).received[-1][1]['params']
        self.assertEqual(body['local_temperature_mode'],'linked');self.assertEqual(body['local_temperature_K'],0)
        self.change('localTemperatureMode','manual')
        temperature=self.driver.find_element(By.ID,'localTemperature');self.js("arguments[0].scrollIntoView({block:'center'})",temperature)
        temperature.send_keys(Keys.CONTROL,'a');temperature.send_keys('8000');self.invoke('runSingle')
        self.assertEqual(type(self).received[-1][1]['params']['local_temperature_K'],8000)
    def test_online_two_fluxes_client_not_user_library_and_old_result_kept(self):
        self.js("state.localSymbols=[];state.localCapabilities={ready:false,error:'用户库不存在'};")
        for mode in ('server','client'):
            self.mode(mode);self.assertFalse(self.driver.find_element(By.ID,'localCapability').is_displayed())
            self.assertTrue(self.driver.find_element(By.ID,'nistIntensityControl').is_displayed())
            self.assertEqual([el.text for el in self.driver.find_elements(By.CSS_SELECTOR,'#intensityScale option')],['Photon flux','Energy flux'])
            self.change('intensityScale','energy');self.invoke('runSingle')
            body=type(self).received[-1][1]['params'];self.assertEqual(body['mode'],mode);self.assertEqual(body['intensity_scale'],'energy')
            self.assertIn('NIST',self.driver.find_element(By.ID,'modePath').text)
        self.js("state.hasResult=true;specData={xs:[240,250],ys:[1,2],yi:[],meta:{source:'old',intensity_scale:'energy'}};")
        self.change('intensityScale','photon');self.assertEqual(self.js('return specData.meta.intensity_scale'),'energy')
    def test_unchecked_interpolation_does_not_read_hidden_invalid_drafts_all_modes(self):
        for mode in ('server','client','local'):
            self.mode(mode);self.js("$('#resampleStep').value='';$('#resample').checked=false;$('#resample').dispatchEvent(new Event('change'))")
            self.assertFalse(self.driver.find_element(By.ID,'resampleStep').is_displayed());self.invoke('runSingle')
            self.assertFalse(type(self).received[-1][1]['params']['resample'])
            self.js("$('#resample').checked=true;$('#resample').dispatchEvent(new Event('change'))")
            self.assertTrue(self.driver.find_element(By.ID,'resampleStep').is_displayed());before=len(type(self).received);self.invoke('runSingle')
            self.assertEqual(len(type(self).received),before)
        self.js("switchPage('batch');$('#batchStep').value='';$('#batchResample').checked=false;$('#batchResample').dispatchEvent(new Event('change'))")
        for mode in ('client','local'):
            self.change('batchMode',mode);self.assertFalse(self.driver.find_element(By.ID,'batchStep').is_displayed());self.invoke('runBatch')
            self.assertFalse(type(self).received[-1][1]['params']['resample'])
        self.change('batchMode','server');self.change('batchIntensityScale','energy')
        self.js("$('#batchResample').checked=true;$('#batchResample').dispatchEvent(new Event('change'));$('#batchStep').value=.03")
        self.invoke('runBatch');self.assertEqual(type(self).received[-1][1]['params']['resample_step'],.03)
        self.assertEqual(type(self).received[-1][1]['params']['intensity_scale'],'energy')
    def test_real_file_upload_long_name_stays_inside_card_and_clear(self):
        path=Path(type(self).temp.name)/('complete-composition-template-'+'long-'*24+'.csv')
        path.write_text('name,Fe,Te[eV]\na,100,1.1\nb,100,1.2\n',encoding='utf-8')
        self.js("switchPage('batch')");self.driver.find_element(By.ID,'templateFile').send_keys(str(path))
        WebDriverWait(self.driver,5).until(lambda d:'计划2谱' in self.driver.find_element(By.ID,'templateInfo').text)
        for width in (1366,1024,800):
            self.driver.set_window_size(width,900)
            geometry=self.js("const p=$('#templateChoose').closest('.card').getBoundingClientRect();return ['templateChoose','templateFileName','templateExample'].map(id=>{const r=$('#'+id).getBoundingClientRect();return [r.left,r.right,p.left,p.right];})")
            for left,right,parent_left,parent_right in geometry:self.assertGreaterEqual(left,parent_left);self.assertLessEqual(right,parent_right)
        self.assertEqual(self.driver.find_element(By.ID,'templateFileName').get_attribute('title'),path.name)
        self.js("$('#templateClear').click()");self.assertEqual(self.driver.find_element(By.ID,'templateFileName').text,'未选择文件')
    def test_invalid_balance_error_specific_red_and_recovers(self):
        element=self.driver.find_element(By.CSS_SELECTOR,'.comp-el');element.send_keys(Keys.CONTROL,'a');element.send_keys('Xx');element.send_keys(Keys.TAB)
        self.assertIn('无效',self.driver.find_element(By.ID,'sumVal').text)
        self.assertIn('bad',self.driver.find_element(By.ID,'sumRow').get_attribute('class'))
        element.send_keys(Keys.CONTROL,'a');element.send_keys('fe');element.send_keys(Keys.TAB)
        self.assertEqual(self.driver.find_element(By.ID,'sumRow').text,'100% ✓')
