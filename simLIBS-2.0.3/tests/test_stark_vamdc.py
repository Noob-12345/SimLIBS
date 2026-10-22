"""Offline contract tests; the XSAMS fixture is an unedited official response."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import requests
from simLIBS.nist_stark import match_width

try:
    from simLIBS import stark_vamdc
except ImportError:
    stark_vamdc = None


XML = (Path(__file__).parent / 'fixtures' / 'starkb_si_ii_6347.xsams.xml').read_text(encoding='utf-8')
NS = {'x': 'http://vamdc.org/xml/xsams/1.0'}
URL = 'https://stark-b.obspm.fr/12.07/vamdc/tap/sync'


def payload(xml=XML):
    return {'format': 'vamdc-xsams', 'datasets': [], 'status': 'ok',
            'pages': [{'xml': xml, 'url': URL}]}


def edited(edit):
    root = ET.fromstring(XML)
    edit(root)
    return ET.tostring(root, encoding='unicode')


def response(xml=XML, *, status=200, truncated='None'):
    out = requests.Response()
    out.status_code = status
    out._content = xml.encode('utf-8')
    out.url = URL
    out.headers['Content-Type'] = 'text/xml'
    if truncated is not None:
        out.headers['VAMDC-TRUNCATED'] = truncated
    return out


class VamdcTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(stark_vamdc, 'stark_vamdc implementation is not present yet')

    def rows(self, xml=XML, ne=1e17):
        return stark_vamdc.parse_payload(payload(xml), element='Si', charge=1, ne=ne)

    def test_real_fwhm_and_quantum_identity(self):
        row, = self.rows()
        self.assertEqual(row['lower_label'], '3s2.4s 2S 1/2')
        self.assertEqual(row['upper_label'], '3s2.4p 2Po 3/2')
        self.assertEqual(row['calculated_wavelength_angstrom'], 6347.)
        self.assertEqual([s['fwhm_angstrom'] for s in row['samples']], [2.74, 1.93, 1.44, 1.19])
        self.assertEqual([s['temperature_k'] for s in row['samples']], [5000., 10000., 20000., 40000.])
        self.assertTrue(all(s['ne'] == 1e17 and not s['flag'] for s in row['samples']))
        self.assertEqual(row['method'], 'unreported')
        self.assertIsNone(row['c_angstrom_cm3'])
        self.assertIsNone(row['fit'])
        self.assertEqual(row['temperature_interpolation'], 'linear')
        self.assertEqual(row['source_format'], 'vamdc-xsams')
        self.assertIn('Stark broadening of visible SI II lines', row['source'])
        self.assertIn('1977PhRvA..16.1617L', row['source'])
        self.assertEqual(row['source_url'], URL)
        json.dumps(row, allow_nan=False)

    def test_no_high_density_extrapolation_and_no_reference_relabel(self):
        self.assertEqual(self.rows(ne=1e18), [])
        self.assertTrue(all(s['ne'] == 1e17 for s in self.rows(ne=1e16)[0]['samples']))

    def test_covering_densities_are_preserved_for_temperature_aware_selection(self):
        def add_density(root):
            envs = root.find('x:Environments', NS)
            tr = root.find('.//x:RadiativeTransition', NS)
            for env in list(envs):
                clone = copy.deepcopy(env)
                clone.set('envID', env.get('envID') + '-low')
                clone.find('x:TotalNumberDensity/x:Value', NS).text = '1e16'
                envs.append(clone)
            for br in list(tr.findall('x:Broadening', NS)):
                clone = copy.deepcopy(br)
                clone.set('envRef', br.get('envRef') + '-low')
                tr.append(clone)
        xml = edited(add_density)
        self.assertEqual([row['samples'][0]['ne'] for row in self.rows(xml, ne=1e15)], [1e16, 1e17])
        self.assertTrue(all(s['ne'] == 1e17 for s in self.rows(xml, ne=2e16)[0]['samples']))

    def test_validity_comments_become_flags(self):
        def warn(root):
            parameter = root.find('.//x:LineshapeParameter', NS)
            ET.SubElement(parameter, '{%s}Comments' % NS['x']).text = '0.1 < NV <= 0.5'
        self.assertEqual(self.rows(edited(warn))[0]['samples'][0]['flag'], '0.1 < NV <= 0.5')

    def test_density_selection_uses_a_table_that_covers_the_target_temperature(self):
        def add_low_density(root):
            envs = root.find('x:Environments', NS)
            low_env = copy.deepcopy(envs[0])
            low_env.set('envID', 'low-density-only-5000K')
            low_env.find('x:TotalNumberDensity/x:Value', NS).text = '1e16'
            envs.append(low_env)
            transition = root.find('.//x:RadiativeTransition', NS)
            low_width = copy.deepcopy(transition.find('x:Broadening', NS))
            low_width.set('envRef', low_env.get('envID'))
            low_width.find('x:Lineshape/x:LineshapeParameter/x:Value', NS).text = '0.274'
            transition.append(low_width)
        rows = self.rows(edited(add_low_density), ne=1e15)
        line = dict(element='Si', charge=1, wavelength_nm=634.886)
        identity = dict(lower_label='3s2.4s 2S 1/2', upper_label='3s2.4p 2P* 3/2')
        for temperature, expected_reference in ((10000, 1e17), (7500, 1e17), (5000, 1e16)):
            with self.subTest(temperature=temperature):
                out, reason = match_width(line, identity, rows, temperature_k=temperature, ne=1e15)
                self.assertIsNotNone(out, reason)
                self.assertEqual(out['stark_table_reference_ne_cm3'], expected_reference)

    def test_duplicate_transition_is_not_chosen(self):
        def duplicate(root):
            parent = root.find('x:Processes/x:Radiative', NS)
            parent.append(copy.deepcopy(parent[0]))
        with self.assertRaisesRegex(ValueError, 'duplicate|ambiguous|Ambiguous'):
            self.rows(edited(duplicate))

    def test_distinct_sources_with_same_states_remain_distinct_candidates(self):
        def duplicate(root):
            parent = root.find('x:Processes/x:Radiative', NS)
            clone = copy.deepcopy(parent[0])
            clone.set('id', 'different-source-transition')
            parent.append(clone)
        self.assertEqual(len(self.rows(edited(duplicate))), 2)

    def test_multiple_state_components_are_ambiguous(self):
        def duplicate(root):
            composition = root.find('.//x:AtomicComposition', NS)
            composition.append(copy.deepcopy(composition[0]))
        with self.assertRaisesRegex(ValueError, 'state|component|Ambiguous'):
            self.rows(edited(duplicate))

    def test_bad_units_and_dangling_environment_are_errors(self):
        for old, new in [('units="A"', 'units="nm"'), ('units="K"', 'units="eV"'),
                         ('units="1/cm3"', 'units="1/m3"'),
                         ('envRef="Estarkb-200176"', 'envRef="missing"')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.rows(XML.replace(old, new))

    def test_bad_xml_html_entities_and_nonfinite_values_are_errors(self):
        for xml in ['<broken', '<html>502</html>', XML.replace('2.74', 'NaN'),
                    '<!DOCTYPE x [<!ENTITY n "unsafe">]>' + XML]:
            with self.subTest(xml=xml[:35]), self.assertRaises(ValueError):
                self.rows(xml)

    def test_fetch_preserves_raw_xml_and_json_serializable_metadata(self):
        with patch('requests.get', return_value=response()) as get:
            out = stark_vamdc.fetch_species('Si', 1, 1e17)
        self.assertEqual(out['pages'][0]['xml'], XML)
        self.assertEqual(out['datasets'], [])
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(get.call_args[0][0], URL)
        self.assertIn("AtomSymbol = 'Si'", get.call_args[1]['params']['QUERY'])
        self.assertIn('EnvironmentTotalNumberDensity >= 1e+17', get.call_args[1]['params']['QUERY'])
        json.dumps(out, allow_nan=False)

    def test_204_is_explicit_no_data(self):
        with patch('requests.get', return_value=response('', status=204)):
            out = stark_vamdc.fetch_species('Si', 1, 1e17)
        self.assertEqual(out['status'], 'no data')
        self.assertEqual(out['pages'], [])
        self.assertEqual(stark_vamdc.parse_payload(out, element='Si', charge=1, ne=1e17), [])

    def test_fetch_reports_density_coverage_without_changing_raw_page(self):
        with patch('requests.get', return_value=response()):
            out = stark_vamdc.fetch_species('Si', 1, 1e18)
        self.assertEqual(out['status'], 'density above available tables')
        self.assertEqual(out['pages'][0]['xml'], XML)

    def test_recursive_splitting_and_empty_branch_still_cover_the_domain(self):
        # First separate the unbounded tail, then bisect the bounded left side.
        early = XML.replace('6347.0', '2000.0').replace('Pstarkb-R5252', 'Pstarkb-R2000')
        calls = []
        def get(url, **kwargs):
            query = kwargs['params']['QUERY']
            calls.append(query)
            if len(calls) in (1, 2):
                return response(truncated='50')
            if len(calls) == 3:
                return response(early)
            if len(calls) == 4:
                return response(XML)
            return response('', status=204)
        with patch('requests.get', side_effect=get):
            out = stark_vamdc.fetch_species('Si', 1, 1e17)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len(out['pages']), 2)
        self.assertEqual(len(stark_vamdc.parse_payload(out, element='Si', charge=1, ne=1e17)), 2)

    def test_truncation_splits_the_full_domain_without_caching_partial_page(self):
        other = XML.replace('6347.0', '7000.0').replace('Pstarkb-R5252', 'Pstarkb-R7000')
        calls = []
        def get(url, **kwargs):
            query = kwargs['params']['QUERY']
            calls.append(query)
            if len(calls) == 1:
                return response(truncated='50.0')
            return response(XML if '<=' in query else other)
        with patch('requests.get', side_effect=get):
            out = stark_vamdc.fetch_species('Si', 1, 1e17)
        self.assertEqual(len(out['pages']), 2)
        self.assertEqual(len(calls), 3)
        self.assertIn('RadTransWavelength <=', calls[1])
        self.assertRegex(calls[2], r'RadTransWavelength >\s*6347')
        self.assertEqual(len(stark_vamdc.parse_payload(out, element='Si', charge=1, ne=1e17)), 2)

    def test_truncation_that_cannot_be_completed_is_an_error(self):
        with patch('requests.get', return_value=response(truncated='50')), \
             patch.object(stark_vamdc, '_MAX_DEPTH', 2), self.assertRaises(ValueError):
            stark_vamdc.fetch_species('Si', 1, 1e17)

    def test_fetch_validates_complete_xml_before_cache_can_receive_it(self):
        for bad in [response('<html>502</html>'), response(XML.replace('2.74', 'NaN')),
                    response(XML.replace('units="A"', 'units="nm"')), response(truncated=None)]:
            with self.subTest(body=bad.content[:30]), patch('requests.get', return_value=bad), \
                 self.assertRaises(ValueError):
                stark_vamdc.fetch_species('Si', 1, 1e17)

    def test_http_errors_are_propagated(self):
        with patch('requests.get', return_value=response('bad gateway', status=502)), \
             self.assertRaises(requests.HTTPError):
            stark_vamdc.fetch_species('Si', 1, 1e17)

    def test_invalid_species_conditions_are_rejected_without_network(self):
        for args in [('Si OR 1=1', 1, 1e17), ('Si', -1, 1e17), ('Si', 1, float('inf'))]:
            with self.subTest(args=args), patch('requests.get') as get, self.assertRaises(ValueError):
                stark_vamdc.fetch_species(*args)
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
