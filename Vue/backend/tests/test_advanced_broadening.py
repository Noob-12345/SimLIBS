"""Independent branches with SYNTHETIC mixed He/Li, multi-charge test data only."""
from dataclasses import replace
import importlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.special import voigt_profile

from simlibs_ui.adapter import source_module
from simlibs_ui.advanced import options as all_options
from simlibs_ui.advanced_nist import options, simulate
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings
from simlibs_ui.storage import save_result, read_manifest

CMEV = 8065.54393734921
LABELS = ['He I', 'He II', 'Li I', 'Li II']
WAVES = [280.23, 280.43, 280.67, 280.89]
AREAS = [6.5, 2.3, 4.2, 3.7]


def mixed_html(*, levels=True, transitions=True):
    header = "[{label:'Wavelength'}," + ",".join(f"{{label:'{name}'}}" for name in LABELS) + "]"
    rows = [f"[{wave}," + ",".join(str(AREAS[i] if i == j else 0) for j in range(4)) + "]" for i, wave in enumerate(WAVES)]
    # All numbers and atomic arrays below are invented test fixtures, not atomic data.
    result = "var dataSticksArray=[" + ",".join([header] + rows) + "];"
    if transitions:
        result += f'var cmeV={CMEV};'
        rows = []
        for i, (z, el, charge) in enumerate([(2, 'He', 0), (2, 'He', 1), (3, 'Li', 0), (3, 'Li', 1)]):
            result += f"spectra[{z}][{charge+1}]['name']='{el} test';"
            rows.append([WAVES[i], 1e8*(i+1), 30000+i*1000, z, charge+1, 0])
        result += 'var lines='+json.dumps(rows)+';'
    if levels:
        result += 'var koeff=6.043e21;'
        for z in (2, 3):
            for stage in range(1, z+1):
                result += f'levels[{z}][{stage}]=[0,10000];gValues[{z}][{stage}]=[1,2];ips[{z}][{stage}]=[{80000*stage}];'
    return result.encode()


def stark_csv():
    return pd.DataFrame([dict(element='He' if i < 2 else 'Li', charge=i%2, wavelength_nm=WAVES[i],
        lower_eV=0, upper_eV=(30000+i*1000)/CMEV, stark_width_nm=.002*(i+1),
        stark_reference_ne_cm3=1e16, source='SYNTHETIC TEST ONLY') for i in range(4)]).to_csv(index=False)


class Response:
    def __init__(self, html): self.html = html
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, size): yield self.html


class AdvancedBroadeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = replace(Settings(), output=str(self.root))
        self.p = replace(Parameters(), webscraping='local', mode_version=2, broadening='local', broaden_convention='physics',
            elements=('He','Li'), percentages=(40,60), low_w=280, upper_w=281, broaden_grid_step=.001, step=.001, resolution=3000).validated()
        source_module(self.s.source)
        self.engine = importlib.import_module('simLIBS.nist_self_absorption')
        self.lines = importlib.import_module('simLIBS.nist_lines')
        self.calls = []

    def run_model(self, sa=False, stark=False, instrument=False, *, html=None, p=None, extra=None):
        raw = dict(model='nist', self_absorption=sa, stark_broadening=stark, instrument_broadening=instrument,
                   matrix=False, stark_source='local', stark_csv=stark_csv(), density_mode='specified', number_density_cm3=1e16)
        raw.update(extra or {})
        def get(url, **kwargs): self.calls.append(url); return Response(html if html is not None else mixed_html())
        with patch.dict(os.environ, {'SIMLIBS_TASK_DIR': str(self.root)}):
            return simulate(p or self.p, self.s, raw, request_get=get)

    def backend(self, frames, origin):
        web = str(Path(__file__).resolve().parents[1]/'web')
        if web not in sys.path: sys.path.insert(0, web)
        from real_backend import RealBackend
        path = save_result(self.root/'result', frames, origin)
        backend = RealBackend.__new__(RealBackend); backend._lock = threading.Lock(); backend._settings = self.s
        backend._jobs = {'mixed': {'status':'completed','result_path':path,'manifest':read_manifest(path)}}
        return backend

    def test_all_six_valid_combinations_have_nonzero_mixed_elements_and_ion_sum(self):
        for sa, stark in [(False,False),(False,True),(True,True)]:
            for instrument in (False,True):
                with self.subTest(sa=sa,stark=stark,instrument=instrument):
                    frames, origin = self.run_model(sa,stark,instrument)
                    ion = frames['ion']
                    self.assertEqual([c for c in ion if c in LABELS], LABELS)
                    for el in ('He','Li'):
                        self.assertGreater(float(ion[[c for c in LABELS if c.startswith(el+' ')]].sum(axis=1).max()), 0)
                    np.testing.assert_allclose(ion[LABELS].sum(axis=1), frames['raw'].intensity, rtol=1e-14)
                    result = self.backend(frames,origin).get_result('mixed')
                    curves = result['series']['elements']['interpolated']['curves']
                    self.assertEqual([c['label'] for c in curves], ['He','Li'])
                    np.testing.assert_allclose(np.array(curves[0]['ys'])+curves[1]['ys'], frames['raw'].intensity)
                    self.assertEqual(origin['stark_broadening'],stark)
                    self.assertEqual(origin['self_absorption'],sa)
                    self.assertEqual(origin['instrument_broadening'],instrument)
                    self.assertIn('He%3A40%3BLi%3A60', self.calls[-1])

    def test_illegal_absorption_without_stark_is_rejected_not_corrected(self):
        with self.assertRaisesRegex(ValueError,'Stark'): self.run_model(True,False,True)
        self.assertEqual(self.calls,[])

    def test_stark_only_needs_no_levels_saha_or_absorption_draft(self):
        with patch.object(self.engine,'nist_populations',side_effect=AssertionError('Saha called')):
            frames, origin = self.run_model(False,True,False,html=mixed_html(levels=False),
                    extra={'path_length_m':'invalid','number_density_cm3':'invalid','density_mode':'invalid'})
        diagnostics = pd.read_csv(origin['line_table'])
        self.assertTrue((diagnostics.tau_center == 0).all()); self.assertTrue((diagnostics.SA == 1).all())
        self.assertIsNone(origin['matrix']['effective_number_density_cm3'])
        expected = np.zeros(len(frames['raw']))
        for i,wave in enumerate(WAVES):
            width=2*.002*(i+1)*1e17/1e16
            expected += AREAS[i]*voigt_profile(frames['raw'].wavelength-wave,0,width/2)
        np.testing.assert_allclose(frames['raw'].intensity,expected,rtol=1e-13)

    def test_voigt_matches_analytic_multi_ion_profile(self):
        frames,_ = self.run_model(False,True,True,html=mixed_html(levels=False))
        expected = np.zeros(len(frames['raw']))
        for i,wave in enumerate(WAVES):
            expected += AREAS[i]*voigt_profile(frames['raw'].wavelength-wave,wave/3000/math.sqrt(2),.002*(i+1)*10)
        np.testing.assert_allclose(frames['raw'].intensity,expected,rtol=1e-13)

    def test_no_stark_only_stick_payload_and_ignored_invalid_csv_density(self):
        with patch.object(self.engine,'parse_atomic_payload',side_effect=AssertionError('atomic data used')), \
             patch.object(self.engine,'resolve_stark',side_effect=AssertionError('Stark used')):
            for instrument in (False,True):
                frames,origin=self.run_model(False,False,instrument,html=mixed_html(levels=False,transitions=False),
                    extra={'stark_csv':{'invalid':'ignored'},'stark_name':False,'path_length_m':'bad','number_density_cm3':False,'density_mode':None})
                self.assertNotIn('line_table',origin)
                self.assertIsNone(origin['diagnostics']['tau_max'])
                self.assertEqual(origin['stark_input']['rows'],0)
                self.assertGreater(float(frames['raw'].intensity.max()),0)

    def test_unbroadened_projection_conserves_area_centroid_and_ignores_r(self):
        frames, origin=self.run_model()
        self.assertEqual(origin['spectrum_style'],'sticks'); self.assertIsNone(origin['actual_resolution'])
        x=frames['raw'].wavelength.to_numpy()
        for i,label in enumerate(LABELS):
            y=frames['ion'][label].to_numpy()
            self.assertAlmostEqual(float(np.trapezoid(y,x)),AREAS[i],places=12)
            self.assertAlmostEqual(float(np.trapezoid(x*y,x)/np.trapezoid(y,x)),WAVES[i],places=11)
        other,_=self.run_model(p=replace(self.p,resolution=12000))
        np.testing.assert_array_equal(frames['raw'].intensity,other['raw'].intensity)

    def test_stark_only_and_absorption_without_instrument_do_not_apply_r(self):
        for sa in (False,True):
            first,origin=self.run_model(sa,True,False)
            second,_=self.run_model(sa,True,False,p=replace(self.p,resolution=9000))
            np.testing.assert_array_equal(first['raw'].intensity,second['raw'].intensity)
            self.assertIsNone(origin['actual_resolution'])

    def test_gaussian_uses_original_renderer_and_matrix_yield_keeps_mixed_weights(self):
        frames,origin=self.run_model(False,False,True,extra={'matrix':True,'responses':{'He':.5,'Li':.5}})
        table=self.lines.parse_sticks(mixed_html().decode()); table[LABELS]*=.5
        expected=self.lines.render_sticks(table,frames['raw'].wavelength.to_numpy(),3000)
        np.testing.assert_allclose(frames['raw'].intensity,expected.intensity,rtol=1e-14)
        self.assertEqual(origin['matrix']['yield_scale'],.5)
        self.assertIsNone(origin['matrix']['effective_number_density_cm3'])

    def test_legacy_missing_flag_keeps_stark_thin_and_paper_rejects_disabling_stark(self):
        self.assertTrue(options({'self_absorption':False})['stark_broadening'])
        with self.assertRaisesRegex(ValueError,'Stark'): all_options({'model':'paper','stark_broadening':False})

    def test_source_bytes_and_no_stark_json_csv_png_keep_actual_components(self):
        for name in ('nist_lines.py','nist_self_absorption.py'):
            original=Path(__file__).resolve().parents[3]/'simLIBS-2.0.3/simLIBS'/name
            self.assertEqual(original.read_bytes(),(Path(self.s.source)/'simLIBS'/name).read_bytes())
        frames,origin=self.run_model()
        backend=self.backend(frames,origin)
        data=json.loads(backend.export('mixed','json').payload)
        self.assertEqual(len(data['origin']['nist_line_sticks']),4)
        self.assertNotIn('line_diagnostics',data['origin']);self.assertNotIn('opacity',data)
        csv=pd.read_csv(io.StringIO(backend.export('mixed','csv').payload))
        self.assertTrue({'He_corrected','Li_corrected','nominal_thin','matrix_thin'} <= set(csv))
        from matplotlib.figure import Figure
        save=Figure.savefig;labels=[];colors=[]
        def capture(fig,*args,**kw):
            labels.extend(c.get_label() for c in fig.axes[0].collections)
            colors.extend(c.get_colors()[0].tolist() for c in fig.axes[0].collections)
            return save(fig,*args,**kw)
        with patch.object(Figure,'savefig',capture): png=backend.export('mixed','png').payload
        self.assertTrue(png.startswith(b'\x89PNG'));self.assertEqual(labels,['Total','He','Li']);self.assertNotEqual(colors[1],colors[2])
        # Real engine result from invented data, for isolated component/Canvas tests only.
        evidence=Path(os.environ.get('SIMLIBS_TEST_EVIDENCE_DIR', str(self.root)))/'ui-mixed-result.json'
        evidence.write_text(json.dumps({'synthetic_test_fixture':True,'result':data},allow_nan=False),encoding='utf-8')


if __name__=='__main__':unittest.main()
