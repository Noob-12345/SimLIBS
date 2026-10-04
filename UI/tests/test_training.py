"""训练 CSV 真实格式、完整数据、分包、取消和 API/下载契约回归。"""
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd

from simlibs_ui.models import Parameters, BatchSpec
from simlibs_ui.operations import batch, export_result
from simlibs_ui.settings import Settings, UI_ROOT
from simlibs_ui.storage import read_manifest
from simlibs_ui.training import REFERENCE_ELEMENTS, build_training_package

sys.path.insert(0, str(UI_ROOT/'web'))
from backend_api import BatchRequest, ApiError
from real_backend import RealBackend
from mock_backend import MockBackend


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pool = pd.DataFrame({'H': [100., 50.], 'W': [0., 50.], 'name': ['hydrogen', 'mixture']})
        self.calls = []

    def simulate(self, p, settings):
        self.calls.append(p)
        x = np.array([650., 655., 660.])
        frame = pd.DataFrame({'wavelength': x, 'intensity': x/655*p.Te})
        return {'raw': frame, 'interpolated': frame}, {'kind': 'simulation', 'parameters': p.to_dict(),
                 'actual_Ne': str(float(f'{p.Ne:.3g}')), 'label': 'offline transport fixture', 'nist_url': 'https://physics.nist.gov/?int_scale=2'}

    def generate(self, count=5, size=2, simulator=None):
        path = batch(Parameters(), Settings(), BatchSpec(size=count, batch_size=size), self.pool,
                     self.root/'result', lambda *a, **k: None, lambda: False, simulator or self.simulate)
        return path, read_manifest(path)

    def test_five_spectra_two_per_package_pair_names_rows_labels_and_exact_saved_data(self):
        path, manifest = self.generate()
        package = manifest['training_package']
        self.assertEqual(package['sample_counts'], [2, 2, 1])
        self.assertEqual(package['label_order'], REFERENCE_ELEMENTS+['H', 'W'])
        with zipfile.ZipFile(package['archive']) as archive:
            self.assertIsNone(archive.testzip())
            meta = json.loads(archive.read('package-manifest.json'))
            source = json.loads(archive.read('source-manifest.json'))
            self.assertEqual(source['dataset'], manifest['dataset'])
            self.assertFalse(source['partial'])
            index = 0
            for ordinal, expected in enumerate([2, 2, 1], 1):
                suffix = '' if ordinal==1 else f'_{ordinal}'
                spectra = list(csv.reader(io.StringIO(archive.read(f'Random_spectra{suffix}.csv').decode())))
                contents = list(csv.reader(io.StringIO(archive.read(f'Random_contents{suffix}.csv').decode())))
                self.assertEqual(len(spectra), expected*2)
                self.assertEqual(len(contents), expected+1)
                self.assertEqual(contents[0], REFERENCE_ELEMENTS+['H', 'W'])
                for local in range(expected):
                    sample = read_manifest(manifest['samples'][index])
                    saved = pd.read_csv(sample['files']['interpolated'], float_precision='round_trip')
                    np.testing.assert_array_equal(np.array(spectra[local*2], float), saved['wavelength'])
                    np.testing.assert_array_equal(np.array(spectra[local*2+1], float), saved['intensity'])
                    percentages = dict(zip(self.calls[index].elements, self.calls[index].percentages))
                    np.testing.assert_array_equal(np.array(contents[local+1], float), [percentages.get(e,0) for e in contents[0]])
                    self.assertEqual(meta['samples'][index]['origin'], sample['origin'])
                    index += 1
        target = self.root/'download.zip'
        export_result(path, target, 'training')
        self.assertEqual(target.read_bytes(), Path(package['archive']).read_bytes())

    def test_full_50001_point_two_row_format_not_display_preview(self):
        def large(p, s):
            x = np.linspace(200, 700, 50001)
            frame = pd.DataFrame({'wavelength': x, 'intensity': np.sin(x)**2})
            return {'interpolated': frame}, {'kind':'simulation', 'parameters':p.to_dict()}
        path, manifest = self.generate(1, 32, large)
        sample = read_manifest(manifest['samples'][0])
        self.assertEqual(len(sample['preview']['interpolated']), 1500)
        with zipfile.ZipFile(manifest['training_package']['archive']) as archive:
            rows = list(csv.reader(io.StringIO(archive.read('Random_spectra.csv').decode())))
            self.assertEqual(len(rows),2)
            self.assertEqual([len(r) for r in rows], [50001, 50001])
            self.assertEqual(float(rows[0][0]),200)
            self.assertEqual(float(rows[0][-1]),700)

    def test_size_larger_than_total_gives_one_package(self):
        _, manifest = self.generate(2, 32)
        self.assertEqual(manifest['training_package']['sample_counts'],[2])

    def test_cancel_and_simulation_failure_publish_no_package(self):
        path = batch(Parameters(), Settings(), BatchSpec(size=3,batch_size=2), self.pool, self.root/'cancel',
                     lambda *a, **k:None, lambda:bool(self.calls), self.simulate)
        result = read_manifest(path)
        self.assertTrue(result['partial'])
        self.assertNotIn('training_package',result)
        with self.assertRaises(ValueError): export_result(path, self.root/'cancel.zip','training')
        self.calls.clear()
        def fail(p,s):
            if self.calls:raise RuntimeError('failed actual sample')
            return self.simulate(p,s)
        with self.assertRaises(RuntimeError):
            batch(Parameters(),Settings(),BatchSpec(size=3),self.pool,self.root/'fail',lambda *a,**k:None,lambda:False,fail)
        self.assertNotIn('training_package',read_manifest(self.root/'fail'/'manifest.json'))

    def test_cancel_during_packaging_and_packaging_failure_mark_partial(self):
        for failure in (InterruptedError('cancelled package'), ValueError('grid mismatch')):
            with self.subTest(failure=type(failure).__name__),patch('simlibs_ui.training.build_training_package',side_effect=failure):
                self.calls.clear()
                directory = self.root/type(failure).__name__
                with self.assertRaises(type(failure)):
                    batch(Parameters(),Settings(),BatchSpec(size=2),self.pool,directory,lambda *a,**k:None,lambda:False,self.simulate)
                manifest=read_manifest(directory/'manifest.json')
                self.assertTrue(manifest['partial'])
                self.assertNotIn('training_package',manifest)

    def test_saved_grid_mismatch_and_cancellation_rejected_by_packager(self):
        _, manifest = self.generate(2,2)
        sample=read_manifest(manifest['samples'][1])
        frame=pd.read_csv(sample['files']['interpolated'])
        frame.loc[1,'wavelength'] += .1
        frame.to_csv(sample['files']['interpolated'],index=False)
        with self.assertRaisesRegex(ValueError,'网格'):
            build_training_package(self.root/'result',manifest)
        with self.assertRaises(InterruptedError):
            build_training_package(self.root/'result',manifest,lambda:True)

    def test_api_strict_batch_size_ranges_and_core_local_grid(self):
        body={'params':{'te':1,'ne':1e17,'resolution':1000,'low_w':650,'up_w':660,'max_ion_charge':3,'mode':'static'},
              'n_samples':3,'seed':42,'te_range':[1,1],'ne_range':[17,17],
              'compositions':[{'name':'H','items':[{'el':'H','pct':100}]}]}
        self.assertEqual(BatchRequest.from_api(body).batch_size,32)
        for size in (0,-1,1.2,None,True,5001,float('inf')):
            with self.subTest(size=size),self.assertRaises(ApiError):BatchRequest.from_api(dict(body,batch_size=size))
            with self.subTest(core=size),self.assertRaises(ValueError):BatchSpec(batch_size=size).validated(Parameters())
        for field,value in [('te_range',[0,1]),('ne_range',[309,310]),('ne_range',[-400,-399])]:
            with self.subTest(field=field,value=value),self.assertRaises(ApiError):BatchRequest.from_api(dict(body,**{field:value}))
        local=replace(Parameters(),webscraping='dynamic',broadening='local',low_w=200,upper_w=700,broaden_grid_step=.01,resample=False)
        self.assertEqual(local.points,50001)
        self.assertEqual(BatchSpec(size=3,batch_size=2).validated(local).batch_size,2)
        backend=RealBackend.__new__(RealBackend)
        with patch.object(backend,'_launch',return_value='fixture') as launch:
            backend.start_batch(BatchRequest.from_api(dict(body,batch_size=2)))
        self.assertEqual(launch.call_args.args[0],'批量模拟')
        self.assertEqual(launch.call_args.args[2]['spec']['batch_size'],2)

    def test_download_reuses_zip_and_old_tasks_get_clear_error(self):
        path,manifest=self.generate(3,2)
        backend=RealBackend.__new__(RealBackend);backend._lock=threading.Lock()
        backend._jobs={'fixture':{'status':'completed','result_path':path,'manifest':manifest}}
        first=backend.export('fixture','training');second=backend.export('fixture','training')
        self.assertEqual(first.payload,second.payload)
        self.assertEqual(first.media_type,'application/zip')
        self.assertEqual(len(self.calls),3,'下载不能重新模拟')
        manifest.pop('training_package')
        with self.assertRaises(ApiError) as err:backend.export('fixture','training')
        self.assertEqual(err.exception.status,409)


if __name__=='__main__': unittest.main()
