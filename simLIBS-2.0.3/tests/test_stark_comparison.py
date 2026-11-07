"""Offline comparison tests. Written on request; NOT executed in this task."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def synthetic_table():
    return dict(element='C', charge=2, dataset_id='synthetic-only', method='SCP',
                lower_label='3s 2S', upper_label='3p 2Po',
                calculated_wavelength_angstrom=5000., source='synthetic fixture, not a publication',
                source_ids=['test'], source_url='https://example.invalid/test', c_angstrom_cm3=None,
                samples=[dict(temperature_k=10000., ne=1e17, fwhm_angstrom=1., flag='')])


def synthetic_model(table):
    from stark_atomic_data import table_key
    return dict(key=table_key(table), status='ready', atomic_quality='synthetic-test-only',
                atomic_source='test only', lower=dict(n_eff=3., l=0, same_n=[
                    dict(delta_e_ev=2., matrix_element_sq_a0=18.)]),
                upper=dict(n_eff=3., l=1, same_n=[dict(delta_e_ev=2., matrix_element_sq_a0=6.),
                                                dict(delta_e_ev=2., matrix_element_sq_a0=7.5)]))


class AtomicPreparationTests(unittest.TestCase):
    def test_complete_aki_arrays_build_model_without_phi_guess(self):
        from stark_atomic_data import build_model_input
        # Artificial complete 3s/3p/3d doublet terms, not atomic measurements.
        levels = []
        for config, term, energy, js in [('3s', '2S', 0., ('1/2',)),
                                         ('3p', '2P*', 2., ('1/2', '3/2')),
                                         ('3d', '2D', 3., ('3/2', '5/2'))]:
            levels.extend(dict(configuration=config, term=term, energy_ev=energy, j=j) for j in js)
        lines = []
        for a, b in [(levels[0], levels[1]), (levels[0], levels[2]),
                     (levels[1], levels[3]), (levels[2], levels[3]), (levels[2], levels[4])]:
            lines.append(dict(lower_configuration=a['configuration'], lower_term=a['term'],
                              lower_j=a['j'], lower_energy_ev=a['energy_ev'],
                              upper_configuration=b['configuration'], upper_term=b['term'],
                              upper_j=b['j'], upper_energy_ev=b['energy_ev'], line_strength_a0_sq=6.))
        model = build_model_input(synthetic_table(), levels, lines, 20., atomic_source='synthetic test')
        self.assertEqual(model['status'], 'ready')
        self.assertEqual(len(model['lower']['same_n']), 1)
        self.assertEqual(len(model['upper']['same_n']), 2)
        self.assertAlmostEqual(model['lower']['same_n'][0]['matrix_element_sq_a0'], 6.)
        # Removing an allowed fine-structure component must reject the array.
        with self.assertRaises(ValueError):
            build_model_input(synthetic_table(), levels, lines[:-1], 20., atomic_source='synthetic test')

    def test_key_reuses_atomic_input_across_reference_densities(self):
        from stark_atomic_data import table_key
        table = synthetic_table()
        key = table_key(table)
        table['samples'][0]['ne'] = 1e16
        self.assertEqual(table_key(table), key)
        table['source_ids'] = ['different-paper']
        self.assertNotEqual(table_key(table), key)

    def test_nist_energy_units_and_aki_line_strength(self):
        from stark_atomic_data import parse_nist_levels, parse_nist_lines
        text = 'Configuration\tTerm\tJ\tLevel (cm-1)\n"3s"\t"2S"\t"1/2"\t"[10000.0]"\n'
        rows, limits = parse_nist_levels(text)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]['energy_ev'], 10000/8065.54393734921)
        self.assertEqual(limits, [])
        lines = ('ritz_wl_vac(nm)\tAki(s^-1)\tEi(cm-1)\tEk(cm-1)\tconf_i\tterm_i\tJ_i'
                 '\tconf_k\tterm_k\tJ_k\tg_i\tg_k\tType\n'
                 '500\t1e8\t0\t20000\t3s\t2S\t1/2\t3p\t2P*\t3/2\t2\t4\t\n')
        rows = parse_nist_lines(lines)
        self.assertAlmostEqual(rows[0]['line_strength_a0_sq'], 1e8*4*5000**3/2.02613e18)
        with self.assertRaises(ValueError):
            parse_nist_lines(lines.replace('\tType', ''))

    def test_filled_core_orbital_does_not_require_impossible_array(self):
        from stark_atomic_data import build_model_input
        core = '1s2.2s2.2p6.3s2.3p6'
        levels = []
        for orbital, term, energy, js in [('3d', '2D', 0., ('3/2', '5/2')),
                                         ('3f', '2F*', 1., ('5/2', '7/2'))]:
            levels.extend(dict(configuration=core+'.'+orbital, term=term, energy_ev=energy, j=j) for j in js)
        # 3f is physically impossible (n<=l), so no fake array may be constructed.
        table = synthetic_table()
        table.update(lower_label=core+'.3d 2D', upper_label=core+'.3d 2D')
        with self.assertRaisesRegex(ValueError, 'No resolvable same-n'):
            build_model_input(table, levels, [], 20., atomic_source='synthetic test')

    def test_rejects_html_and_open_core(self):
        from stark_atomic_data import parse_nist_levels, valence_configuration
        with self.assertRaises(ValueError):
            parse_nist_levels('<html>Server error</html>')
        self.assertEqual(valence_configuration('1s2.2s2.3p'), ('1s2.2s2', 3, 1))
        for config in ('3d6.4s', '3s2.3p2', '3p?', '3d(2D)4s'):
            with self.subTest(config=config), self.assertRaises(ValueError):
                valence_configuration(config)

    def test_source_is_required_for_manual_inputs(self):
        from stark_atomic_data import load_model_inputs
        with tempfile.TemporaryDirectory() as folder:
            manual = synthetic_model(synthetic_table())
            candidate = dict(key=manual['key'], status='missing', reason='test candidate')
            Path(folder, 'models.json').write_text(
                json.dumps(dict(schema_version=1, models=[candidate])), encoding='utf-8')
            manual.pop('atomic_source')
            Path(folder, 'manual_inputs.json').write_text(json.dumps(dict(models=[manual])), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'atomic_source'):
                load_model_inputs(folder)


class ComparisonTests(unittest.TestCase):
    def test_cli_can_request_bounded_download_concurrency(self):
        from stark_semiempirical_check import _parser, _options
        args = _options(_parser().parse_args(['fetch-stark', '--workers', '4']))
        self.assertEqual(args.workers, 4)

    def compare(self, table=None):
        from stark_semiempirical_check import compare_tables
        table = table or synthetic_table()
        model = synthetic_model(table)
        return compare_tables([table], {model['key']: model})

    def test_fwhm_convention_and_independent_error(self):
        rows, skipped = self.compare()
        self.assertFalse(skipped)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row['ratio'], 1.058029807901368, places=11)
        self.assertAlmostEqual(row['signed_relative_error_percent'], 5.8029807901368, places=10)

    def test_flagged_and_unsupported_points_are_not_silently_used(self):
        table = synthetic_table()
        table['samples'][0]['flag'] = '*'
        rows, skipped = self.compare(table)
        self.assertFalse(rows)
        self.assertTrue(skipped)
        table['charge'] = 1
        table['samples'][0]['flag'] = ''
        rows, skipped = self.compare(table)
        self.assertFalse(rows)
        self.assertTrue(skipped)

    def test_repeated_points_do_not_inflate_unique_line_count(self):
        from stark_semiempirical_check import summarize
        rows, skipped = self.compare()
        summary = summarize(rows+rows, skipped)
        self.assertEqual(summary['overall']['point_weighted']['point_count'], 2)
        self.assertEqual(summary['overall']['point_weighted']['unique_line_count'], 1)
        self.assertEqual(summary['overall']['line_balanced']['unique_line_count'], 1)

    def test_empty_data_still_produces_machine_readable_report(self):
        from stark_semiempirical_check import write_outputs
        with tempfile.TemporaryDirectory() as folder:
            write_outputs([], [], folder)
            self.assertTrue(Path(folder, 'summary.json').exists())
            self.assertTrue(Path(folder, 'report.md').exists())
            self.assertFalse(Path(folder, 'comparison.png').exists())


class CollectorTests(unittest.TestCase):
    def test_discovery_reads_atoms_not_collision_particles(self):
        import stark_data_collect as collector
        client = collector._client()
        xml = (ROOT/'tests/fixtures/starkb_si_ii_6347.xsams.xml').read_text(encoding='utf-8')
        page = dict(xml=xml, headers={'VAMDC-TRUNCATED': 'None'}, url=client.TAP_URL)
        species = collector._species_from_page(client, page)
        self.assertIn(dict(element='Si', charge=1), species)
        self.assertNotIn(dict(element='H', charge=1), species)
        page['headers']['VAMDC-TRUNCATED'] = '50%'
        with self.assertRaises(ValueError):
            collector._species_from_page(client, page)


if __name__ == '__main__':
    unittest.main()
