"""Priority, offline identity, physical domains and FWHM/HWHM regression tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scipy.constants import e, k

from simLIBS import NISTSelfAbsorptionConfig, MissingStarkDataError
from simLIBS.nist_self_absorption import resolve_stark
from simLIBS.nist_stark import parse_identities
from simLIBS.stark_b import parse_table, StarkDataAccessError
from simLIBS.stark_resolver import _atomic_identities
from simLIBS import stark_atomic_data as atomic
from simLIBS.stark_semiempirical import Level, Perturber, calculate_stark_width

FIX = Path(__file__).resolve().parents[3]/'simLIBS-2.0.3'/'tests'/'fixtures'
CMEV = 8065.54393734921


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'stark_broadening.json'
        self.table = parse_table((FIX/'starkb_si_ii_6347.html').read_text(encoding='utf-8'),
                                element='Si', charge=1, dataset_id='223', method='SCP')[0]
        self.line = parse_identities((FIX/'nist_si_ii_identity.tsv').read_text(encoding='utf-8'),
                                    element='Si', charge=1, cmev=CMEV)[0]
        self.config = NISTSelfAbsorptionConfig(stark_database_path=self.path, stark_atomic_dir=self.root,
                                               stark_allow_network=False, stark_cache_dir=self.root/'cache')

    def database(self, tables, complete=True):
        raw = json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        doc = dict(schema_version=1, source='STARK-B', rows=tables,
                   rows_sha256=hashlib.sha256(raw).hexdigest(), manifest=dict(complete=complete, failures=[]))
        self.path.write_text(json.dumps(doc), encoding='utf-8')

    def resolve(self, lines=None, config=None, temperature=10000., ne=1e17):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network used')):
            return resolve_stark(lines or [self.line], config or self.config, te=temperature*k/e, ne=ne, cmev=CMEV)

    def model(self, line):
        return dict(line, atomic_source='synthetic atomic matrix elements for testing only',
                    lower=dict(n_eff=3., l=0, same_n=[dict(delta_e_ev=2., matrix_element_sq_a0=18.)]),
                    upper=dict(n_eff=3., l=1, same_n=[dict(delta_e_ev=2., matrix_element_sq_a0=6.),
                                                    dict(delta_e_ev=2., matrix_element_sq_a0=7.5)]))

    def test_database_priority_offline_and_fwhm_units(self):
        self.database([self.table])
        with patch('simLIBS.stark_resolver._mse_width', side_effect=AssertionError('MSE used before database')):
            row = self.resolve()[0]
        self.assertEqual(row['stark_resolution_layer'], 'STARK-B')
        expected_fwhm = .193*(self.line['wavelength_nm']/634.7)**2
        self.assertAlmostEqual(2*row['stark_width_nm'], expected_fwhm)
        half = self.resolve(ne=5e16)[0]
        self.assertAlmostEqual(half['stark_width_nm'], row['stark_width_nm']/2)
        self.assertEqual(row['stark_collection_manifest']['complete'], True)

    def test_explicit_mse_fallback_and_correct_hwhm_density_scaling(self):
        self.database([])
        line = dict(self.line, element='B', charge=2)  # synthetic identity probe only
        model = self.model(line)
        from dataclasses import replace
        cfg = replace(self.config, stark_mse_inputs=[model])
        row = self.resolve([line], cfg)[0]
        self.assertEqual(row['stark_method'], 'DK1980')
        levels = {name: Level(**dict(model[name], same_n=tuple(Perturber(**p) for p in model[name]['same_n'])))
                  for name in ('lower', 'upper')}
        expected = calculate_stark_width(wavelength_nm=line['wavelength_nm'], temperature_k=10000.,
                    electron_density_cm3=1e17, ion_charge=2, **levels)
        self.assertAlmostEqual(2*row['stark_width_nm'], expected.fwhm_nm)
        self.assertAlmostEqual(self.resolve([line], cfg, ne=2e17)[0]['stark_width_nm'], 2*row['stark_width_nm'])
        self.assertIn('offline', row['stark_b_missing_reason'])

    def test_real_nist_atomic_input_automatically_builds_missing_database_line(self):
        self.database([])
        docs = {name: json.loads((FIX/'nist_live'/f'B_2_{name}_initial.json').read_text(encoding='utf-8'))
                for name in ('levels', 'lines', 'ionization')}
        levels, _ = atomic.parse_nist_levels(docs['levels']['text'])
        lines = atomic.parse_nist_lines(docs['lines']['text'])
        data = dict(levels=levels, lines=lines, ionization_energy_ev=atomic._parse_ie(docs['ionization']['text'], 'B', 2),
                    atomic_source={name+'_sha256': d['sha256'] for name, d in docs.items()})
        (self.root/'B_2_atomic.json').write_text(json.dumps(data), encoding='utf-8')
        table = json.loads((FIX/'starkb_b_iii_first_atomic_ready.json').read_text(encoding='utf-8'))['table']
        identities = _atomic_identities(data, 'B', 2)
        from simLIBS.nist_stark import same_state
        line = next(r for r in identities if same_state(table['lower_label'], r['lower_label'])
                    and same_state(table['upper_label'], r['upper_label']))
        numerical_only = {key: value for key, value in line.items() if not key.endswith('_label')}
        row = self.resolve([numerical_only])[0]
        self.assertEqual(row['stark_atomic_quality'], 'nist-aki-complete')
        self.assertGreater(row['stark_width_nm'], 0)
        self.assertEqual(row['stark_atomic_source'], data['atomic_source'])
        # Incomplete fine-structure array must not be silently interpreted as zero.
        data['lines'] = []
        (self.root/'B_2_atomic.json').write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(MissingStarkDataError):
            self.resolve([line])

    def test_both_layers_missing_keep_reasons_and_skip_policy(self):
        self.database([], complete=False)
        with self.assertRaises(MissingStarkDataError) as raised:
            self.resolve()
        row = raised.exception.missing_lines.iloc[0]
        self.assertIn('incomplete', row.stark_b_missing_reason)
        self.assertIn('q=2 or 3', row.stark_mse_missing_reason)
        from dataclasses import replace
        row = self.resolve(config=replace(self.config, missing_stark='unbroadened'))[0]
        self.assertIsNone(row['stark_width_nm'])
        self.assertIsNone(row['stark_reference_ne_cm3'])
        self.assertTrue(row['stark_missing'])

    def test_no_nearest_wave_or_wrong_state_and_no_temperature_density_extrapolation(self):
        self.database([self.table])
        for line, temp, ne in [(dict(self.line, upper_label='3s2.4p 2P* 1/2'), 10000., 1e17),
                               (self.line, 100., 1e17), (self.line, 10000., 1e20)]:
            with self.subTest(temp=temp, ne=ne), self.assertRaises(MissingStarkDataError):
                self.resolve([line], temperature=temp, ne=ne)

    def test_zero_width_is_kept_but_never_used(self):
        table = deepcopy(self.table)
        for sample in table['samples']:
            sample['fwhm_angstrom'] = 0.
        self.database([table])
        with self.assertRaises(MissingStarkDataError) as raised:
            self.resolve()
        self.assertIn('missing electron width', raised.exception.missing_lines.stark_b_missing_reason.iloc[0])

    def test_corrupt_database_is_access_failure(self):
        self.database([self.table])
        doc = json.loads(self.path.read_text())
        doc['rows'][0]['samples'][0]['fwhm_angstrom'] *= 2
        self.path.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(StarkDataAccessError, 'checksum'):
            self.resolve()

    def test_flagged_negative_source_width_is_preserved_and_unusable(self):
        table = deepcopy(self.table)
        for sample in table['samples']:
            sample.update(fwhm_angstrom=-5.11, flag='nonpositive source electron width')
        self.database([table])
        from simLIBS.stark_resolver import load_database
        self.assertEqual(load_database(self.path)['rows'][0]['samples'][0]['fwhm_angstrom'], -5.11)
        with self.assertRaises(MissingStarkDataError):
            self.resolve()
        for sample in table['samples']:
            sample['flag'] = ''
        self.database([table])
        with self.assertRaisesRegex(StarkDataAccessError, 'nonpositive flag'):
            self.resolve()

    def test_cached_prepared_model_and_manual_override_are_used_after_database_rejection(self):
        table = dict(self.table, element='B', charge=2)
        self.database([table])
        line = dict(self.line, element='B', charge=2)
        model = self.model(line)
        model.update(key=atomic.table_key(table), status='ready', atomic_quality='prepared-test')
        (self.root/'models.json').write_text(json.dumps(dict(schema_version=1, models=[model])), encoding='utf-8')
        row = self.resolve([line], temperature=1000.)[0]
        self.assertEqual(row['stark_method'], 'DK1980')
        self.assertEqual(row['stark_atomic_quality'], 'prepared-test')
        (self.root/'manual_inputs.json').write_text(json.dumps(dict(models=[model])), encoding='utf-8')
        self.assertEqual(self.resolve([line], temperature=1000.)[0]['stark_atomic_quality'], 'manual')

    def test_explicit_model_requires_exact_identity_and_supported_charge(self):
        self.database([])
        from dataclasses import replace
        line = dict(self.line, charge=2)
        cfg = replace(self.config, stark_mse_inputs=[self.model(line)])
        with self.assertRaises(MissingStarkDataError):
            self.resolve([dict(line, gA_s=line['gA_s']*1.001)], cfg)
        for charge in (0, 1, 4):
            probe = dict(line, charge=charge)
            with self.subTest(charge=charge), self.assertRaises(MissingStarkDataError):
                self.resolve([probe], replace(cfg, stark_mse_inputs=[self.model(probe)]))

    def test_offline_numerical_only_line_joins_cached_asd_identity(self):
        self.database([self.table])
        from simLIBS.stark_b import SourceCache
        low, high = self.line['wavelength_nm']-.05, self.line['wavelength_nm']+.05
        key = f'nist-asd-identity-v1:Si:1:{low:.12g}:{high:.12g}'
        SourceCache(self.config.stark_cache_dir).get(key, lambda: dict(
            text=(FIX/'nist_si_ii_identity.tsv').read_text(encoding='utf-8'), url='captured NIST ASD fixture'))
        numerical = {key: value for key, value in self.line.items() if not key.endswith('_label')}
        row = self.resolve([numerical])[0]
        self.assertEqual(row['stark_resolution_layer'], 'STARK-B')
        self.assertEqual(row['nist_lower_id'], self.line['nist_lower_id'])

    def test_database_revision_invalidates_cached_parse(self):
        self.database([self.table])
        first = self.resolve()[0]['stark_width_nm']
        table = deepcopy(self.table)
        for sample in table['samples']:
            sample['fwhm_angstrom'] *= 2
        self.database([table])
        self.assertAlmostEqual(self.resolve()[0]['stark_width_nm'], first*2)


if __name__ == '__main__':
    unittest.main()
