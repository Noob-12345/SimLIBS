import json,os
from pathlib import Path
import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from tests.web_browser_support import BrowserCase
from simlibs_ui.offline_database import capabilities
from simlibs_ui.settings import Settings,UI_ROOT

@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST')=='1','isolated Chrome required')
class LocalBrowserTests(BrowserCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params_reply={'params':{'te':1,'ne':1e17,'resolution':1000,'low_w':200,'up_w':500,'max_ion_charge':2,
                                   'mode':'local','mode_version':2,'headless':True,'resample':False},
                          'composition':[{'el':'Fe','pct':100}],'local_capabilities':capabilities(Settings().line_database)}
    def setUp(self):
        type(self).get_paths.clear();super().setUp()
        WebDriverWait(self.driver,10).until(lambda d:self.js('return state.localSymbols.length===31'))
    def edit(self,id,value):
        el=self.driver.find_element(By.ID,id);self.js("arguments[0].scrollIntoView({block:'center'})",el)
        el.send_keys(Keys.CONTROL,'a');el.send_keys(str(value));el.send_keys(Keys.TAB);return el
    def invoke(self,name):self.driver.execute_async_script('const done=arguments[0];'+name+'().then(done,done);')
    def choose(self,id,value):
        if id=='themeMode':
            self.js("$('#themeBtn').click();$('#themeMenu [data-theme-mode='+arguments[0]+']').click()",value)
        else:self.js("const el=document.getElementById(arguments[0]);el.value=arguments[1];el.dispatchEvent(new Event('change',{bubbles:true}));",id,value)
    def test_local_default_capabilities_charge_photon_brand_and_links(self):
        self.assertEqual(self.js('return state.mode'),'local')
        self.assertEqual([p for p in type(self).get_paths if p.startswith('/api/status')],['/api/status?mode=local'])
        self.assertEqual(self.js("return Array.from($('#maxIon').options).map(o=>o.value)"),['0','1','2'])
        self.assertEqual(self.js("return Array.from($('#intensityScale').options).map(o=>o.value)"),['photon','energy'])
        self.assertFalse(self.driver.find_element(By.ID,'nistIntensityControl').is_displayed())
        self.assertEqual(self.driver.find_element(By.CSS_SELECTOR,'.brand h1').text,'SimLIBS\nSPECTRUM WORKBENCH FOR SCNU')
        self.assertEqual(self.driver.find_element(By.ID,'githubLink').get_attribute('href'),'https://github.com/Noob-12345/SimLIBS')
        self.assertTrue(self.js("return $('.brand-image').complete&&$('.brand-image').naturalWidth>0"))
        self.assertFalse(self.driver.find_element(By.ID,'localCapability').is_displayed())
        el=self.driver.find_element(By.CSS_SELECTOR,'.comp-el');el.send_keys(Keys.CONTROL,'a');el.send_keys('f')
        option=next(el for el in self.driver.find_elements(By.CSS_SELECTOR,'.element-options button') if el.text=='Fe');option.click()
        self.assertEqual(el.get_attribute('value'),'Fe');self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR,'[data-preset]'))
    def test_batch_owns_mode_parameters_and_interpolation_for_all_three_modes(self):
        self.js("switchPage('batch');$('#teInput').value='';state.comp=[{el:'bad',pct:''}];state.batchComp=[{el:'Fe',pct:100}];renderBatchComposition();")
        checkbox=self.driver.find_element(By.ID,'batchResample');label=checkbox.find_element(By.XPATH,'..')
        self.js("arguments[0].scrollIntoView({block:'center'})",label)
        WebDriverWait(self.driver,3).until(lambda d:label.is_displayed() and label.is_enabled());label.click()
        self.assertTrue(checkbox.is_selected())
        WebDriverWait(self.driver,3).until(lambda d:self.driver.find_element(By.ID,'batchStep').is_displayed())
        self.edit('batchTe','1.25');self.edit('batchNe','1.234e17');self.edit('batchR','1234');self.edit('batchStep','.03')
        self.js("$('#resampleStep').value=.7;$('#batchResample').checked=true;$('#batchCount').value=2;")
        for mode in ('local','client','server'):
            self.choose('batchMode',mode);self.invoke('runBatch');payload=type(self).received[-1][1]
            self.assertEqual(payload['params']['mode'],mode);self.assertEqual(payload['params']['resample_step'],.03)
            self.assertTrue(payload['params']['resample']);self.assertEqual(payload['params']['te'],1.25);self.assertEqual(payload['params']['resolution'],1234)
            self.assertEqual(payload['generation']['concentrations'],[{'el':'Fe','enabled':False,'fixed':100}]);self.assertFalse(payload['generation']['te']['enabled'])
    def test_uploaded_template_order_repeats_ignores_composition_drafts(self):
        self.js("switchPage('batch');state.comp=[{el:'bad',pct:''}];state.batchComp=[{el:'',pct:''}];renderBatchComposition();")
        path=Path(type(self).temp.name)/'actual-template.csv';path.write_text('samples,Fe_at%,Al_at%,Te[eV],Ne[cm^-3],R\nfirst,100,0,1,1e17,1000\nsecond,50,50,1.2,2e17,2000\n',encoding='utf-8')
        self.driver.find_element(By.ID,'templateFile').send_keys(str(path))
        WebDriverWait(self.driver,5).until(lambda d:'计划2谱' in self.driver.find_element(By.ID,'templateInfo').text)
        self.edit('templateRepeat','2')
        WebDriverWait(self.driver,5).until(lambda d:'计划4谱' in self.driver.find_element(By.ID,'templateInfo').text)
        self.invoke('runBatch');payload=type(self).received[-1][1]
        self.assertEqual(payload['n_samples'],4);self.assertEqual(payload['repeats'],2);self.assertNotIn('generation',payload)
        self.assertIn('first,100,0',payload['template_csv']);self.assertIn('second,50,50',payload['template_csv'])
        self.js("$('#templateClear').click()");self.assertIsNone(self.js('return state.templateText'))
    def test_resume_sends_no_new_parameters_and_keeps_previous_spectrum(self):
        self.js("state.hasResult=true;specData={xs:[200,201],ys:[0,1],yi:[],meta:{intensity_scale:'energy'}};state.resumeJobId='old';$('#batchResume').disabled=false;$('#batchTe').value=9;")
        self.invoke('resumeBatch');self.assertEqual(type(self).received[-1],('/api/jobs/old/resume',{}))
        self.assertTrue(self.js('return state.hasResult'));self.assertEqual(self.js('return specData.meta.intensity_scale'),'energy')
    def test_theme_catalog_persistence_and_system_follow(self):
        def system(dark):self.driver.execute_cdp_cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-color-scheme','value':'dark' if dark else 'light'}]})
        system(True);self.choose('themeMode','system')
        WebDriverWait(self.driver,3).until(lambda d:self.js('return document.documentElement.dataset.theme')=='dark')
        system(False);WebDriverWait(self.driver,3).until(lambda d:self.js('return document.documentElement.dataset.theme')=='light')
        self.choose('themeMode','dark');system(False)
        self.assertEqual(self.js('return document.documentElement.dataset.theme'),'dark')
        self.driver.find_element(By.ID,'themeCatalogBtn').click()
        for key,color in [('violet','#a78bfa'),('ocean','#60a5fa'),('forest','#34d399'),('amber','#fb923c'),('rose','#f472b6')]:
            self.driver.find_element(By.CSS_SELECTOR,'[data-preset-theme='+key+']').click();self.assertEqual(self.js("return cssVar('--accent')"),color)
            self.assertEqual(self.js("return cssVar('--chart-main')"),color)
        self.assertEqual(self.js("return document.querySelectorAll('#accentCustom,#accentPalette,#themeMode').length"),0)
        self.driver.refresh();WebDriverWait(self.driver,5).until(lambda d:self.js("return cssVar('--accent')")=='#f472b6')
        self.assertEqual(self.js('return document.documentElement.dataset.theme'),'dark')
        self.assertEqual(json.loads(self.js("return localStorage.getItem('simlibs-theme')")),{'mode':'dark','preset':'rose'})
        self.choose('themeMode','system');system(False)
        WebDriverWait(self.driver,3).until(lambda d:self.js('return document.documentElement.dataset.theme')=='light')
