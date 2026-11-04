"""纯离线采集器契约测试：本轮只编写，未执行。

全部物种、XSAMS 和电子表均为合成测试数据，不代表真实原子数据。
使用内存 client/session，保留采集器自身的原子写入、SHA-256、清单和
读取校验。socket 连接和 sleep 另外被拦截，测试无需网络或实际等待。
这里只验证采集及缓存契约，既有 XSAMS 科学解析由其原有测试覆盖。
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode
import warnings
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://stark-b.obspm.fr/12.07/vamdc/tap/sync'
NS_URI = 'http://vamdc.org/xml/xsams/1.0'
NS = {'x': NS_URI}
SPECIES = (('C', 0), ('Fe', 2), ('Xe', 8))
MIN_NE = 1e-300


def _catalogue(species):
    atoms = []
    # 同一元素/q 的不同 speciesID 应去重；中性及高电离态都必须保留。
    for index, (element, charge) in enumerate(list(species) + [species[0]]):
        atoms.append(
            '<Atom><ChemicalElement><ElementSymbol>{}</ElementSymbol>'
            '</ChemicalElement><Isotope><Ion speciesID="X-test-{}">'
            '<IonCharge>{}</IonCharge></Ion></Isotope></Atom>'.format(element, index, charge))
    # H+ 只作为环境碰撞物种，electron 属于 Particles，均不应采集。
    atoms.append(
        '<Atom><ChemicalElement><ElementSymbol>H</ElementSymbol></ChemicalElement>'
        '<Isotope><Ion speciesID="X-collider"><IonCharge>1</IonCharge></Ion>'
        '</Isotope></Atom>')
    return (
        '<XSAMSData xmlns="{}"><Environments><Environment envID="E-test">'
        '<Composition><Species speciesRef="X-collider" /></Composition>'
        '</Environment></Environments><Species><Atoms>{}</Atoms><Particles>'
        '<Particle speciesID="X-electron" name="electron" />'
        '</Particles></Species></XSAMSData>'.format(NS_URI, ''.join(atoms)))


def _payload(element, charge, generation):
    # TestTables 是 mock 解析器的专用节点；不冒充完整的真实 XSAMS 跃迁。
    xml = (
        '<XSAMSData xmlns="{}"><TestTables>'
        '<Table ne="1e15" width="{}" /><Table ne="1e18" width="{}" />'
        '</TestTables></XSAMSData>'.format(NS_URI, generation / 10., generation / 5.))
    return dict(format='vamdc-xsams', element=element, charge=charge,
                requested_ne_cm3=MIN_NE, status='ok', datasets=[],
                pages=[dict(xml=xml, url=ENDPOINT, headers={'VAMDC-TRUNCATED': 'None'})])


def _parse_payload(payload, *, element, charge, ne):
    if ne != MIN_NE:
        raise ValueError('Test client requires all reference densities')
    if (payload['element'], payload['charge']) != (element, charge):
        raise ValueError('Synthetic payload identity mismatch')
    rows = []
    for page in payload['pages']:
        for table in ET.fromstring(page['xml']).findall('x:TestTables/x:Table', NS):
            density, width = float(table.get('ne')), float(table.get('width'))
            transition = 'synthetic-{}-q{}'.format(element, charge)
            samples = [dict(ne=density, temperature_k=temperature,
                            fwhm_angstrom=width * factor, flag='',
                            environment_id='test-environment', collider_ref='X-electron')
                       for temperature, factor in ((5000., 1.), (10000., .75))]
            rows.append(dict(
                element=element, charge=charge, dataset_id='vamdc:' + transition,
                transition_id=transition, method='unreported', lower_label='test lower',
                upper_label='test upper', lower_state_id='test-lower', upper_state_id='test-upper',
                calculated_wavelength_angstrom=5000., c_angstrom_cm3=None, fit=None,
                samples=samples, source='Synthetic test only; not a publication',
                source_ids=['test-only'], source_url=page['url'], source_format='vamdc-xsams',
                temperature_interpolation='linear', metadata={'reference_ne_cm3': density}))
    return rows


class _OfflineService:
    """只产生内存响应；每次 _client 调用返回独立对象以隔离 transport 包装。"""

    def __init__(self):
        self.species = list(SPECIES)
        self.truncated = 'None'
        self.generation = 1
        self.fail_species = set()
        self.http_calls = []
        self.fetch_calls = []
        self.sessions = []
        self.requests = SimpleNamespace(
            Session=self.session, Request=self.request,
            RequestException=OSError, Timeout=TimeoutError, ConnectionError=ConnectionError)

    @staticmethod
    def request(method, url, *, params):
        if method != 'GET':
            raise AssertionError('Unexpected HTTP method in offline test')
        prepared = SimpleNamespace(url=url + '?' + urlencode(params))
        return SimpleNamespace(prepare=lambda: prepared)

    def session(self):
        session = SimpleNamespace(get=Mock(side_effect=self.get), close=Mock())
        self.sessions.append(session)
        return session

    def get(self, url, **kwargs):
        self.http_calls.append((url, kwargs))
        if url != ENDPOINT or kwargs.get('params', {}).get('QUERY') != 'SELECT SPECIES':
            raise AssertionError('Unexpected request in offline test')
        headers = {} if self.truncated is None else {'VAMDC-TRUNCATED': self.truncated}
        return SimpleNamespace(status_code=200, content=_catalogue(self.species).encode('utf-8'),
                               headers=headers, raise_for_status=Mock(), close=Mock())

    def fetch_species(self, element, charge, ne):
        self.fetch_calls.append((element, charge, ne))
        if ne != MIN_NE:
            raise ValueError('Collector must request all reference densities')
        if (element, charge) in self.fail_species:
            raise ValueError('synthetic species download failure')
        return _payload(element, charge, self.generation)

    def client(self):
        return SimpleNamespace(TAP_URL=ENDPOINT, requests=self.requests,
                               _xml=ET.fromstring, fetch_species=self.fetch_species,
                               parse_payload=_parse_payload)


class StarkDataCollectTests(unittest.TestCase):
    def setUp(self):
        # 按路径加载被测模块，避免修改 sys.path 或导入 simLIBS 顶层。
        spec = importlib.util.spec_from_file_location(
            '_stark_collect_under_test', ROOT / 'stark_data_collect.py')
        self.collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.collector)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name) / 'stark-b'
        self.service = _OfflineService()
        self._patch(patch.object(self.collector, '_client', side_effect=self.service.client))
        self.sleep = self._patch(patch.object(self.collector.time, 'sleep'))
        self._patch(patch('socket.create_connection', side_effect=AssertionError('Network forbidden')))
        self._patch(patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')))

    def _patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def fetch(self, **kwargs):
        return self.collector.fetch_stark_database(self.directory, delay=0., **kwargs)

    def load(self, **kwargs):
        return self.collector.load_stark_tables(self.directory, **kwargs)

    @staticmethod
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def write(path, document):
        # 不调用采集器序列化/计数 helper，避免用同一实现生成错误期望值。
        data = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + chr(10)).encode('utf-8')
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def manifest(self):
        return self.read(self.directory / 'manifest.json')

    def rewrite_manifest(self, manifest):
        self.write(self.directory / 'manifest.json', manifest)

    def change_species_file(self, mutate):
        manifest = self.manifest()
        record = manifest['species'][0]
        path = self.directory / record['path']
        document = self.read(path)
        mutate(document)
        # 更新摘要后还必须拒绝内容矛盾，不能只由 SHA-256 碰巧挡住。
        record['sha256'] = self.write(path, document)
        self.rewrite_manifest(manifest)

    def reset_calls(self):
        self.service.http_calls.clear()
        self.service.fetch_calls.clear()

    @staticmethod
    def identities(rows):
        return {(row['element'], row['charge']) for row in rows}

    def test_discovery_rejects_truncation_or_missing_header_and_records_failure(self):
        for index, header in enumerate(('50%', '0', '', None)):
            with self.subTest(header=header):
                self.directory = self.directory.parent / ('case-' + str(index))
                self.service.truncated = header
                manifest = self.fetch()
                self.assertFalse(manifest['complete'])
                self.assertEqual(manifest['discovery']['status'], 'failed')
                self.assertIn('truncat', manifest['discovery']['error'].lower())
                self.assertEqual(manifest['failures'][0]['stage'], 'discovery')
                self.assertEqual(manifest['species'], [])
                self.assertEqual(self.service.fetch_calls, [])
                self.assertEqual(self.manifest(), manifest)
                for allow_partial in (False, True):
                    with self.assertRaisesRegex(ValueError, 'discovery is incomplete or failed'):
                        self.load(allow_partial=allow_partial)

    def test_catalogue_without_truncation_header_requires_matching_species_count(self):
        # SELECT SPECIES uses a species-only response with COUNT-SPECIES,
        # unlike SELECT ALL transition responses which require TRUNCATED.
        import stark_data_collect as collector
        real_client = collector._client()
        root = '<XSAMSData xmlns="http://vamdc.org/xml/xsams/1.0"><Species><Atoms>'
        root += '<Atom><ChemicalElement><ElementSymbol>C</ElementSymbol></ChemicalElement>'
        root += '<Isotope><Ion speciesID="C3"><IonCharge>2</IonCharge></Ion></Isotope></Atom>'
        root += '</Atoms></Species></XSAMSData>'
        page = dict(xml=root, url=real_client.TAP_URL, headers={'VAMDC-COUNT-SPECIES': '1'})
        self.assertEqual(collector._species_from_page(real_client, page), [dict(element='C', charge=2)])
        page['headers']['VAMDC-COUNT-SPECIES'] = '2'
        with self.assertRaises(ValueError):
            collector._species_from_page(real_client, page)

    def test_all_scope_deduplicates_atoms_keeps_neutral_and_high_charge(self):
        manifest = self.fetch()
        self.assertTrue(manifest['complete'])
        self.assertEqual(manifest['scope'], 'all')
        self.assertEqual(manifest['filters'], {'elements': None, 'charges': None})
        self.assertEqual([(item['element'], item['charge']) for item in manifest['species']], list(SPECIES))
        self.assertEqual(self.service.fetch_calls, [(element, charge, MIN_NE) for element, charge in SPECIES])
        self.assertEqual(manifest['discovery']['species_count'], 3)
        self.assertEqual(manifest['counts'], dict(species_count=3, ok_count=3, no_data_count=0,
                                                failed_count=0, pending_count=0,
                                                table_count=6, sample_count=12, page_count=3))
        rows = self.load()
        self.assertEqual(self.identities(rows), set(SPECIES))
        self.assertEqual(len(rows), 6)
        self.assertEqual({row['metadata']['reference_ne_cm3'] for row in rows}, {1e15, 1e18})
        self.assertTrue(all(row['method'] == 'unreported' for row in rows))
        _, kwargs = self.service.http_calls[0]
        self.assertEqual(kwargs['timeout'], (10, 60))
        self.assertFalse(kwargs['allow_redirects'])
        self.sleep.assert_not_called()

    def test_filtered_scope_is_complete_only_for_requested_intersection(self):
        manifest = self.fetch(elements=['Xe', 'C', 'C'], charges=[8, 0, 8])
        self.assertTrue(manifest['complete'])
        self.assertEqual(manifest['scope'], 'filtered')
        self.assertEqual(manifest['filters'], {'elements': ['C', 'Xe'], 'charges': [0, 8]})
        self.assertEqual(manifest['discovery']['species_count'], 3)
        self.assertEqual(self.service.fetch_calls, [('C', 0, MIN_NE), ('Xe', 8, MIN_NE)])
        self.assertEqual(self.identities(self.load()), {('C', 0), ('Xe', 8)})
        self.assertEqual(manifest['counts']['species_count'], 2)
        self.assertEqual(manifest['counts']['table_count'], 4)

    def test_manifest_cannot_relabel_filtered_scope_as_all(self):
        self.fetch(elements=['Fe'], charges=[2])
        manifest = self.manifest()
        manifest['scope'] = 'all'
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'scope disagrees'):
            self.load()

    def test_sha_corruption_rejected_and_partial_read_warns_and_skips_species(self):
        manifest = self.fetch()
        path = self.directory / manifest['species'][0]['path']
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.load()
        self.reset_calls()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            rows = self.load(allow_partial=True)
        self.assertEqual(self.identities(rows), {('Fe', 2), ('Xe', 8)})
        self.assertTrue(any(item.category is RuntimeWarning and 'C q=0' in str(item.message)
                            and 'SHA-256 mismatch' in str(item.message) for item in caught))
        self.assertEqual(self.service.http_calls, [])
        self.assertEqual(self.service.fetch_calls, [])

    def test_changed_saved_rows_rejected_even_with_matching_sha(self):
        self.fetch()

        def mutate(document):
            document['rows'][0]['samples'][0]['fwhm_angstrom'] += 1.

        self.change_species_file(mutate)
        with self.assertRaisesRegex(ValueError, 'Saved standard rows differ from original payload'):
            self.load()

    def test_changed_raw_payload_rejected_even_with_matching_sha(self):
        self.fetch()

        def mutate(document):
            page = document['payload']['pages'][0]
            root = ET.fromstring(page['xml'])
            root.find('x:TestTables/x:Table', NS).set('width', '9.5')
            page['xml'] = ET.tostring(root, encoding='unicode')

        self.change_species_file(mutate)
        with self.assertRaisesRegex(ValueError, 'Saved standard rows differ from original payload'):
            self.load()

    def test_manifest_table_count_must_agree_with_raw_rows(self):
        self.fetch()
        manifest = self.manifest()
        manifest['species'][0]['table_count'] += 1
        manifest['counts']['table_count'] += 1
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'Species counts/timestamp differ from manifest'):
            self.load()

    def test_manifest_aggregate_count_mismatch_rejected(self):
        self.fetch()
        manifest = self.manifest()
        manifest['counts']['sample_count'] += 1
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'aggregate counts/failures are inconsistent'):
            self.load()

    def test_manifest_missing_species_rejected_despite_consistent_aggregate_counts(self):
        self.fetch()
        manifest = self.manifest()
        removed = manifest['species'].pop()
        for name in ('species_count', 'ok_count'):
            manifest['counts'][name] -= 1
        for name in ('table_count', 'sample_count', 'page_count'):
            manifest['counts'][name] -= removed[name]
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'do not cover the selected discovery catalogue'):
            self.load()

    def test_discovery_list_must_agree_with_raw_even_when_sha_updated(self):
        self.fetch()
        manifest = self.manifest()
        path = self.directory / manifest['discovery']['path']
        index = self.read(path)
        index['species'].pop()
        manifest['discovery']['species_count'] -= 1
        manifest['discovery']['sha256'] = self.write(path, index)
        self.rewrite_manifest(manifest)
        for allow_partial in (False, True):
            with self.subTest(allow_partial=allow_partial):
                with self.assertRaisesRegex(ValueError, 'catalogue/count differs from its raw XSAMS'):
                    self.load(allow_partial=allow_partial)

    def test_incomplete_manifest_rejected_and_partial_mode_warns(self):
        self.service.fail_species.add(('Fe', 2))
        manifest = self.fetch()
        self.assertFalse(manifest['complete'])
        self.assertEqual(manifest['counts']['failed_count'], 1)
        self.assertEqual(manifest['counts']['ok_count'], 2)
        failed, = [item for item in manifest['species'] if item['status'] == 'failed']
        self.assertEqual((failed['element'], failed['charge']), ('Fe', 2))
        self.assertIsNone(failed['sha256'])
        self.assertEqual(failed['table_count'], 0)
        self.assertIn('synthetic species download failure', manifest['failures'][0]['error'])
        with self.assertRaisesRegex(ValueError, 'manifest is incomplete.*Fe q=2'):
            self.load()
        self.reset_calls()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            rows = self.load(allow_partial=True)
        messages = [str(item.message) for item in caught if item.category is RuntimeWarning]
        self.assertTrue(any('manifest is incomplete' in message for message in messages))
        self.assertTrue(any('Fe q=2' in message and 'download failure' in message for message in messages))
        self.assertEqual(self.identities(rows), {('C', 0), ('Xe', 8)})
        self.assertEqual(self.service.http_calls, [])
        self.assertEqual(self.service.fetch_calls, [])

    def test_interruption_before_complete_flag_still_requires_explicit_partial(self):
        self.fetch()
        manifest = self.manifest()
        manifest['complete'] = False
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'manifest is incomplete'):
            self.load()
        with self.assertWarnsRegex(RuntimeWarning, 'manifest is incomplete'):
            rows = self.load(allow_partial=True)
        self.assertEqual(self.identities(rows), set(SPECIES))

    def test_resume_reuses_valid_snapshot_without_discovery_or_fetch(self):
        initial = self.fetch()
        expected_rows = self.load()
        self.service.species.append(('N', 3))
        self.service.generation = 2
        self.reset_calls()
        resumed = self.fetch()
        self.assertTrue(resumed['complete'])
        self.assertEqual(resumed['discovery']['sha256'], initial['discovery']['sha256'])
        self.assertEqual(self.load(), expected_rows)
        self.assertEqual(self.service.http_calls, [])
        self.assertEqual(self.service.fetch_calls, [])

    def test_resume_repairs_only_species_with_damaged_sha(self):
        initial = self.fetch()
        path = self.directory / initial['species'][0]['path']
        path.write_bytes(path.read_bytes() + b' ')
        self.reset_calls()
        resumed = self.fetch()
        self.assertTrue(resumed['complete'])
        self.assertEqual(self.service.http_calls, [])
        self.assertEqual(self.service.fetch_calls, [('C', 0, MIN_NE)])
        self.assertIn('SHA-256 mismatch', resumed['species'][0]['cache_validation_error'])
        self.assertEqual(self.identities(self.load()), set(SPECIES))

    def test_parallel_collection_preserves_manifest_and_rows(self):
        manifest = self.fetch(workers=2)
        self.assertTrue(manifest['complete'])
        self.assertEqual(self.identities(self.load()), set(SPECIES))
        self.assertEqual(len(self.service.fetch_calls), len(SPECIES))

    def test_chunked_transfer_failure_is_retried(self):
        import requests
        transport = self.collector._Transport(requests, 0.)
        self.addCleanup(transport.close)
        response = SimpleNamespace(status_code=200, content=b'<unused/>',
                                   headers={'VAMDC-TRUNCATED': 'None'}, raise_for_status=Mock(), close=Mock())
        with patch.object(transport._session, 'get', side_effect=[
                requests.exceptions.ChunkedEncodingError('incomplete download'), response]) as request:
            self.assertIs(transport.get(ENDPOINT), response)
            self.assertEqual(request.call_count, 2)

    def test_streaming_response_size_is_bounded(self):
        import requests
        transport = self.collector._Transport(requests, 0.)
        self.addCleanup(transport.close)
        response = Mock(status_code=200, headers={'VAMDC-TRUNCATED': 'None'})
        response.iter_content.return_value = iter([b'x'*32, b'y'*32])
        with patch.object(transport._session, 'get', return_value=response), \
                patch.object(self.collector, '_MAX_RESPONSE_BYTES', 50, create=True):
            with self.assertRaisesRegex(ValueError, 'size'):
                transport.get(ENDPOINT)
        response.close.assert_called()

    def test_species_count_exception_is_not_used_for_transition_payload(self):
        client = self.collector._client()
        xml = '<XSAMSData xmlns="http://vamdc.org/xml/xsams/1.0"><Species><Atoms>'
        xml += '<Atom><ChemicalElement><ElementSymbol>C</ElementSymbol></ChemicalElement>'
        xml += '<Isotope><Ion speciesID="C2"><IonCharge>2</IonCharge></Ion></Isotope></Atom>'
        xml += '</Atoms></Species></XSAMSData>'
        page = dict(xml=xml, url=ENDPOINT+'?QUERY=SELECT+ALL', headers={'VAMDC-COUNT-SPECIES': '1'})
        payload = dict(format='vamdc-xsams', element='C', charge=2, requested_ne_cm3=MIN_NE,
                       status='no data', pages=[page])
        with self.assertRaises(ValueError):
            self.collector._payload_rows(client, payload, 'C', 2)

    def test_transports_share_request_start_limiter(self):
        import requests
        clock, starts = [100.], []
        def sleep(seconds):
            clock[0] += seconds
        def reply(*args, **kwargs):
            starts.append(clock[0])
            return SimpleNamespace(status_code=204, headers={}, content=b'', raise_for_status=lambda:None,
                                   close=lambda:None)
        with patch.object(self.collector.time, 'monotonic', side_effect=lambda:clock[0]), \
                patch.object(self.collector.time, 'sleep', side_effect=sleep), \
                patch.object(requests, 'Session', side_effect=lambda:SimpleNamespace(get=reply, close=lambda:None)):
            limiter = self.collector._RateLimiter(1.)
            a = self.collector._Transport(requests, 1., limiter=limiter)
            b = self.collector._Transport(requests, 1., limiter=limiter)
            a.get(ENDPOINT)
            b.get(ENDPOINT)
            b.get(ENDPOINT)
        self.assertEqual(starts, [100.,101.,102.])

    def test_resume_retries_failed_species_and_clears_failures(self):
        self.service.fail_species.add(('Fe', 2))
        self.assertFalse(self.fetch()['complete'])
        self.service.fail_species.clear()
        self.reset_calls()
        resumed = self.fetch()
        self.assertTrue(resumed['complete'])
        self.assertEqual(self.service.http_calls, [])
        self.assertEqual(self.service.fetch_calls, [('Fe', 2, MIN_NE)])
        self.assertEqual(resumed['failures'], [])
        self.assertEqual(resumed['counts']['failed_count'], 0)
        self.assertEqual(self.identities(self.load()), set(SPECIES))

    def test_refresh_rediscovers_new_species_and_refetches_successful_cache(self):
        initial = self.fetch()
        self.service.species.append(('N', 3))
        self.service.generation = 2
        self.reset_calls()
        refreshed = self.fetch(refresh=True)
        expected = sorted(SPECIES + (('N', 3),))
        self.assertTrue(refreshed['complete'])
        self.assertEqual(len(self.service.http_calls), 1)
        self.assertEqual(self.service.fetch_calls, [(element, charge, MIN_NE) for element, charge in expected])
        self.assertNotEqual(refreshed['discovery']['sha256'], initial['discovery']['sha256'])
        self.assertEqual(refreshed['counts']['species_count'], 4)
        rows = self.load()
        self.assertEqual(self.identities(rows), set(expected))
        self.assertEqual(len(rows), 8)
        widths = [row['samples'][0]['fwhm_angstrom'] for row in rows
                  if row['metadata']['reference_ne_cm3'] == 1e15]
        self.assertEqual(widths, [.2] * 4)


if __name__ == '__main__':
    unittest.main()
