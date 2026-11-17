"""Offline source/official PyWavelets crosscheck; reference-env is test-only."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
import numpy as np
from simlibs_ui.spectrum_cwt import cwt
from simlibs_ui.spectrum_processing import background,ridge_peaks,process,parameters

REF=Path(os.environ.get('SIMLIBS_PROCESS_REFERENCES',Path(__file__).parents[2]/'.ai-workflow/20261117-spectrum-browser'))
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class Processing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (REF/'reference-env/site/pywt').exists() or not (REF/'references/source-peakfilling.py').exists():
            raise unittest.SkipTest('Set SIMLIBS_PROCESS_REFERENCES to task evidence with source snapshots and PyWavelets 1.8.0 reference-env (not a runtime dependency)')
        sys.path.insert(0,str(REF/'reference-env/site'));import pywt
        cls.pywt=pywt
        # Compatibility only in this test process; source and shared env unchanged.
        np.trapz=np.trapezoid
        cls.original=load('original_background',REF/'references/source-peakfilling.py')
        cls.peaks=load('original_peaks',REF/'references/source-Wavelet_peakfinding.py')

    def test_background_matches_source_negative_edges_area_and_nonuniform_axis(self):
        for y in [np.array([-2.,-1.,-2.]),np.array([-1.,2.,-3.]),np.arange(33.)-14,np.ones(33),np.sin(np.arange(129.)/5)*100-30]:
            x=np.cumsum(np.linspace(.1,.4,len(y)));order=min(6,(len(y)-1)//2)
            before=y.copy();actual,h=background(y,x,order,1e-4,1000)
            expected,eh=self.original.alternating_peak_stripping(y,x,order,1e-4,1000,True)
            np.testing.assert_array_equal(actual,expected);self.assertEqual(h,eh);np.testing.assert_array_equal(before,y)
        actual,h=background(np.array([-2.,-1.,-2.]),np.arange(3.),1,1e-4,1000)
        np.testing.assert_array_equal(actual,[-1,-2,-1]);self.assertEqual(len(h),1)

    def test_all_four_cwt_arrays_and_complete_peak_indices_match_source(self):
        rng=np.random.default_rng(7);x=np.linspace(200,500,1024)
        signals=[np.full(1024,-3.),rng.normal(size=1024)*3,1000*np.exp(-((x-280)/2)**2)+700*np.exp(-((x-400)/4)**2)-40]
        for wave in ('mexh','morl','gaus1','gaus2'):
            for signal in signals:
                scales=list(range(1,8));actual=cwt(signal,scales,wave);expected,_=self.pywt.cwt(signal,scales,wave)
                np.testing.assert_allclose(actual,expected,rtol=2e-11,atol=2e-10)
                indices,_=ridge_peaks(signal,actual,2,2,200,3)
                original,_,_=self.peaks.wavelet_peak_detection(signal,x,wave,scales,2,2,200,3)
                self.assertEqual(indices,original)

    def test_product_bounds_zero_peaks_input_preserved_and_both_order(self):
        x=np.linspace(1,100,1000);y=500*np.exp(-((x-60)/1.5)**2)-3
        document=dict(xs=x.tolist(),sha256='layout-fixture',unit='pixel',curves=[dict(id='raw',ys=y.tolist())],provenance=dict(selection={'frame':'fixture'}))
        original=list(document['curves'][0]['ys']);result=process(document,'raw',{'mode':'both','max_iter':1000})
        expected_bg=self.original.alternating_peak_stripping(y,x);np.testing.assert_array_equal(result['background'],expected_bg)
        expected,_,_=self.peaks.wavelet_peak_detection(y-expected_bg,x,'mexh',range(1,8),2,2,200,3)
        self.assertEqual([p['index'] for p in result['peaks']],expected);self.assertEqual(document['curves'][0]['ys'],original)
        flat={**document,'curves':[dict(id='raw',ys=[0.]*1000)]};self.assertEqual(process(flat,'raw',{'mode':'peaks'})['peaks'],[])
        with self.assertRaises(ValueError):process({**document,'xs':[1.]*1000},'raw',{})
        for options in ({'order':True},{'max_iter':999999},{'scales':[0]},{'threshold':float('nan')},{'wavelet':'unknown'}):
            with self.assertRaises(ValueError):parameters(options,1000)
        with self.assertRaises(ValueError):parameters({'max_iter':5000},100000)

    def test_nonfinite_intermediates_rejected_and_unused_parameters_ignored(self):
        with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
            with self.assertRaisesRegex(ValueError,'溢出'):background(np.full(33,1e308),np.arange(33.),6,1e-4,10)
            with self.assertRaisesRegex(ValueError,'CWT'):cwt(np.full(100,1e308),[1,7],'gaus1')
        p=parameters({'mode':'background','wavelet':'invalid','scales':[0],'min_length':999,'threshold':float('nan')},100)
        self.assertEqual(p['mode'],'background')
        p=parameters({'mode':'peaks','order':'invalid','max_iter':-1,'epsilon':float('nan')},100)
        self.assertEqual(p['mode'],'peaks')


if __name__=='__main__':unittest.main()
