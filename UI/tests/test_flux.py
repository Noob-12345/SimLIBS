from urllib.parse import parse_qs,urlsplit
from unittest.mock import Mock,patch
import unittest
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings
from simlibs_ui.adapter import simulate,source_module
from tests.test_adapter import HTML,CSV
import pandas as pd


class FluxTests(unittest.TestCase):
    def test_default_is_legacy_photon_and_bad_scale_rejected(self):
        self.assertEqual(getattr(Parameters(),'intensity_scale',None),'photon')
        with self.assertRaises(ValueError):Parameters.from_dict(dict(Parameters().to_dict(),intensity_scale='watts'))

    def test_real_source_static_url_and_provenance_for_both_scales(self):
        for scale,number in [('photon','2'),('energy','1')]:
            with self.subTest(scale=scale):
                p=Parameters.from_dict(dict(Parameters().to_dict(),intensity_scale=scale))
                with patch('requests.get',return_value=Mock(content=HTML)) as get:
                    frames,origin=simulate(p,Settings())
                self.assertEqual(parse_qs(urlsplit(get.call_args.args[0]).query)['int_scale'],[number])
                self.assertEqual(parse_qs(urlsplit(origin['nist_url']).query)['int_scale'],[number])
                self.assertEqual(origin['intensity_scale'],scale)
                self.assertEqual(origin['int_scale'],int(number))
                self.assertEqual(frames['raw']['intensity'].tolist(),[0,2,0],'必须直接解析服务数据，不能后乘总谱')

    def test_dynamic_url_also_uses_selected_scale(self):
        module=source_module(Settings().source)
        driver=Mock();driver.window_handles=['main','csv'];driver.page_source='<pre>'+CSV+'</pre>'
        driver.find_element.return_value.is_displayed.return_value=True
        driver.find_element.return_value.is_enabled.return_value=True
        p=Parameters.from_dict(dict(Parameters().to_dict(),intensity_scale='energy',webscraping='dynamic'))
        with patch('simlibs_ui.adapter.resolve_driver',return_value=('mock.exe','154')),patch.object(module.webdriver,'Chrome',return_value=driver):
            frames,origin=simulate(p,Settings())
        self.assertEqual(parse_qs(urlsplit(driver.get.call_args.args[0]).query)['int_scale'],['1'])
        driver.quit.assert_called_once()

    def test_old_simulation_url_and_unknown_history_scale(self):
        from simlibs_ui.models import intensity_scale_from_origin
        self.assertEqual(intensity_scale_from_origin({'nist_url':'https://example.test/?int_scale=2'}),'photon')
        self.assertEqual(intensity_scale_from_origin({'nist_url':'https://example.test/?int_scale=1'}),'energy')
        self.assertEqual(intensity_scale_from_origin({'kind':'history','parameters':None}),'unknown')

    def test_png_gif_figure_labels_come_from_origin(self):
        from simlibs_ui.plotting import figure_for
        from simlibs_ui.storage import save_result,read_manifest
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            df=pd.DataFrame({'wavelength':[650.,655.,660.],'intensity':[0.,2.,0.]})
            for scale,label in [('photon','Photon flux [a.u.]'),('energy','Energy flux [a.u.]'),('unknown','Intensity [a.u.; scale unknown]')]:
                path=save_result(Path(directory)/scale,{'interpolated':df},{'kind':'history' if scale=='unknown' else 'simulation','intensity_scale':scale})
                figure=figure_for(read_manifest(path),'interpolated','fixture','#ef4444',False)
                self.assertEqual(figure.axes[0].get_ylabel(),label)
                figure.clear()


if __name__=='__main__':unittest.main()
