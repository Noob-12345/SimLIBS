from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
import pandas as pd
from simlibs_ui.storage import save_result, read_manifest, write_json

WEB_ROOT = Path(__file__).resolve().parents[1]/'web'
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))
from real_backend import RealBackend

try:
    from sampling import sample_indices
except ImportError:
    sample_indices = None


class SamplingTests(unittest.TestCase):
    def test_preserves_narrow_and_weak_peaks_without_inventing_values(self):
        self.assertIsNotNone(sample_indices, '保峰抽样尚未实现')
        x = np.linspace(400, 700, 12001)
        y = np.zeros(len(x))
        y[197], y[8765] = 1802, 1e-12
        indices = sample_indices(x, y, 6000)
        self.assertEqual(len(indices), 6000)
        self.assertEqual((indices[0], indices[-1]), (0, len(x)-1))
        self.assertTrue(all(a < b for a,b in zip(indices,indices[1:])))
        self.assertIn(197, indices)
        self.assertIn(8765, indices)
        self.assertEqual(y[indices][list(indices).index(8765)], 1e-12)

    def test_sparse_and_independent_ion_peaks(self):
        self.assertIsNotNone(sample_indices)
        np.testing.assert_array_equal(sample_indices([1,2,3], [0,1,0], 6000), [0,1,2])
        x = np.arange(5001.)
        y = np.zeros((5001,2))
        y[199,0], y[2999,1] = 100, 1e-14
        indices = sample_indices(x,y,2000)
        self.assertIn(199,indices)
        self.assertIn(2999,indices)


class RealWebDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.backend = RealBackend.__new__(RealBackend)
        x = 650 + np.arange(12001)*.0005
        y = np.zeros(len(x));y[197]=1802;y[8765]=1e-12
        raw = pd.DataFrame({'wavelength':[650.,651.2,656.,660.], 'intensity':[0.,1e-12,1802.,0.]})
        interp = pd.DataFrame({'wavelength':x,'intensity':y})
        ion = pd.DataFrame({'Wavelength (nm)':[649.,650.125,653.000000123,659.,662.],
                            'H I':[0.,2e-13,1.,2.,0.], 'He I':[0.,1.,2.,3.,0.], 'Sum(calc)':[0.,1.,3.,5.,0.]})
        self.manifest_path = save_result(self.path/'spectrum', {'raw':raw,'interpolated':interp,'ion':ion},
                                         {'kind':'simulation','label':'offline test transport fixture'})
        self.manifest = read_manifest(self.manifest_path)

    def test_single_reads_full_csv_and_keeps_real_raw_and_ions(self):
        result = self.backend._single_result({'duration':'1s'},self.manifest)
        self.assertGreater(len(result['xs']),1500)
        self.assertEqual(len(result['xs']),12001)
        self.assertIn(1e-12,result['ys'])
        series = result.get('series')
        self.assertIsNotNone(series, '各真实序列不能共用插值数组冒充raw/ion')
        self.assertEqual(series['raw']['xs'],[650.,651.2,656.,660.])
        self.assertEqual(series['raw']['ys'],[0.,1e-12,1802.,0.])
        self.assertEqual([s['label'] for s in series['ions']],['H I','He I'])
        self.assertEqual(series['ions'][0]['xs'][2],653.000000123)
        self.assertEqual(series['ions'][0]['ys'][1],2e-13)
        self.assertEqual(result['yi'], [], 'Sum(calc)不能伪装成某个离子')

    def test_static_has_no_fabricated_ion_sequence(self):
        manifest = dict(self.manifest)
        manifest['files'] = {k:v for k,v in manifest['files'].items() if k!='ion'}
        result = self.backend._single_result({},manifest)
        self.assertEqual(result['yi'],[])
        self.assertEqual(result['series']['ions'],[])

    def test_scan_loads_each_current_frame_without_display_budget(self):
        result = self.backend._scan_result({}, {'kind':'scan','axis':'Te','completed_values':[1,2],
                                               'frames':[self.manifest_path,self.manifest_path]})
        self.assertEqual(len(result['frames']),2)
        self.assertTrue(result['lazy_frames'])
        self.backend._lock=__import__('threading').Lock()
        self.backend._jobs={'fixture':{'status':'completed','manifest':{'kind':'scan','completed_values':[1,2],'frames':[self.manifest_path,self.manifest_path]}}}
        for i in range(2):
            frame=self.backend.get_result('fixture',frame=i)
            self.assertEqual(len(frame['xs']),12001)
            self.assertIn(1e-12,frame['ys'])
            self.assertEqual(frame['series']['raw']['xs'],[650.,651.2,656.,660.])


if __name__=='__main__':
    unittest.main()
