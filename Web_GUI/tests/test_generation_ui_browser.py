"""Generation subpanels and real input interactions; isolated local test transport only."""
import os
import unittest
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from tests.web_browser_support import BrowserCase
from simlibs_ui.offline_database import capabilities
from simlibs_ui.settings import Settings


@unittest.skipUnless(os.environ.get('SIMLIBS_WEB_BROWSER_TEST') == '1', 'isolated Chrome required')
class GenerationUiBrowserTests(BrowserCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params_reply = {'params': {'mode': 'local', 'mode_version': 2, 'te': 1, 'ne': 1e17,
            'resolution': 1000, 'low_w': 240, 'up_w': 260, 'max_ion_charge': 2,
            'headless': True, 'resample': False, 'local_broadening_enabled': False},
            'composition': [{'el': 'Fe', 'pct': 100}],
            'local_capabilities': capabilities(Settings().line_database)}

    def setUp(self):
        super().setUp()
        WebDriverWait(self.driver, 10).until(lambda d: self.js('return state.localSymbols.length===31'))
        self.settle()

    def settle(self):
        self.driver.execute_async_script("""const done=arguments[0];
            Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity)
                .map(a=>a.finished.catch(()=>{}))).then(()=>requestAnimationFrame(()=>requestAnimationFrame(done)));""")

    def click(self, selector):
        element = self.driver.find_element(By.CSS_SELECTOR, selector)
        self.js("arguments[0].scrollIntoView({block:'center'})", element)
        self.settle()
        # Earlier expected validation/fixture errors can leave a toast over the target.
        # Wait for normal dismissal and hit testing; keep the real WebDriver click.
        WebDriverWait(self.driver, 6).until(lambda d: self.js("""const target=arguments[0],r=target.getBoundingClientRect();
            const top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return target===top||target.contains(top);""", element))
        element.click()

    def generation(self, kind):
        self.click('#batchGenerationSeg [data-v=' + kind + ']')

    def toggle(self, id):
        self.click('#' + id + ' + .track')

    def edit(self, selector, value):
        element = self.driver.find_element(By.CSS_SELECTOR, selector)
        self.js("arguments[0].scrollIntoView({block:'center'})", element)
        element.send_keys(Keys.CONTROL, 'a', Keys.BACKSPACE)
        if value:
            element.send_keys(str(value))
        return element

    def batch(self):
        self.js("switchPage('batch');state.batchComp=[{el:'Fe',pct:20},{el:'Al',pct:40},{el:'Ca',pct:40}];renderBatchComposition()")
        self.settle()

    def invoke(self, function='runBatch'):
        self.driver.execute_async_script('const done=arguments[0];' + function + '().then(done,done);')

    def test_offline_notice_and_shared_path_switch_spacing(self):
        self.js('setOffline(true)')
        self.assertEqual(self.driver.find_element(By.ID, 'offlineBanner').text.replace('⚠', '').strip(), '未检测到后端服务')
        self.assertEqual(self.js("return $('#toasts .toast b').textContent"), '未检测到后端服务')
        self.invoke('runSingle')
        self.assertFalse(type(self).received)
        self.assertNotIn('start_web', self.js('return document.body.innerText'))
        self.assertNotIn('纯前端示意模式', self.js('return document.body.innerText'))
        self.js("setOffline(false);$('#toasts').replaceChildren()")
        for width in (1366, 800):
            self.driver.set_window_size(width, 1000)
            gaps = []
            for theme in ('dark', 'light'):
                self.js('themePreference.mode=arguments[0];applyTheme()', theme)
                for page, path, switch in (('single', 'broadSeg', 'localBroadeningControl'),
                                            ('batch', 'batchPathBox', 'batchBroadeningControl')):
                    self.js("switchPage(arguments[0]);$('#'+arguments[1]).scrollIntoView({block:'center'})", page, path)
                    self.settle()
                    gaps.append(self.js("return $('#'+arguments[1]).getBoundingClientRect().top-$('#'+arguments[0]).getBoundingClientRect().bottom", path, switch))
                    self.assertTrue(self.js('return document.documentElement.scrollWidth<=innerWidth+2'))
            self.assertTrue(all(gap >= 12 for gap in gaps), gaps)
            self.assertLess(max(gaps) - min(gaps), 1, gaps)

    def test_one_editor_inline_random_and_drafts_survive_panel_switches(self):
        self.batch()
        self.js("window.savedEditor=$('#batchCompositionEditor');window.savedPct=$('.batch-pct')")
        self.edit('.batch-pct', '')
        self.generation('random')
        self.toggle('randomConcentration1')
        self.edit('#concentrationMin1', 'bad')
        self.edit('#concentrationMax1', '101')
        self.toggle('randomTe');self.edit('#batchTeA', 'invalid')
        self.toggle('randomNe');self.edit('#batchNeB', 'invalid')
        before = self.js('return JSON.stringify(state.batchComp)')
        for kind in ('fixed', 'template', 'random'):
            self.generation(kind)
            self.assertEqual(self.js('return JSON.stringify(state.batchComp)'), before)
            self.assertTrue(self.js("return savedEditor===$('#batchCompositionEditor')&&savedPct===$('.batch-pct')"))
            self.assertEqual(self.js("return $$('#batchCompositionEditor').length"), 1)
            self.assertFalse(self.js("return $('#batchControls .composition-editor')!==null"))
            self.assertEqual(self.driver.find_element(By.ID, 'batchFixedControls').is_displayed(), kind == 'fixed')
            self.assertEqual(self.driver.find_element(By.ID, 'batchRandomControls').is_displayed(), kind == 'random')
            self.assertEqual(self.driver.find_element(By.ID, 'batchTemplateControls').is_displayed(), kind == 'template')
            self.assertEqual(self.driver.find_element(By.ID, 'batchCompositionEditor').is_displayed(), kind != 'template')
            self.assertEqual(self.driver.find_element(By.CSS_SELECTOR, '.batch-pct').get_attribute('value'), '')
        self.assertEqual(self.driver.find_element(By.ID, 'concentrationMin1').get_attribute('value'), 'bad')
        self.assertEqual(self.driver.find_element(By.ID, 'batchTeA').get_attribute('value'), 'invalid')
        self.assertEqual(self.driver.find_element(By.ID, 'batchNeB').get_attribute('value'), 'invalid')
        self.assertTrue(self.driver.find_element(By.ID, 'randomConcentration1').is_selected())
        self.assertFalse(self.driver.find_element(By.CSS_SELECTOR, '#batchCompositionRow1 .batch-pct').is_enabled())
        self.assertFalse(self.driver.find_element(By.CSS_SELECTOR, '#batchCompositionRow1 .batch-pct-slider').is_enabled())
        self.assertTrue(self.js("return $$('#batchCompRows .batch-random-switch').every(label=>label.previousElementSibling.classList.contains('batch-pct-slider')&&label.nextElementSibling.classList.contains('concentration-bounds'))"))
        self.assertEqual(self.js("return $$('#concentrationRandomControls,.random-concentration').length"), 0)
        self.toggle('randomConcentration1')
        self.assertTrue(self.driver.find_element(By.CSS_SELECTOR, '#batchCompositionRow1 .batch-pct').is_enabled())
        self.assertEqual(self.driver.find_element(By.CSS_SELECTOR, '#batchCompositionRow1 .batch-pct').get_attribute('value'), '40')
        self.assertFalse(self.driver.find_element(By.ID, 'concentrationMin1').is_displayed())
        self.generation('fixed')
        self.assertFalse(self.driver.find_element(By.CSS_SELECTOR, '.batch-random-switch').is_displayed())
        ids = self.js('return $$(`[id]`).map(e=>e.id)')
        self.assertEqual(len(ids), len(set(ids)))

    def test_exact_percentage_slider_balance_completion_and_32_rows(self):
        self.batch()
        first = self.edit('.batch-pct', '20.1234567890123')
        first.send_keys(Keys.TAB)
        self.assertEqual(first.get_attribute('value'), '20.1234567890123')
        self.assertAlmostEqual(float(self.driver.find_element(By.CSS_SELECTOR, '.batch-pct-slider').get_attribute('value')), 20.1234567890123)
        self.assertAlmostEqual(self.js('return state.batchComp.reduce((s,c)=>s+Number(c.pct),0)'), 100)
        self.invoke()
        self.assertEqual(type(self).received[-1][1]['generation']['concentrations'][0]['fixed'], 20.1234567890123)
        slider = self.driver.find_element(By.CSS_SELECTOR, '.batch-pct-slider')
        self.js("arguments[0].scrollIntoView({block:'center'})", slider)
        slider.send_keys(Keys.ARROW_RIGHT)
        self.assertAlmostEqual(float(first.get_attribute('value')), float(slider.get_attribute('value')))
        self.click('.batch-pct-slider')
        self.assertTrue(self.js("return $('.batch-pct')===arguments[0]", first))
        self.assertAlmostEqual(self.js('return state.batchComp.reduce((s,c)=>s+Number(c.pct),0)'), 100)
        field = self.edit('.batch-el', 'cu')
        self.click('#batchOptions0 button')
        self.assertEqual(field.get_attribute('value'), 'Cu')
        field = self.edit('#batchCompositionRow1 .batch-el', 'mg')
        field.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
        self.assertEqual(field.get_attribute('value'), 'Mg')
        for draft in ('', '-1', 'NaN', 'Infinity'):
            self.edit('.batch-pct', draft)
            type(self).received.clear();self.invoke()
            self.assertFalse(type(self).received)
        self.edit('.batch-pct', '20').send_keys(Keys.TAB)
        self.edit('.batch-el', 'bad')
        type(self).received.clear();self.invoke();self.assertFalse(type(self).received)
        self.js("$('#batchMode').value='client';state.batchComp=ELEMENT_SYMBOLS.slice(0,32).map((el,i)=>({el,pct:i===0?100:0}));renderBatchComposition()")
        self.click('#batchAddElement')
        self.assertEqual(self.js('return state.batchComp.length'), 32)
        self.assertEqual(self.js("return $$('#batchCompRows .batch-composition-row').length"), 32)
        self.click('#batchCompositionRow0 .comp-del')
        self.assertEqual(self.js('return state.batchComp.length'), 31)
        self.assertEqual(self.js("return $$('#randomConcentration0').length"), 1)

    def test_fixed_random_template_contracts_and_invalid_bounds(self):
        self.batch();self.invoke()
        fixed = type(self).received[-1][1]
        self.assertEqual(fixed['generation'], {'kind': 'fixed', 'te': {'enabled': False}, 'ne': {'enabled': False},
            'concentrations': [{'el': 'Fe', 'enabled': False, 'fixed': 20},
                               {'el': 'Al', 'enabled': False, 'fixed': 40}, {'el': 'Ca', 'enabled': False, 'fixed': 40}]})
        self.generation('random')
        for id in ('randomTe', 'randomNe', 'randomConcentration1', 'randomConcentration2'):
            self.toggle(id)
        for selector, value in (('#batchTeA','1.1'),('#batchTeB','1.4'),('#batchNeA','1.23456789123e17'),
                                ('#batchNeB','2e17'),('#concentrationMin1','30'),('#concentrationMax1','50'),
                                ('#concentrationMin2','30'),('#concentrationMax2','50')):
            self.edit(selector, value)
        self.invoke();body = type(self).received[-1][1]
        self.assertEqual(body['generation']['te'], {'enabled': True, 'min': 1.1, 'max': 1.4})
        self.assertEqual(body['generation']['ne'], {'enabled': True, 'min': 1.23456789123e17, 'max': 2e17})
        self.assertEqual(body['generation']['concentrations'], [{'el':'Fe','enabled':False,'fixed':20},
            {'el':'Al','enabled':True,'min':30,'max':50}, {'el':'Ca','enabled':True,'min':30,'max':50}])
        self.assertEqual((body['n_samples'],body['batch_size'],body['seed']), (48,32,42))
        for draft in ('', 'NaN', '60'):
            self.edit('#concentrationMin1', draft)
            type(self).received.clear();self.invoke();self.assertFalse(type(self).received)
            self.assertIn('边界', self.driver.find_element(By.ID, 'batchSumVal').text)
        self.edit('#concentrationMin1','30');self.edit('#concentrationMax1','31')
        self.edit('#concentrationMax2','31')
        type(self).received.clear();self.invoke();self.assertFalse(type(self).received)
        self.edit('#concentrationMin1','bad')
        self.toggle('randomConcentration1');self.toggle('randomConcentration2')
        self.edit('#batchTeA','bad');self.edit('#batchNeB','bad')
        self.toggle('randomTe');self.toggle('randomNe')
        type(self).received.clear();self.invoke()
        self.assertEqual(type(self).received[-1][1]['generation']['concentrations'], fixed['generation']['concentrations'])
        self.generation('template')
        self.js("state.batchComp[0].el='bad';state.batchComp[0].pct='';$('#batchTe').value='bad';$('#batchNe').value='bad'")
        text = 'name,Fe_at%,Al_at%,Te[eV],Ne[cm^-3],R\nfirst,100,0,1.2,1.4e17,1000\nsecond,50,50,1.3,1.6e17,2000\n'
        path = Path(type(self).temp.name) / 'generation-template.csv'
        # Preserve the exact fixture bytes on Windows; assert upload content verbatim.
        path.write_bytes(text.encode('utf-8'))
        self.driver.find_element(By.ID, 'templateFile').send_keys(str(path))
        WebDriverWait(self.driver,5).until(lambda d:'计划2谱' in d.find_element(By.ID,'templateInfo').text)
        self.edit('#templateRepeat','2').send_keys(Keys.TAB)
        WebDriverWait(self.driver,5).until(lambda d:'计划4谱' in d.find_element(By.ID,'templateInfo').text)
        self.invoke();template = type(self).received[-1][1]
        self.assertNotIn('generation', template)
        self.assertEqual(template['template_csv'], text)
        self.assertEqual((template['n_samples'],template['repeats'],template['name_column']), (4,2,'name'))


if __name__ == '__main__':
    unittest.main()
