"""Isolated cascade contracts using captured source data, not live results."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.constants import e, k
from simLIBS import NISTSelfAbsorptionConfig, MissingStarkDataError
from simLIBS import stark_resolver as resolver
from simLIBS import stark_atomic_data as atomic
from simLIBS import nist_stark
from simLIBS.stark_b import SourceCache, StarkBClient, StarkDataAccessError, parse_table
from simLIBS.nist_self_absorption import resolve_stark, render_nist_absorption
from simLIBS.stark_semiempirical import Level, Perturber, calculate_stark_width

FIX = Path(__file__).parent/'fixtures'
CMEV = 8065.54393734921


def captured_b():
    docs = {kind: json.loads((FIX/'nist_mse'/('B_2_'+kind+'_initial.json')).read_text(encoding='utf-8'))
            for kind in ('levels', 'lines', 'ionization')}
    levels, _ = atomic.parse_nist_levels(docs['levels']['text'])
    lines = atomic.parse_nist_lines(docs['lines']['text'])
    data = dict(levels=levels, lines=lines, ionization_energy_ev=atomic._parse_ie(docs['ionization']['text'], 'B', 2),
                atomic_source={kind+'_sha256': d['sha256'] for kind, d in docs.items()})
    line = next(row for row in resolver._atomic_identities(data, 'B', 2) if row['wavelength_nm'] == 206.64387)
    return docs, data, line


class CascadeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.database = self.root/'database.json'
        self.config = NISTSelfAbsorptionConfig(stark_database_path=self.database, stark_cache_dir=self.root/'cache',
                                               instrument_broadening=False, wavelength_step_nm=.0002)
        self.si = nist_stark.parse_identities((FIX/'nist_si_ii_identity.tsv').read_text(encoding='utf-8'),
                                               element='Si', charge=1, cmev=CMEV)[0]
        self.table = parse_table((FIX/'starkb_si_ii_6347.html').read_text(encoding='utf-8'),
                                 element='Si', charge=1, dataset_id='223', method='SCP')[0]
        self.empty_species = ([], {'payload': {'status': 'no published electron data', 'datasets': []}})
        self.docs, self.bdata, self.b = captured_b()
        self.write_database([])
        # Any unanticipated external call fails the test instead of reaching the internet.
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('unexpected real network'))
        self.network.start(); self.addCleanup(self.network.stop)

    def write_database(self, rows):
        raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        self.database.write_text(json.dumps(dict(schema_version=1, source='STARK-B', rows=rows,
            rows_sha256=hashlib.sha256(raw).hexdigest(), manifest={'complete': True, 'failures': []})), encoding='utf-8')

    def resolve(self, records, config=None):
        return resolve_stark(records, config or self.config, te=10000*k/e, ne=1e17, cmev=CMEV)

    def atomic_provider(self, session, method, url, **kwargs):
        self.atomic_calls.append((url, kwargs['params']))
        if url == atomic.ASD_LEVELS: return self.docs['levels']['text']
        if url == atomic.ASD_IE: return self.docs['ionization']['text']
        if url == atomic.ASD_LINES: return self.docs['lines']['text']
        raise AssertionError(url)

    def test_json_hit_short_circuits_and_single_fwhm_conversion(self):
        self.write_database([self.table])
        with patch.object(nist_stark, 'resolve_online', side_effect=AssertionError('online called')),\
             patch.object(resolver, 'fetch_atomic_input', side_effect=AssertionError('atomic called')):
            row = self.resolve([self.si])[0]
        self.assertEqual(row['stark_resolution_layer'], 'JSON')
        self.assertAlmostEqual(2*row['stark_width_nm'], .193*(self.si['wavelength_nm']/634.7)**2)
        self.assertEqual(row['stark_reference_ne_cm3'], 1e17)
        self.assertEqual(row['stark_database_sha256'], hashlib.sha256(self.database.read_bytes()).hexdigest())

    def test_json_miss_online_hit_uses_actual_matching_not_mse(self):
        with patch.object(StarkBClient, 'species', return_value=([self.table], {'payload': {}})),\
             patch.object(resolver, 'fetch_atomic_input', side_effect=AssertionError('MSE after online hit')):
            row = self.resolve([self.si])[0]
        self.assertEqual(row['stark_resolution_layer'], 'STARK-B')
        self.assertGreater(row['stark_width_nm'], 0)
        self.assertIn('JSON', row['stark_layer_reasons'])

    def test_json_resolved_indices_are_removed_before_online(self):
        self.write_database([self.table])
        other = dict(self.si, element='Mg', charge=0)
        calls = []
        def species(element, charge, ne): calls.append((element,charge)); return self.empty_species
        with patch.object(StarkBClient, 'species', side_effect=species):
            rows = self.resolve([self.si, other], replace(self.config, missing_stark='unbroadened'))
        self.assertEqual(calls, [('Mg',0)])
        self.assertEqual([r['stark_resolution_layer'] for r in rows], ['JSON','missing'])
        self.assertIn('q=2 or 3', rows[1]['stark_mse_missing_reason'])

    def test_two_misses_fetch_complete_atomic_input_then_real_dk1980_render(self):
        self.atomic_calls=[]; events=[]
        with patch.object(StarkBClient, 'species', return_value=self.empty_species),\
             patch.object(StarkBClient, '_request', self.atomic_provider),\
             patch.object(resolver, 'report_progress', events.append):
            row = self.resolve([self.b])[0]
        self.assertEqual(len(self.atomic_calls),3)
        self.assertEqual(self.atomic_calls[1][1]['low_w'],'')
        self.assertEqual(row['stark_resolution_layer'],'DK1980')
        self.assertEqual(row['stark_atomic_quality'],'nist-aki-complete')
        model=atomic.build_model_input(dict(self.b,dataset_id='probe',calculated_wavelength_angstrom=self.b['wavelength_nm']*10),
            self.bdata['levels'],self.bdata['lines'],self.bdata['ionization_energy_ev'],atomic_source=self.bdata['atomic_source'])
        levels={name:Level(**dict(model[name],same_n=tuple(Perturber(**p) for p in model[name]['same_n']))) for name in ('lower','upper')}
        expected=calculate_stark_width(wavelength_nm=self.b['wavelength_nm'],temperature_k=10000,electron_density_cm3=1e17,ion_charge=2,**levels)
        self.assertAlmostEqual(2*row['stark_width_nm'],expected.fwhm_nm)
        render_row=dict(row,ion='B III',nist_strength=1.,line_id=0)
        result=render_nist_absorption([render_row],{'assumptions':[]},te=10000*k/e,ne=1e17,
            low=206.4,high=206.9,resolution=100000,config=self.config,self_absorption=False)
        self.assertTrue(np.isfinite(result.spectrum.to_numpy()).all())
        self.assertGreater(result.spectrum.intensity.max(),0)
        self.assertAlmostEqual(result.line_diagnostics.thin_fwhm_nm.iloc[0],expected.fwhm_nm)
        self.assertTrue(any('Json抓取：B III' in msg for msg in events))
        self.assertTrue(any('获取完整E1跃迁Aki' in msg for msg in events))
        # Cached full atomic arrays are independently verified and require no fetch.
        with patch.object(StarkBClient,'species',return_value=self.empty_species),\
             patch.object(StarkBClient,'_request',side_effect=AssertionError('cache not used')):
            again=self.resolve([self.b],replace(self.config,stark_allow_network=False))[0]
        self.assertEqual(again['stark_width_nm'],row['stark_width_nm'])

    def test_incomplete_aki_arrays_never_become_zero_or_phi_one(self):
        invalid=deepcopy(self.bdata);invalid['lines']=[]
        with patch.object(StarkBClient,'species',return_value=self.empty_species),patch.object(resolver,'fetch_atomic_input',return_value=invalid):
            with self.assertRaises(MissingStarkDataError):self.resolve([self.b])
            row=self.resolve([self.b],replace(self.config,missing_stark='unbroadened'))[0]
        self.assertTrue(row['stark_missing']);self.assertIsNone(row['stark_width_nm'])
        self.assertIn('identity',row['stark_mse_missing_reason'])

    def test_access_fault_not_physical_missing_but_valid_alternative_keeps_evidence(self):
        error=StarkDataAccessError('TLS verification failed');error.code='stark_network'
        with patch.object(nist_stark,'resolve_online',side_effect=error):
            with self.assertRaises(StarkDataAccessError):self.resolve([self.si],replace(self.config,missing_stark='unbroadened'))
        with patch.object(nist_stark,'resolve_online',side_effect=error),patch.object(resolver,'fetch_atomic_input',return_value=self.bdata):
            row=self.resolve([self.b])[0]
        self.assertEqual(row['stark_resolution_layer'],'DK1980')
        self.assertEqual(row['stark_access_failures'][0]['code'],'stark_network')

    def test_wrong_identity_conditions_and_zero_width_not_accepted(self):
        self.write_database([self.table])
        with patch.object(StarkBClient,'species',return_value=self.empty_species):
            for line in [dict(self.si,upper_label='3s2.4p 2P* 1/2'),dict(self.si,gA_s=self.si['gA_s']*1.01)]:
                # Numerical identity with fabricated gA alone is not a test of the
                # source labels; different state and physical applicability are.
                if line['upper_label']==self.si['upper_label']:continue
                with self.assertRaises(MissingStarkDataError):self.resolve([line])
        table=deepcopy(self.table)
        for sample in table['samples']:sample.update(fwhm_angstrom=0,flag='nonpositive source electron width')
        self.write_database([table])
        with patch.object(StarkBClient,'species',return_value=self.empty_species):
            with self.assertRaises(MissingStarkDataError):self.resolve([self.si])

    def test_corrupt_json_and_atomic_cache_fail_loudly(self):
        self.write_database([self.table]);doc=json.loads(self.database.read_text());doc['rows'][0]['samples'][0]['fwhm_angstrom']*=2
        self.database.write_text(json.dumps(doc))
        with self.assertRaisesRegex(StarkDataAccessError,'checksum'):self.resolve([self.si])
        self.write_database([]);self.atomic_calls=[]
        with patch.object(StarkBClient,'species',return_value=self.empty_species),patch.object(StarkBClient,'_request',self.atomic_provider):self.resolve([self.b])
        cache_file=next((self.root/'cache').glob('*.json'));doc=json.loads(cache_file.read_text());doc['sha256']='0'*64;cache_file.write_text(json.dumps(doc))
        with patch.object(StarkBClient,'species',return_value=self.empty_species):
            with self.assertRaises(StarkDataAccessError):self.resolve([self.b])

    def test_cancel_before_layers_and_actual_charge_domain(self):
        with patch.object(resolver,'check_cancelled',return_value=True):
            with self.assertRaises(InterruptedError):self.resolve([self.si])
        for q in (0,1,4):
            line=dict(self.b,charge=q)
            with patch.object(StarkBClient,'species',return_value=self.empty_species),patch.object(resolver,'fetch_atomic_input',side_effect=AssertionError('unsupported species requested')):
                row=self.resolve([line],replace(self.config,missing_stark='unbroadened'))[0]
            self.assertTrue(row['stark_missing'])

    def test_bundled_file_is_fixed_complete_export_not_sibling_discovery(self):
        database=resolver.load_database()
        self.assertEqual(database['file_sha256'],'f40995bbb87ffeedb069d29e8e42c7fa6e64d939ceaceeb19fe902b7185f5a54')
        self.assertEqual(len(database['rows']),11819)
        self.assertTrue(database['manifest']['complete'])
        self.assertEqual(resolver.default_database_path().parent.name,'data')


if __name__=='__main__':unittest.main()
