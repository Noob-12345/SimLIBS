"""NIST 数值身份 -> 组态/项/J -> STARK-B 的严格识别，不依赖邻近波长。"""
from copy import deepcopy
from pathlib import Path
import unittest

from simLIBS import nist_stark
from simLIBS.stark_b import parse_table


FIXTURES = Path(__file__).parent/'fixtures'
TSV = (FIXTURES/'nist_si_ii_identity.tsv').read_text(encoding='utf-8')
HTML = (FIXTURES/'starkb_si_ii_6347.html').read_text(encoding='utf-8')
CMEV = 8065.54393734921


class NISTStarkTests(unittest.TestCase):
    def identities(self):
        return nist_stark.parse_identities(TSV, element='Si', charge=1, cmev=CMEV)

    def line(self):
        return dict(element='Si', charge=1, wavelength_nm=634.886, gA_s=233600000.,
                    lower_eV=65500.47/CMEV, upper_eV=81251.32/CMEV)

    def test_real_ritz_identity_matches_without_air_vacuum_guessing(self):
        rows = self.identities()
        match = nist_stark.identify(self.line(), rows)
        self.assertEqual(match['lower_label'], '3s2.4s 2S 1/2')
        self.assertEqual(match['upper_label'], '3s2.4p 2P* 3/2')
        self.assertEqual(match['nist_lower_id'], '014002.000009')
        bad = dict(self.line(), gA_s=136000000.)
        self.assertIsNone(nist_stark.identify(bad, rows))
        with self.assertRaisesRegex(ValueError, 'Ambiguous NIST'):
            nist_stark.identify(self.line(), rows+rows)

    def test_state_matching_preserves_J_parity_and_parent_terms(self):
        self.assertTrue(nist_stark.same_state('3s2.4p 2Po 3/2', '3s2.4p 2P* 3/2'))
        self.assertFalse(nist_stark.same_state('3s2.4p 2Po 3/2', '3s2.4p 2P* 1/2'))
        self.assertFalse(nist_stark.same_state('3s2.4p 2Po 3/2', '3s2.4p 2P 3/2'))
        self.assertFalse(nist_stark.same_state('3p2.(3P).4p 2Do 3/2', '3p2.(1D).4p 2D* 3/2'))
        # 只有数据库明确不分辨 J 时，才按多重态记录覆盖对应精细结构线。
        self.assertTrue(nist_stark.same_state('3s2.4p 2Po', '3s2.4p 2P* 3/2'))
        self.assertFalse(nist_stark.same_state('3s2.4p 2Po 3/2', '3s2.4p 2P*'))
        # 分隔符和项前缀的排版不同可以统一，母项与前缀本身不删除。
        self.assertTrue(nist_stark.same_state('3d6(5D).4s a6D', '3d6.(5D).4s a 6D 9/2'))
        self.assertTrue(nist_stark.same_state('3s2.4p 2Po 1.5', '3s2.4p 2P* 3/2'))
        self.assertFalse(nist_stark.same_state('3d6(5D).4s a6D', '3d6.(5D).4s b 6D 9/2'))
        for invalid in ['3s2.4p 2P* 1/2,3/2', '3s2.4p 2P* ?', '3s2.4p 2P*', '3s2.4p 2P* 1/3']:
            self.assertFalse(nist_stark.same_state('3s2.4p 2Po', invalid))

    def test_source_matching_uses_states_even_when_database_wave_is_far_away(self):
        table = parse_table(HTML, element='Si', charge=1, dataset_id='223', method='SCP')
        identity = nist_stark.identify(self.line(), self.identities())
        result, reason = nist_stark.match_width(self.line(), identity, table, temperature_k=10000, ne=1e17)
        self.assertEqual(reason, '')
        self.assertAlmostEqual(result['stark_width_nm'], .0965*(634.886/634.7)**2)
        self.assertIn('configuration/term/J', result['stark_match'])
        # 同一多重态的另一条线不能拿明确 J=3/2 的系数冒充 J=1/2。
        result, reason = nist_stark.match_width(dict(self.line(), wavelength_nm=637.313), self.identities()[1],
                                               table, temperature_k=10000, ne=1e17)
        self.assertIsNone(result)
        self.assertIn('state', reason)

    def test_equal_priority_sources_are_ambiguous_and_missing_conditions_explained(self):
        row = parse_table(HTML, element='Si', charge=1, dataset_id='223', method='SCP')[0]
        identity = self.identities()[0]
        with self.assertRaisesRegex(ValueError, 'Ambiguous STARK-B'):
            nist_stark.match_width(self.line(), identity, [row, deepcopy(row)], temperature_k=10000, ne=1e17)
        out, reason = nist_stark.match_width(self.line(), identity, [row], temperature_k=1000, ne=1e17)
        self.assertIsNone(out)
        self.assertIn('temperature', reason)

    def test_invalid_export_does_not_report_no_data(self):
        with self.assertRaisesRegex(ValueError, 'NIST identity'):
            nist_stark.parse_identities('<h1>service error</h1>', element='Si', charge=1, cmev=CMEV)


if __name__ == '__main__':
    unittest.main()
