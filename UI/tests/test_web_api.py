from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from simlibs_ui.models import Parameters, ELEMENTS

WEB_ROOT=Path(__file__).resolve().parents[1]/'web'
if str(WEB_ROOT) not in sys.path:sys.path.insert(0,str(WEB_ROOT))
import backend_api
from real_backend import RealBackend
from mock_backend import MockBackend


class WebAPITests(unittest.TestCase):
    def test_display_budget_is_separate_from_physical_limit(self):
        self.assertEqual(backend_api.MAX_PREVIEW_POINTS,6000)
        self.assertEqual(backend_api.MAX_SINGLE_POINTS,200000)

    def test_flux_defaults_validation_and_three_operations_forwarding(self):
        base={'te':1.,'ne':1e17,'resolution':1000,'low_w':650.,'up_w':660.,'max_ion_charge':3,'mode':'static'}
        self.assertEqual(getattr(backend_api.CommonParams.from_api(base),'intensity_scale',None),'photon')
        with self.assertRaises(backend_api.ApiError):backend_api.CommonParams.from_api(dict(base,intensity_scale='watts'))
        backend=RealBackend.__new__(RealBackend)
        for scale in ('photon','energy'):
            params=dict(base,intensity_scale=scale)
            body={'params':params,'composition':[{'el':'H','pct':100}]}
            reqs=[('start_single',backend_api.SingleRequest.from_api(body)),
                  ('start_batch',backend_api.BatchRequest.from_api(dict(params=params,n_samples=2,te_range=[1,1],ne_range=[17,17],compositions=[{'name':'H','items':body['composition']}]))),
                  ('start_scan',backend_api.ScanRequest.from_api(dict(body,axis='te',start=1,end=1.2,frames=2)))]
            for method,req in reqs:
                with self.subTest(scale=scale,method=method),patch.object(backend,'_launch',return_value='fixture') as launch:
                    getattr(backend,method)(req)
                self.assertEqual(launch.call_args.args[2]['parameters']['intensity_scale'],scale)

    def test_api_periodic_table_and_strict_total(self):
        for element in ('Xx','FE',''):
            with self.subTest(element=element),self.assertRaises(backend_api.ApiError):
                backend_api.validate_composition([backend_api.CompositionItem(element,100)])
        for pct in (99,101):
            with self.assertRaises(backend_api.ApiError):backend_api.validate_composition([backend_api.CompositionItem('Fe',pct)])

    def test_real_result_scale_and_mock_are_explicit(self):
        from tests.test_web_sampling import RealWebDataTests
        fixture=RealWebDataTests();fixture.setUp()
        try:
            fixture.manifest['origin'].update(intensity_scale='energy',int_scale=1)
            result=fixture.backend._single_result({},fixture.manifest)
            self.assertEqual(result['meta'].get('intensity_scale'),'energy')
            self.assertIn('a.u.',result['meta']['intensity_units'])
        finally:fixture.temp.cleanup()
        backend=MockBackend.__new__(MockBackend);backend._jobs={'fixture':{'duration':'0s'}}
        p=backend_api.CommonParams.from_api({'te':1,'ne':1e17,'resolution':1000,'low_w':650,'up_w':660,'max_ion_charge':3,'mode':'static','intensity_scale':'energy'})
        result=backend._single_result('fixture',p,['H'])
        self.assertEqual(result['meta'].get('requested_intensity_scale'),'energy')
        self.assertEqual(result['meta'].get('intensity_scale'),'unknown')
        self.assertIn('MOCK',result['meta']['source'])
        self.assertEqual(result['yi'],[])

    def test_scan_api_derived_values_are_finite_and_ne_overflow_rejected(self):
        import math
        values=backend_api.scan_values(1e308,1.7e308,5)
        self.assertTrue(all(math.isfinite(v) for v in values))
        params={'te':1,'ne':1e17,'resolution':1000,'low_w':650,'up_w':660,'max_ion_charge':3,'mode':'static'}
        with self.assertRaises(backend_api.ApiError):
            backend_api.ScanRequest.from_api({'params':params,'axis':'ne','start':307,'end':310,'frames':2,'composition':[{'el':'H','pct':100}]})

    def test_restart_restores_only_terminal_project_results(self):
        import tempfile,json
        from dataclasses import replace
        from simlibs_ui.settings import Settings
        from simlibs_ui.storage import save_result,write_json
        import pandas as pd
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);jid='a'*32
            save_result(root/'.jobs'/jid/'result',{'interpolated':pd.DataFrame({'wavelength':[1.,2.],'intensity':[0.,1.]})},{'kind':'history'})
            write_json(root/'.web-session.json',{'jobs':[{'job_id':jid,'status':'completed','kind':'单次模拟'},
                                                       {'job_id':'b'*32,'status':'running'}, {'job_id':'../bad','status':'completed'}]})
            backend=RealBackend.__new__(RealBackend);backend._jobs={};backend._settings_path=root/'settings.json'
            backend._settings=replace(Settings(),output=str(root))
            backend._restore_session()
            self.assertEqual(list(backend._jobs),[jid])
            self.assertEqual(backend._jobs[jid]['status'],'completed')
            self.assertEqual(backend._jobs[jid]['manifest']['origin']['kind'],'history')

    def test_single_export_title_uses_actual_origin_parameters(self):
        title=RealBackend._chart_title({'origin':{'parameters':{'elements':['H'],'Te':1.,'Ne':1e17}}})
        self.assertIn('Te=1 ',title)
        self.assertIn('Ne=1e+17',title)
        self.assertIn('cm^-3',title,'导出标题不能使用当前字体缺失的上标负号')


if __name__=='__main__':unittest.main()
