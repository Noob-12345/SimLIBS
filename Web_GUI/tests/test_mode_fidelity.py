from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit
import numpy as np
import pandas as pd
from simlibs_ui.models import Parameters,BatchSpec,ScanSpec
from simlibs_ui.mode_engine import client_simulate,grid_for
from simlibs_ui.storage import save_result,read_manifest
from simlibs_ui.settings import Settings,UI_ROOT
sys.path.insert(0,str(UI_ROOT/'web'))
from backend_api import CommonParams,ApiError
from real_backend import RealBackend

HTML="""<script>var dataSticksArray=[[{label:'Wavelength (nm)'},{label:'H I'},{label:'Fe I (4.4e-2)'}],[655,80,20]];var resolution=85;</script>"""


class FidelityTests(unittest.TestCase):
    def p(self,**values):return replace(Parameters(),**dict(dict(webscraping='client',mode_version=2,broadening='local',broaden_grid_step=.01),**values)).validated()
    def response(self,html=HTML):return Mock(text=html)

    def test_versioned_api_legacy_and_fixed_paths_and_three_operation_contracts(self):
        base={'te':1,'ne':1e17,'resolution':1000,'low_w':650,'up_w':660,'max_ion_charge':2}
        for mode in ('server','client'):
            p=CommonParams.from_api(dict(base,mode=mode,mode_version=2))
            self.assertEqual(p.broadening,'nist' if mode=='server' else 'local')
            core=RealBackend._to_parameters(p,[])
            self.assertEqual((core.webscraping,core.mode_version),(mode,2))
            with self.assertRaises(ApiError):CommonParams.from_api(dict(base,mode=mode))
            with self.assertRaises(ApiError):CommonParams.from_api(dict(base,mode=mode,mode_version=2,broadening='local' if mode=='server' else 'nist'))
        for mode in ('static','dynamic'):
            self.assertEqual(CommonParams.from_api(dict(base,mode=mode)).mode_version,1)
        with self.assertRaises(ApiError):CommonParams.from_api(dict(base,mode='server',mode_version=2,broaden_convention='physics'))
        self.assertEqual(BatchSpec(size=3,batch_size=2).validated(self.p()).batch_size,2)
        self.assertEqual(ScanSpec(axis='R',start=1000,stop=2000).validated(self.p()),[1000,2000])

    def test_client_requests_preserve_ne_scale_threshold_and_never_launch_browser(self):
        getter=Mock(return_value=self.response())
        p=self.p(Ne=1.23456789123456e17,intensity_scale='photon')
        with patch('simlibs_ui.adapter.resolve_driver') as browser:
            frames,origin=client_simulate(p,Settings(),request_get=getter)
        browser.assert_not_called()
        query=parse_qs(urlsplit(getter.call_args.args[0]).query)
        self.assertEqual(query['eden'],[f'{p.Ne:.15g}'])
        self.assertEqual(query['min_rel_int'],['0.0'])
        self.assertEqual(query['int_scale'],['2'])
        self.assertEqual(len(frames['raw']),1001)
        self.assertEqual(origin['actual_resolution'],1000)
        self.assertEqual(origin['line_strength_location'],'NIST server')

    def test_client_matches_readonly_reference_kernel_and_physics_fwhm(self):
        path=Path(r'D:\LIBS\Deeplearning\Cross_attention\Dataset\nist_reconstruction.py')
        spec=importlib.util.spec_from_file_location('readonly_reference_kernel',path)
        reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
        p=self.p(broaden_grid_step=.001)
        frames,_=client_simulate(p,Settings(),request_get=Mock(return_value=self.response()))
        table=reference.parse_nist_matrix(HTML,'dataSticksArray')
        expected=reference.render_nist_sticks(table,grid_for(p,p.broaden_grid_step),1000)
        np.testing.assert_allclose(frames['raw']['intensity'],expected['intensity'],rtol=1e-14,atol=1e-14)
        physics=replace(p,broaden_convention='physics')
        frames,origin=client_simulate(physics,Settings(),request_get=Mock(return_value=self.response()))
        y=frames['raw']['intensity'].to_numpy();x=frames['raw']['wavelength'].to_numpy()
        support=x[y>=y.max()/2]
        self.assertAlmostEqual(support[-1]-support[0],655/1000,delta=.003)
        self.assertAlmostEqual(origin['broadening_params']['render_resolution'],2*np.sqrt(np.log(2))*1000)

    def test_split_core_overlap_keeps_each_boundary_line_once(self):
        html=HTML.replace('[655,80,20]','[699,80,20],[700,80,20],[701,80,20]')
        getter=Mock(return_value=self.response(html))
        frames,origin=client_simulate(self.p(low_w=200,upper_w=1200,broaden_grid_step=.01),Settings(),request_get=getter)
        self.assertEqual(getter.call_count,2)
        self.assertEqual(origin['line_table_rows'],3)
        urls=[parse_qs(urlsplit(call.args[0]).query) for call in getter.call_args_list]
        self.assertEqual([(q['low_w'][0],q['upp_w'][0]) for q in urls],[('200','702'),('698','1200')])

    def test_invalid_ion_strength_metadata_and_cancel_reject_without_next_request(self):
        for html in (HTML.replace('4.4e-2','NaN'),HTML.replace('80,20','-1,20'),HTML.replace('80,20','NaN,20')):
            with self.subTest(html=html),self.assertRaises(ValueError):
                client_simulate(self.p(),Settings(),request_get=Mock(return_value=self.response(html)))
        getter=Mock()
        with self.assertRaises(InterruptedError):client_simulate(self.p(),Settings(),cancelled=lambda:True,request_get=getter)
        getter.assert_not_called()

    def test_full_50001_nodes_element_sums_and_lazy_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            x=np.linspace(200,700,50001);a=np.sin(x)**2;b=np.cos(x)**2*.01
            ion=pd.DataFrame({'Wavelength (nm)':x,'H I':a*.75,'H II':a*.25,'Fe I (4.4e-2)':b,'Sum(calc)':a+b})
            total=pd.DataFrame({'wavelength':x,'intensity':a+b})
            path=save_result(Path(directory)/'sample',{'raw':total,'interpolated':total,'ion':ion},{'kind':'simulation','actual_resolution':3000})
            m=read_manifest(path);backend=RealBackend.__new__(RealBackend)
            output=backend._single_result({},m)
            self.assertEqual(len(output['xs']),50001)
            saved=pd.read_csv(m['files']['interpolated'],float_precision='round_trip')
            np.testing.assert_array_equal(output['ys'],saved['intensity'])
            group=output['series']['elements']['raw']
            self.assertEqual([row['label'] for row in group['curves']],['Fe','H'])
            np.testing.assert_allclose(group['curves'][1]['ys'],a,rtol=1e-14)
            backend._lock=threading.Lock();backend._jobs={'frame-test':{'job_id':'frame-test','status':'completed','manifest':{'kind':'scan','axis':'R','completed_values':[1000,2000],'frames':[path,path]}}}
            meta=backend.get_result('frame-test')
            self.assertTrue(meta['lazy_frames']);self.assertNotIn('xs',meta['frames'][0])
            frame=backend.get_result('frame-test',frame=1)
            self.assertEqual(len(frame['xs']),50001)

    def test_resampling_total_and_all_ions_share_exact_transform(self):
        p=self.p(resample=True,step=.02)
        frames,_=client_simulate(p,Settings(),request_get=Mock(return_value=self.response()))
        self.assertEqual(len(frames['interpolated']),501)
        ion=frames['ion_interpolated']
        np.testing.assert_allclose(ion['H I']+ion['Fe I (4.4e-2)'],ion['Sum(calc)'],rtol=1e-14)
        np.testing.assert_array_equal(ion['Sum(calc)'],frames['interpolated']['intensity'])


if __name__=='__main__':unittest.main()
