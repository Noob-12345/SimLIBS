import os,json
from pathlib import Path
import unittest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from tests.web_browser_support import BrowserCase
from simlibs_ui.offline_database import capabilities
from simlibs_ui.settings import Settings

@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST')=='1','isolated Chrome required')
class ThemeCatalogBrowserTests(BrowserCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params_reply={'params':{'te':1,'ne':1e17,'resolution':1000,'low_w':240,'up_w':260,'max_ion_charge':2,
             'mode':'local','mode_version':2,'headless':True,'resample':False},'composition':[{'el':'Fe','pct':100}],
             'local_capabilities':capabilities(Settings().line_database)}
    def test_svg_link_full_page_thumbnails_and_removed_controls(self):
        link=self.driver.find_element(By.ID,'githubLink');self.assertEqual(link.text,'')
        self.assertTrue(link.find_elements(By.CSS_SELECTOR,'svg path'));self.assertEqual(link.get_attribute('target'),'_blank')
        self.assertEqual(link.get_attribute('href'),'https://github.com/Noob-12345/SimLIBS')
        for attr in ('aria-label','title','rel'):self.assertTrue(link.get_attribute(attr))
        self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR,'#themeMode,#accentPalette,#accentCustom'))
        self.driver.find_element(By.ID,'themeCatalogBtn').click()
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR,'.theme-card')),5)
        for card in self.driver.find_elements(By.CSS_SELECTOR,'.theme-card'):
            self.assertEqual(len(card.find_elements(By.CSS_SELECTOR,'.theme-preview')),2)
            for selector in ('.mini-sidebar','.mini-heading','.mini-cards','.mini-chart svg'):
                self.assertEqual(len(card.find_elements(By.CSS_SELECTOR,selector)),2)
            backgrounds=[self.js('return getComputedStyle(arguments[0]).backgroundColor',preview) for preview in card.find_elements(By.CSS_SELECTOR,'.theme-preview')]
            self.assertNotEqual(*backgrounds)
    def test_keyboard_menus_escape_outside_click_selection_and_persistence(self):
        trigger=self.driver.find_element(By.ID,'themeCatalogBtn');trigger.send_keys(Keys.ENTER)
        self.driver.switch_to.active_element.send_keys(Keys.ARROW_RIGHT,Keys.SPACE)
        self.assertEqual(self.js('return themePreference.preset'),'ocean')
        self.assertEqual(self.js("return $('.theme-card[aria-pressed=true]').dataset.presetTheme"),'ocean')
        self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
        self.assertEqual(self.driver.switch_to.active_element.get_attribute('id'),'themeCatalogBtn')
        self.assertFalse(self.driver.find_element(By.ID,'themeCatalog').is_displayed())
        mode=self.driver.find_element(By.ID,'themeBtn');mode.send_keys(Keys.ENTER)
        self.driver.switch_to.active_element.send_keys(Keys.HOME,Keys.ENTER)
        self.assertEqual(self.js('return themePreference.mode'),'light')
        self.driver.execute_cdp_cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-color-scheme','value':'dark'}]})
        self.assertEqual(self.js('return document.documentElement.dataset.theme'),'light')
        mode.click();self.driver.switch_to.active_element.send_keys(Keys.END,Keys.ENTER)
        WebDriverWait(self.driver,3).until(lambda d:self.js('return document.documentElement.dataset.theme')=='dark')
        self.assertTrue(self.driver.find_element(By.ID,'iconSystem').is_displayed());self.assertIn('当前夜间',mode.get_attribute('title'))
        mode.click();self.driver.find_element(By.ID,'pageTitle').click()
        self.assertEqual(mode.get_attribute('aria-expanded'),'false')
        self.driver.refresh();WebDriverWait(self.driver,5).until(lambda d:self.js('return themePreference.preset')=='ocean')
        self.assertEqual(json.loads(self.js("return localStorage.getItem('simlibs-theme')")),{'mode':'system','preset':'ocean'})
    def test_empty_local_capability_never_expands_periodic_table_and_zero_is_allowed(self):
        self.js("state.localSymbols=[];state.localCapabilities={error:'目录不存在'};state.comp=[{el:'Fe',pct:100}];renderComp();renderBatchComposition();")
        field=self.driver.find_element(By.CSS_SELECTOR,'.comp-el');field.send_keys(Keys.CONTROL,'a');field.send_keys('f')
        self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR,'.element-options button'))
        self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR,'#batchElementOptions option'))
        self.js("state.comp=[{el:'Fe',pct:100}];renderComp();")
        type(self).received.clear()
        for function in ('runSingle','runBatch','runScan'):
            self.driver.execute_async_script('const done=arguments[0];'+function+'().then(done,done);')
        self.assertFalse(type(self).received)
        payload=self.js("state.localSymbols=['Fe'];return compositionPayload([{el:'Fe',pct:100},{el:'H',pct:0}],'local')")
        self.assertEqual(payload,[{'el':'Fe','pct':100},{'el':'H','pct':0}])
