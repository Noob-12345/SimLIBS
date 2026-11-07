"""Offline integration between the real collector export and runtime loader."""
import importlib.util
import json
from pathlib import Path
import unittest

from simLIBS.stark_b import StarkDataAccessError
from simLIBS.stark_resolver import load_database


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    '_stark_export_runtime_fixtures', ROOT / 'tests/test_stark_data_collect.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class ExportRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the existing offline service and temporary cache setup.
        # Export and runtime validation both execute their production code; the
        # test never manufactures its own rows digest or disables validation.
        self.collection = fixtures.StarkDataCollectTests()
        self.addCleanup(self.collection.doCleanups)
        self.collection.setUp()
        self.collection.fetch()
        self.output = self.collection.directory / 'stark_broadening.json'
        self.collection.collector.export_stark_database(
            self.collection.directory, self.output)

    def test_export_loads_offline_with_all_tables_samples_and_manifest(self):
        exported = json.loads(self.output.read_text(encoding='utf-8'))
        loaded = load_database(self.output)
        self.assertEqual(loaded['rows'], exported['rows'])
        self.assertEqual(loaded['manifest'], exported['manifest'])
        self.assertTrue(loaded['manifest']['complete'])
        self.assertEqual(len(loaded['rows']), 6)
        self.assertEqual(sum(len(row['samples']) for row in loaded['rows']), 12)
        self.assertEqual({(r['element'], r['charge']) for r in loaded['rows']},
                         set(fixtures.SPECIES))

    def test_runtime_rejects_changed_rows_in_a_real_export(self):
        exported = json.loads(self.output.read_text(encoding='utf-8'))
        exported['rows'][0]['samples'][0]['fwhm_angstrom'] *= 2
        self.output.write_text(json.dumps(exported, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(StarkDataAccessError, 'rows_sha256 checksum mismatch'):
            load_database(self.output)


if __name__ == '__main__':
    unittest.main()
