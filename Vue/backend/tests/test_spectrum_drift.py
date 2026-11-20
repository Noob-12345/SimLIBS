import numpy as np
import unittest

from simlibs_ui.spectrum_drift import fit_drift_correction, match_peaks_to_reference
from simlibs_ui.spectrum_processing import parameters, process


class DriftModelTests(unittest.TestCase):
    def test_linear_fit_for_two_lines(self):
        model=fit_drift_correction([150.,300.],[151.5,302.25],max_degree=3)
        self.assertEqual((model.degree,model.n_line),(1,2))
        np.testing.assert_allclose(model.correct([150.]),[151.5],rtol=1e-12)

    def test_quadratic_fit_across_three_lines(self):
        exp=[100.,300.,200.]
        theo=[0.01*e*e-2*e+400 for e in exp]
        model=fit_drift_correction(exp,theo,max_degree=3)
        self.assertEqual(model.degree,2)
        self.assertEqual(list(model.exp_wl),sorted(exp))
        np.testing.assert_allclose(model.correct([150.,250.]),[0.01*150**2-2*150+400,0.01*250**2-2*250+400],rtol=1e-9)

    def test_caps_fit_degree_at_requested_max(self):
        exp=[100.,150.,200.,250.,300.]
        theo=[2*((e-100)/50)**3+0.5*e for e in exp]
        model=fit_drift_correction(exp,theo,max_degree=3)
        self.assertEqual(model.degree,3)
        np.testing.assert_allclose(model.correct(exp),theo,rtol=1e-9)

    def test_rejects_too_few_matched_lines(self):
        with self.assertRaisesRegex(ValueError,'少于2'):
            fit_drift_correction([100.],[101.],max_degree=3)

    def test_rejects_mismatched_lengths(self):
        with self.assertRaisesRegex(ValueError,'数量不一致'):
            fit_drift_correction([100.,200.],[101.],max_degree=3)

    def test_nonfinite_pairs_filtered(self):
        model=fit_drift_correction([100.,float('nan'),200.],[101.,50.,202.],max_degree=3)
        self.assertEqual(model.n_line,2)

    def test_matching_greedy_one_to_one_and_tolerance(self):
        exp,theo=match_peaks_to_reference([400.3,500.2],[400.0,400.4,500.0],0.5)
        np.testing.assert_allclose(exp,[400.3,500.2])
        np.testing.assert_allclose(theo,[400.4,500.0])
        exp0,theo0=match_peaks_to_reference([400.9],[400.0],0.5)
        self.assertEqual((len(exp0),len(theo0)),(0,0))

    def test_matching_rejects_bad_input(self):
        with self.assertRaisesRegex(ValueError,'非有限'):
            match_peaks_to_reference([float('nan')],[400.],0.5)
        with self.assertRaisesRegex(ValueError,'容差'):
            match_peaks_to_reference([400.],[400.],-1)


class DriftProcessTests(unittest.TestCase):
    def document(self):
        xs=np.arange(300.,600.05,0.05)
        y=np.zeros_like(xs)
        for center in (400.4,500.2,550.0):
            y=y+1000.*np.exp(-0.5*((xs-center)/0.3)**2)
        return dict(name='drift.csv',format='CSV',sha256='a'*64,unit='nm',xs=xs.tolist(),
            curves=[dict(id='0: int',label='0: int',ys=y.tolist())],nodes=len(xs),
            provenance=dict(selection=dict(sheet=0,start=2,x_column=0,y_columns=[1])))

    def test_drift_process_matches_fits_and_corrects_axis(self):
        doc=self.document()
        result=process(doc,'0: int',dict(mode='both',drift_correction=True,max_degree=1,tolerance=0.5),[400.,500.,550.])
        self.assertIsNotNone(result['drift_model'])
        self.assertEqual(result['drift_model']['matched_line_count'],3)
        self.assertEqual(result['drift_model']['degree'],1)
        self.assertEqual(len(result['drift_model']['coefficients']),2)
        self.assertEqual(len(result['corrected_xs']),len(doc['xs']))
        for peak in result['peaks']:
            self.assertIn('corrected_x',peak)
        self.assertIn('drift_correction',result['source_hashes'])

    def test_drift_off_keeps_schema_unchanged(self):
        doc=self.document()
        plain=process(doc,'0: int',dict(mode='both'))
        self.assertIsNone(plain['drift_model'])
        self.assertIsNone(plain['corrected_xs'])
        self.assertNotIn('corrected_x',plain['peaks'][0])

    def test_drift_rejects_pixel_axis_and_missing_reference(self):
        doc=self.document();doc['unit']='pixel'
        with self.assertRaisesRegex(ValueError,'nm轴'):
            process(doc,'0: int',dict(mode='both',drift_correction=True),[400.,500.])
        with self.assertRaisesRegex(ValueError,'参考谱线位置'):
            process(self.document(),'0: int',dict(mode='both',drift_correction=True),None)

    def test_drift_parameters_ignored_when_off_and_validated_when_on(self):
        self.assertEqual(parameters(dict(mode='both',max_degree=99),100)['max_degree'],3)
        with self.assertRaisesRegex(ValueError,'max_degree'):
            parameters(dict(mode='both',drift_correction=True,max_degree=99),100)
        with self.assertRaisesRegex(ValueError,'tolerance'):
            parameters(dict(mode='both',drift_correction=True,tolerance=50),100)
        p=parameters(dict(mode='both',drift_correction=True),100)
        self.assertEqual((p['max_degree'],p['tolerance'],p['drift_correction']),(3,0.5,True))


if __name__=='__main__':
    unittest.main()
