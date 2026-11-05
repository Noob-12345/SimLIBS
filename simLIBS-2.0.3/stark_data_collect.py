"""显式采集 STARK-B 全物种电子碰撞展宽表，或离线读取已保存的标准 rows。

本模块导入时不请求网络、不创建文件，也不导入 simLIBS 顶层包。只有显式
调用 fetch_stark_database 或运行 CLI 才采集；load_stark_tables 始终离线。
客户端通过 importlib 按旁边 simLIBS/stark_vamdc.py 的路径加载，只需 requests。

中文 CLI 示例（这些命令会请求网络，须由使用者自行明确执行）：
    python stark_data_collect.py
    python stark_data_collect.py --output-dir ./stark-b --delay 1.0
    python stark_data_collect.py --elements Fe Si --charges 0 1 2 3
    python stark_data_collect.py --refresh --elements Fe --charges 2

--elements/--charges 也支持逗号分隔；电荷为实际 q，q=0 表示中性原子，
不设电离态上限。默认不筛选元素或电荷。complete 仅指 manifest 中 filters
指定的范围；scope=all 才表示所发现的全库物种。续取使用同一份已校验的
物种清单快照；要重新发现官方新增物种并重取表格，显式指定 --refresh。

科学口径：此节点的 Lorentzian gammaL 是电子 FWHM，单位 Å，不是 HWHM，
不应再乘二。使用既有 fetch_species(element, q, 1e-300) 和
parse_payload(..., ne=1e-300)，保留所有正参考电子密度的温度表，不按目标
密度挑选或缩放。method='unreported'、C、拟合及原始警告按解析器原样保留；
不能据此推断计算方法、谱线隔离条件或碰撞近似的有效性。

存储：manifest.json 引用 species_index.json 的完整 SELECT SPECIES 响应，
以及 species/<element>_q<charge>.json；每个物种文件同时含 payload 和 rows。
文件先校验再以同目录临时文件原子替换，manifest 保存 SHA-256、计数及失败。
一次运行不支持多个写入进程共用同一输出目录。读取默认拒绝不完整快照；
allow_partial=True 会警告并只返回校验成功的物种，不能绕过物种清单损坏。
官方明确返回无电子表的物种仍算完成请求，data_status='no data' 且
table_count=0；counts.no_data_count 单列数量，不会用合成数据填补。

离线读取示例：
    from pathlib import Path
    rows = load_stark_tables(Path('stark-b'))
    rows = load_stark_tables(Path('stark-b'), allow_partial=True)
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import threading
import warnings
from requests.exceptions import ChunkedEncodingError, HTTPError


SCHEMA_VERSION = 1
_MIN_NE = 1e-300
_TIMEOUT = (10, 60)  # requests 的连接/读取超时，秒；每个请求都显式传入。
_ATTEMPTS = 3
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024
_MAX_REQUEST_SECONDS = 120
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
_DISCOVERY_QUERY = 'SELECT SPECIES'
_INDEX_PATH = 'species_index.json'
_NS = {'x': 'http://vamdc.org/xml/xsams/1.0'}
_SYMBOL = re.compile(r'[A-Z][a-z]?\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_STATUSES = {'pending', 'ok', 'failed'}


def _client():
    """独立加载客户端，不执行 simLIBS/__init__.py。"""
    source = Path(__file__).resolve().parent / 'simLIBS' / 'stark_vamdc.py'
    spec = importlib.util.spec_from_file_location('_stark_collection_vamdc', source)
    if spec is None or spec.loader is None:
        raise ImportError('Cannot load STARK-B client: ' + str(source))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _timestamp(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(
                r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value):
            raise ValueError
        datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as exc:
        raise ValueError('Missing or invalid UTC timestamp') from exc


def _identity(element, charge):
    if (not isinstance(element, str) or not _SYMBOL.fullmatch(element)
            or type(charge) is not int or charge < 0):
        raise ValueError('Invalid atomic species: {!r}, {!r}'.format(element, charge))
    return element, charge


def _filters(elements, charges):
    if elements is not None:
        if isinstance(elements, str):
            elements = elements.replace(',', ' ').split()
        try:
            elements = list(elements)
        except TypeError as exc:
            raise ValueError('elements must be an iterable of element symbols') from exc
        if not elements:
            raise ValueError('elements must be nonempty or None')
        for element in elements:
            _identity(element, 0)
        elements = sorted(set(elements))
    if charges is not None:
        if isinstance(charges, (str, bytes)):
            raise ValueError('charges must contain integer q values')
        try:
            charges = list(charges)
        except TypeError as exc:
            raise ValueError('charges must be an iterable of integer q values') from exc
        if not charges:
            raise ValueError('charges must be nonempty or None')
        for charge in charges:
            _identity('H', charge)
        charges = sorted(set(charges))
    return {'elements': elements, 'charges': charges}


def _selected(species, filters):
    return [item for item in species
            if (filters['elements'] is None or item['element'] in filters['elements'])
            and (filters['charges'] is None or item['charge'] in filters['charges'])]


def _key(item):
    if not isinstance(item, dict):
        raise ValueError('Species entry must be an object')
    return _identity(item.get('element'), item.get('charge'))


def _species_path(element, charge):
    return 'species/{}_q{}.json'.format(element, charge)


def _path(directory, relative):
    if not isinstance(relative, str) or not relative or chr(92) in relative:
        raise ValueError('Invalid manifest relative path')
    candidate = directory / relative
    try:
        candidate.resolve().relative_to(directory.resolve())
    except ValueError as exc:
        raise ValueError('Manifest path escapes the database directory') from exc
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Manifest path must be relative and remain inside the directory')
    return candidate


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError('Nonfinite JSON number: ' + value)


def _decode(data, path):
    try:
        document = json.loads(data.decode('utf-8'), object_pairs_hook=_object,
                              parse_constant=_bad_constant)
        _json_bytes(document)  # 也拒绝溢出的 1e999 之类非有限数。
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError('Invalid JSON in {}: {}'.format(path, exc)) from exc
    if not isinstance(document, dict):
        raise ValueError('Expected JSON object in ' + str(path))
    return document


def _read_json(path):
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError('Cannot read {}: {}'.format(path, exc)) from exc
    return _decode(data, path)


def _read_hashed(directory, record):
    digest = record.get('sha256')
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError('Missing or invalid SHA-256')
    path = _path(directory, record.get('path'))
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError('Cannot read {}: {}'.format(path, exc)) from exc
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('SHA-256 mismatch: ' + str(path))
    return _decode(data, path)


def _atomic_json(path, value):
    data = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.' + path.name + '.',
                                         suffix='.tmp', dir=str(path.parent),
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return hashlib.sha256(data).hexdigest()


def _header(headers):
    if not isinstance(headers, dict):
        raise ValueError('Missing XSAMS response headers')
    values = [value for key, value in headers.items()
              if isinstance(key, str) and key.lower() == 'vamdc-truncated']
    if len(values) != 1 or not isinstance(values[0], str) or not values[0].strip():
        raise ValueError('Missing or ambiguous VAMDC-TRUNCATED completeness header')
    return values[0].strip()


def _page(page, endpoint, *, complete=True, allow_species_count=False):
    if not isinstance(page, dict):
        raise ValueError('Invalid XSAMS source page')
    url = page.get('url')
    if not isinstance(url, str) or (url != endpoint and not url.startswith(endpoint + '?')):
        raise ValueError('Unexpected STARK-B source URL')
    headers = page.get('headers')
    has_truncation = isinstance(headers, dict) and any(
        key.lower() == 'vamdc-truncated' for key in headers if isinstance(key, str))
    if not has_truncation:
        if not allow_species_count:
            raise ValueError('Missing VAMDC-TRUNCATED completeness header for transition payload')
        # The unfiltered SELECT SPECIES endpoint exports the entire species-only
        # catalogue and COUNT-SPECIES, but no TRUNCATED header. Accept only when
        # its declared count exactly matches all returned species objects, and
        # no states/transitions occur (SELECT ALL still requires TRUNCATED).
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(page['xml'])
            counts = [value for key, value in headers.items() if key.lower() == 'vamdc-count-species']
            actual = len(root.findall('x:Species/x:Atoms/x:Atom/x:Isotope/x:Ion', _NS))
            actual += len(root.findall('x:Species/x:Particles/x:Particle', _NS))
            if (len(counts) != 1 or int(counts[0]) != actual or actual == 0 or
                    root.findall('.//x:AtomicState', _NS) or root.findall('.//x:RadiativeTransition', _NS)):
                raise ValueError
            return
        except (ET.ParseError, KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError('Missing VAMDC-TRUNCATED and no complete species-count evidence') from exc
    truncated = _header(headers)
    if complete and truncated.lower() != 'none':
        raise ValueError('Truncated XSAMS response: ' + truncated)
    if not isinstance(page.get('xml'), str):
        raise ValueError('Missing original XSAMS XML')


class _RateLimiter:
    def __init__(self, delay):
        self.delay, self.last = delay, None
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            if self.last is not None:
                remaining = self.delay-(time.monotonic()-self.last)
                if remaining > 0:
                    time.sleep(remaining)
            self.last = time.monotonic()


class _Transport:
    """仅包装本次独立客户端；节流覆盖其内部每个波长分区请求。"""

    def __init__(self, requests_module, delay, *, limiter=None):
        self._requests = requests_module
        self._session = requests_module.Session()
        self._delay = delay
        self._last_request = None
        self._limiter = limiter or _RateLimiter(delay)
        self.Request = requests_module.Request

    def get(self, url, **kwargs):
        kwargs['timeout'] = _TIMEOUT
        kwargs['allow_redirects'] = False
        kwargs['stream'] = True
        for attempt in range(_ATTEMPTS):
            response = None
            try:
                self._limiter.wait()
                self._last_request = time.monotonic()
                started = time.monotonic()
                print('STARK-B requesting: '+str(kwargs.get('params', {}).get('QUERY', url)), flush=True)
                response = self._session.get(url, **kwargs)
                response.raise_for_status()
                if response.status_code not in (200, 204):
                    raise ValueError('Unexpected STARK-B HTTP status: ' + str(response.status_code))
                # requests 在默认 stream=False 下已用读取超时读完响应体。
                # 保留 content 后关闭 response，客户端仍可访问原始字节和头。
                if hasattr(response, 'iter_content'):
                    chunks, size = [], 0
                    for chunk in response.iter_content(chunk_size=64*1024):
                        size += len(chunk)
                        if size > _MAX_RESPONSE_BYTES:
                            raise ValueError('Response size exceeds 20 MiB; no partial data retained')
                        if time.monotonic()-started > _MAX_REQUEST_SECONDS:
                            raise ValueError('Request total time exceeds 120 seconds; no partial data retained')
                        chunks.append(chunk)
                    response._content = b''.join(chunks)
                    response._content_consumed = True
                else:
                    _ = response.content  # in-memory offline test transport
                if response.status_code == 200:
                    if kwargs.get('params', {}).get('QUERY') == _DISCOVERY_QUERY:
                        _page(dict(xml=response.content.decode('utf-8'), url=url,
                                   headers=dict(response.headers)), url, allow_species_count=True)
                    else:
                        value = _header(dict(response.headers))
                        response.headers['VAMDC-TRUNCATED'] = value
                elif 'VAMDC-TRUNCATED' in response.headers:
                    if _header(dict(response.headers)).lower() != 'none':
                        raise ValueError('Truncated HTTP 204 response')
                return response
            except self._requests.RequestException as exc:
                status = response.status_code if response is not None else None
                retry = (isinstance(exc, (self._requests.Timeout, self._requests.ConnectionError, ChunkedEncodingError))
                         or status in _RETRY_STATUSES)
                if not retry or attempt + 1 == _ATTEMPTS:
                    raise
                if response is not None:
                    response.close()
                time.sleep(2 ** attempt)
            finally:
                if response is not None:
                    response.close()
        raise RuntimeError('STARK-B retry limit exhausted')

    def close(self):
        self._session.close()


def _species_from_page(client, page):
    _page(page, client.TAP_URL, allow_species_count=True)
    root = client._xml(page['xml'])
    # SELECT SPECIES 通常不带环境；若响应带环境，只排除有明确证据的
    # 纯碰撞物种，不凭 H/He 等元素名称删掉可能的真实谱线目标。
    colliders = {node.get('speciesRef') for node in
                 root.findall('x:Environments/x:Environment/x:Composition/x:Species', _NS)}
    targets = {node.text.strip() for node in root.findall(
        'x:Processes/x:Radiative/x:RadiativeTransition/x:SpeciesRef', _NS)
        if node.text and node.text.strip()}
    species, identifiers = set(), set()
    for atom in root.findall('x:Species/x:Atoms/x:Atom', _NS):
        symbols = atom.findall('x:ChemicalElement/x:ElementSymbol', _NS)
        if len(symbols) != 1 or not symbols[0].text:
            raise ValueError('Missing or ambiguous discovery element symbol')
        element = symbols[0].text.strip()
        ions = atom.findall('x:Isotope/x:Ion', _NS)
        if not ions:
            raise ValueError('Discovery atom has no Ion entries: ' + element)
        for ion in ions:
            identifier = ion.get('speciesID')
            if not identifier or identifier in identifiers:
                raise ValueError('Missing or duplicate discovery speciesID')
            identifiers.add(identifier)
            values = ion.findall('x:IonCharge', _NS)
            if len(values) != 1 or values[0].text is None:
                raise ValueError('Missing or ambiguous discovery IonCharge')
            text = values[0].text.strip()
            if not re.fullmatch(r'\+?\d+', text):
                raise ValueError('Invalid nonnegative discovery IonCharge: ' + text)
            identity = _identity(element, int(text))
            if (identifier in colliders and identifier not in targets
                    and not ion.findall('x:AtomicState', _NS)):
                continue
            species.add(identity)
    # 只遍历 Atoms/Atom/Isotope/Ion；Particles 中的 electron 等不入清单。
    if not species:
        raise ValueError('SELECT SPECIES returned no atomic target species')
    return [{'element': element, 'charge': charge} for element, charge in sorted(species)]


def _discover(client):
    params = dict(REQUEST='doQuery', LANG='VSS2', FORMAT='XSAMS', QUERY=_DISCOVERY_QUERY)
    response = client.requests.get(client.TAP_URL, params=params)
    if response.status_code != 200:
        raise ValueError('SELECT SPECIES did not return a species catalogue')
    try:
        xml = response.content.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('Invalid discovery UTF-8') from exc
    page = {'xml': xml, 'headers': dict(response.headers),
            'url': client.requests.Request('GET', client.TAP_URL, params=params).prepare().url}
    species = _species_from_page(client, page)
    return {'schema_version': SCHEMA_VERSION, 'endpoint': client.TAP_URL,
            'retrieved_utc': _utc(), 'query': _DISCOVERY_QUERY,
            'page': page, 'species': species}


def _version(document, endpoint):
    if type(document.get('schema_version')) is not int or document['schema_version'] != SCHEMA_VERSION:
        raise ValueError('Unsupported STARK-B database schema_version')
    if document.get('endpoint') != endpoint:
        raise ValueError('Database endpoint differs from the official client endpoint')
    _timestamp(document.get('retrieved_utc'))


def _read_index(directory, record, client):
    if record.get('status') != 'ok' or record.get('path') != _INDEX_PATH:
        raise ValueError('Species discovery is incomplete or failed: ' + str(record.get('error')))
    document = _read_hashed(directory, record)
    _version(document, client.TAP_URL)
    if document.get('query') != _DISCOVERY_QUERY:
        raise ValueError('Species discovery query is not an unrestricted SELECT SPECIES')
    species = _species_from_page(client, document.get('page'))
    if (_json_bytes(document.get('species')) != _json_bytes(species)
            or record.get('species_count') != len(species)
            or record.get('retrieved_utc') != document['retrieved_utc']):
        raise ValueError('Species discovery catalogue/count differs from its raw XSAMS')
    return species


def _payload_rows(client, payload, element, charge):
    if not isinstance(payload, dict):
        raise ValueError('Missing original species payload')
    if _key(payload) != (element, charge) or payload.get('requested_ne_cm3') != _MIN_NE:
        raise ValueError('Payload species or reference-density coverage mismatch')
    pages = payload.get('pages')
    if not isinstance(pages, list):
        raise ValueError('Missing original payload pages')
    if payload.get('format') == 'starkb-html':
        from stark_html_collect import parse_payload
        rows = parse_payload(payload, element=element, charge=charge, ne=_MIN_NE)
    else:
        for page in pages:
            _page(page, client.TAP_URL)
        rows = client.parse_payload(payload, element=element, charge=charge, ne=_MIN_NE)
    if payload.get('status') != ('ok' if rows else 'no data'):
        raise ValueError('Payload status disagrees with its electron tables')
    _json_bytes(rows)
    return rows


def _read_species(directory, record, client):
    element, charge = _key(record)
    if record.get('status') != 'ok' or record.get('path') != _species_path(element, charge):
        raise ValueError('Species is not stored successfully')
    document = _read_hashed(directory, record)
    _version(document, client.TAP_URL)
    if _key(document) != (element, charge):
        raise ValueError('Stored species identity differs from manifest')
    rows = _payload_rows(client, document.get('payload'), element, charge)
    if _json_bytes(document.get('rows')) != _json_bytes(rows):
        raise ValueError('Saved standard rows differ from original payload')
    expected = (len(rows), sum(len(row['samples']) for row in rows),
                len(document['payload']['pages']))
    actual = (record.get('table_count'), record.get('sample_count'), record.get('page_count'))
    if (actual != expected or document['retrieved_utc'] != record.get('retrieved_utc')
            or record.get('data_status') != document['payload']['status']):
        raise ValueError('Species counts/timestamp differ from manifest')
    return document['rows']


def _pending(element, charge):
    return {'element': element, 'charge': charge, 'status': 'pending',
            'path': _species_path(element, charge), 'sha256': None,
            'table_count': 0, 'sample_count': 0, 'page_count': 0,
            'retrieved_utc': None, 'data_status': None, 'error': None}


def _counts(species):
    successful = [record for record in species if record['status'] == 'ok']
    return {'species_count': len(species), 'ok_count': len(successful),
            'no_data_count': sum(record['data_status'] == 'no data' for record in successful),
            'failed_count': sum(record['status'] == 'failed' for record in species),
            'pending_count': sum(record['status'] == 'pending' for record in species),
            'table_count': sum(record['table_count'] for record in successful),
            'sample_count': sum(record['sample_count'] for record in successful),
            'page_count': sum(record['page_count'] for record in successful)}


def _failures(manifest):
    failures = []
    discovery = manifest['discovery']
    if discovery['status'] == 'failed':
        failures.append({'stage': 'discovery', 'error': discovery['error']})
    if discovery.get('selection_error'):
        failures.append({'stage': 'selection', 'error': discovery['selection_error']})
    for record in manifest['species']:
        if record['status'] == 'failed':
            failures.append({'stage': 'species', 'element': record['element'],
                             'charge': record['charge'], 'error': record['error']})
    return failures


def _save_manifest(directory, manifest):
    manifest['retrieved_utc'] = _utc()
    manifest['counts'] = _counts(manifest['species'])
    manifest['failures'] = _failures(manifest)
    _atomic_json(_path(directory, 'manifest.json'), manifest)


def _manifest_structure(manifest, endpoint):
    _version(manifest, endpoint)
    if type(manifest.get('complete')) is not bool:
        raise ValueError('Manifest complete must be boolean')
    filters = manifest.get('filters')
    if not isinstance(filters, dict) or set(filters) != {'elements', 'charges'}:
        raise ValueError('Manifest is missing selection filters')
    if any(value is not None and not isinstance(value, list) for value in filters.values()):
        raise ValueError('Manifest filters must be lists or null')
    if _filters(filters['elements'], filters['charges']) != filters:
        raise ValueError('Manifest selection filters are not canonical')
    scope = 'all' if filters == {'elements': None, 'charges': None} else 'filtered'
    if manifest.get('scope') != scope:
        raise ValueError('Manifest scope disagrees with selection filters')
    discovery = manifest.get('discovery')
    if (not isinstance(discovery, dict) or not isinstance(discovery.get('status'), str)
            or discovery['status'] not in _STATUSES):
        raise ValueError('Invalid manifest discovery status')
    if discovery.get('path') != _INDEX_PATH:
        raise ValueError('Invalid manifest discovery path')
    if discovery['status'] == 'failed' and not discovery.get('error'):
        raise ValueError('Discovery failure has no visible error')
    if (discovery.get('query') != _DISCOVERY_QUERY
            or type(discovery.get('species_count')) is not int or discovery['species_count'] < 0):
        raise ValueError('Invalid discovery query or species count')
    if discovery['status'] == 'ok':
        if (not isinstance(discovery.get('sha256'), str)
                or not _DIGEST.fullmatch(discovery['sha256']) or not discovery['species_count']):
            raise ValueError('Successful discovery lacks a checksum or species')
        _timestamp(discovery.get('retrieved_utc'))
        if discovery.get('error') is not None:
            raise ValueError('Successful discovery retains an unresolved error')
    elif discovery.get('sha256') is not None or discovery['species_count']:
        raise ValueError('Unsuccessful discovery must not advertise a catalogue')
    species = manifest.get('species')
    if not isinstance(species, list):
        raise ValueError('Manifest species must be a list')
    seen = set()
    for record in species:
        identity = _key(record)
        if identity in seen:
            raise ValueError('Duplicate species in manifest')
        seen.add(identity)
        if not isinstance(record.get('status'), str) or record['status'] not in _STATUSES:
            raise ValueError('Invalid species status in manifest')
        if record.get('path') != _species_path(*identity):
            raise ValueError('Invalid species path in manifest')
        for name in ('table_count', 'sample_count', 'page_count'):
            if type(record.get(name)) is not int or record[name] < 0:
                raise ValueError('Invalid manifest species ' + name)
        if record['status'] == 'ok':
            if not isinstance(record.get('sha256'), str) or not _DIGEST.fullmatch(record['sha256']):
                raise ValueError('Successful species has no SHA-256')
            _timestamp(record.get('retrieved_utc'))
            if record.get('error') is not None:
                raise ValueError('Successful species retains an unresolved error')
            if record.get('data_status') != ('ok' if record['table_count'] else 'no data'):
                raise ValueError('Species data status disagrees with table count')
        else:
            if record.get('sha256') is not None or any(record[name] for name in
                                                      ('table_count', 'sample_count', 'page_count')):
                raise ValueError('Unsuccessful species must not advertise saved tables')
            if record['status'] == 'failed' and not record.get('error'):
                raise ValueError('Species failure has no visible error')
            if record.get('data_status') is not None:
                raise ValueError('Unsuccessful species advertises a data status')
    if (_json_bytes(manifest.get('counts')) != _json_bytes(_counts(species))
            or _json_bytes(manifest.get('failures')) != _json_bytes(_failures(manifest))):
        raise ValueError('Manifest aggregate counts/failures are inconsistent')
    if manifest['complete'] and (discovery['status'] != 'ok' or not species
                                 or discovery.get('selection_error')
                                 or any(record['status'] != 'ok' for record in species)):
        raise ValueError('Manifest claims completeness while work is missing')


def fetch_stark_database(output_dir: Path, *, refresh=False, delay=1.0,
                         elements=None, charges=None, workers=1) -> dict:
    """显式采集或续取；返回 manifest，部分失败保持 complete=False。

    refresh=False 只复用经过 SHA-256 和原始 payload 重解析的成功文件，
    失败、未完成或损坏物种会重新请求。refresh=True 重取物种清单及所有
    当前筛选物种。每个 HTTP 请求最多三次尝试；分区上限由既有客户端限定。
    清单发现失败也返回带错误的 manifest；参数、不可写目录或损坏的旧
    manifest 则抛出异常（损坏旧 manifest 可用 refresh=True 显式重建）。
    """
    if type(refresh) is not bool or isinstance(delay, bool):
        raise ValueError('refresh must be boolean and delay must be finite and nonnegative')
    try:
        delay = float(delay)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('delay must be finite and nonnegative') from exc
    if not math.isfinite(delay) or delay < 0:
        raise ValueError('delay must be finite and nonnegative')
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers must be an integer between 1 and 4')
    filters = _filters(elements, charges)
    directory = Path(output_dir).expanduser().resolve()
    client = _client()
    previous = None
    manifest_path = _path(directory, 'manifest.json')
    if not refresh and manifest_path.exists():
        previous = _read_json(manifest_path)
        _manifest_structure(previous, client.TAP_URL)
    old = {_key(record): record for record in previous['species']} if previous else {}
    discovery = {'status': 'pending', 'path': _INDEX_PATH, 'sha256': None,
                 'species_count': 0, 'query': _DISCOVERY_QUERY, 'error': None}
    if previous:
        discovery = dict(previous['discovery'])
    manifest = {'schema_version': SCHEMA_VERSION, 'endpoint': client.TAP_URL,
                'retrieved_utc': _utc(), 'complete': False,
                'source': 'STARK-B official VAMDC XSAMS',
                'scope': 'all' if elements is None and charges is None else 'filtered',
                'filters': filters, 'discovery': discovery,
                'species': [dict(record) for record in
                            _selected(previous['species'], filters)] if previous else [],
                'counts': {}, 'failures': []}
    # 先撤销 complete；即使中断，也不会把本次部分成功伪装成完整快照。
    _save_manifest(directory, manifest)
    limiter = _RateLimiter(delay)
    transport = _Transport(client.requests, delay, limiter=limiter)
    client.requests = transport
    try:
        species = None
        if previous and discovery['status'] == 'ok':
            try:
                species = _read_index(directory, discovery, client)
            except ValueError as exc:
                discovery['cache_validation_error'] = str(exc)
        if species is None:
            discovery.update(status='pending', sha256=None, species_count=0, error=None)
            _save_manifest(directory, manifest)
            try:
                index = _discover(client)
                species = index['species']
                digest = _atomic_json(_path(directory, _INDEX_PATH), index)
                discovery.update(status='ok', sha256=digest, species_count=len(species),
                                 retrieved_utc=index['retrieved_utc'], error=None)
            except Exception as exc:
                discovery.update(status='failed', error='{}: {}'.format(type(exc).__name__, exc))
                _save_manifest(directory, manifest)
                return manifest
        selected = _selected(species, filters)
        # 筛选为元素与电荷的交集；拒绝空交集被当作成功的数据库。
        if not selected:
            discovery['selection_error'] = 'No catalogue species match filters: ' + repr(filters)
            manifest['species'] = []
            _save_manifest(directory, manifest)
            raise ValueError(discovery['selection_error'])
        discovery.pop('selection_error', None)
        manifest['species'] = [dict(old[_key(item)]) if _key(item) in old
                               else _pending(*_key(item)) for item in selected]
        _save_manifest(directory, manifest)
        def collect(record):
            element, charge = _key(record)
            worker_client = _client()
            worker_transport = _Transport(worker_client.requests, delay, limiter=limiter)
            worker_client.requests = worker_transport
            try:
                try:
                    payload = worker_client.fetch_species(element, charge, _MIN_NE)
                except HTTPError as exc:
                    if exc.response is None or exc.response.status_code != 400:
                        raise
                    from stark_html_collect import fetch_species
                    payload = fetch_species(element, charge, limiter=limiter)
                    payload['vamdc_error'] = str(exc)
                rows = _payload_rows(worker_client, payload, element, charge)
                timestamp = _utc()
                document = {'schema_version': SCHEMA_VERSION, 'endpoint': client.TAP_URL,
                            'retrieved_utc': timestamp, 'element': element, 'charge': charge,
                            'payload': payload, 'rows': rows}
                digest = _atomic_json(_path(directory, record['path']), document)
                record.update(status='ok', sha256=digest, table_count=len(rows),
                              sample_count=sum(len(row['samples']) for row in rows),
                              page_count=len(payload['pages']), retrieved_utc=timestamp,
                              data_status=payload['status'])
            except Exception as exc:
                record.update(status='failed', error='{}: {}'.format(type(exc).__name__, exc))
            finally:
                worker_transport.close()
            return record

        pending = []
        for position, old_record in enumerate(manifest['species']):
            cache_error = None
            if old_record['status'] == 'ok':
                try:
                    _read_species(directory, old_record, client)
                    continue
                except ValueError as exc:
                    cache_error = str(exc)
            record = _pending(*_key(old_record))
            if cache_error:
                record['cache_validation_error'] = cache_error
            manifest['species'][position] = record
            pending.append((position, record))
        _save_manifest(directory, manifest)
        if workers > 1:
            pending.sort(key=lambda item: (item[1]['charge'] not in (2, 3),
                                          item[1]['element'] not in ('C', 'Si', 'B', 'Al', 'Na', 'Mg'),
                                          item[1]['element'], item[1]['charge']))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(collect, dict(record)): position for position, record in pending}
            for future in as_completed(futures):
                position = futures[future]
                record = future.result()
                manifest['species'][position] = record
                _save_manifest(directory, manifest)
                print('STARK-B {} q={}: {}; tables={}; {}'.format(
                    record['element'], record['charge'], record['status'], record.get('table_count', 0),
                    record.get('error', '')), flush=True)
        manifest['complete'] = all(record['status'] == 'ok' for record in manifest['species'])
        _save_manifest(directory, manifest)
        return manifest
    finally:
        transport.close()


def load_stark_tables(directory: Path, *, allow_partial=False) -> list[dict]:
    """离线读取标准 rows；验证完整清单、SHA-256、原始表及全部计数。

    默认任何未完成、失败或数据损坏均 raise ValueError。显式允许部分读取
    时，逐个损坏/失败物种会发出 RuntimeWarning，且不返回其任何 rows；
    manifest 或全库物种清单本身损坏仍直接拒绝。不会自动下载或修复。
    """
    if type(allow_partial) is not bool:
        raise ValueError('allow_partial must be boolean')
    directory = Path(directory).expanduser().resolve()
    manifest = _read_json(_path(directory, 'manifest.json'))
    client = _client()
    _manifest_structure(manifest, client.TAP_URL)
    species = _read_index(directory, manifest['discovery'], client)
    expected = {_key(item) for item in _selected(species, manifest['filters'])}
    actual = {_key(record) for record in manifest['species']}
    if not expected or actual != expected or manifest['discovery'].get('selection_error'):
        raise ValueError('Manifest species do not cover the selected discovery catalogue')
    if not manifest['complete']:
        detail = '; '.join('{} q={}: {} ({})'.format(
            record['element'], record['charge'], record['status'], record.get('error'))
            for record in manifest['species'] if record['status'] != 'ok')
        message = 'STARK-B manifest is incomplete' + (': ' + detail if detail else '')
        if not allow_partial:
            raise ValueError(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)
    rows = []
    for record in manifest['species']:
        try:
            if record['status'] != 'ok':
                raise ValueError('{}: {}'.format(record['status'], record.get('error')))
            stored = _read_species(directory, record, client)
        except ValueError as exc:
            message = '{} q={}: {}'.format(record['element'], record['charge'], exc)
            if not allow_partial:
                raise ValueError(message) from exc
            warnings.warn('Skipping STARK-B species ' + message, RuntimeWarning, stacklevel=2)
            continue
        rows.extend(stored)
    return rows


def export_stark_database(directory: Path, output: Path, *, allow_partial=False):
    """Write a portable, provenance-preserving JSON for simulation.

    All downloaded electron tables are retained, regardless of whether the
    semiempirical model supports their ion or has sufficient atomic inputs.
    Raw XSAMS payloads preserve the other colliders, shifts and source text.
    A partial export must be explicitly requested and remains labelled partial.
    """
    directory = Path(directory).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if output in (directory / "manifest.json", directory / _INDEX_PATH) or directory / "species" in output.parents:
        raise ValueError("Export must not overwrite the collection manifest or species cache")
    rows = load_stark_tables(directory, allow_partial=allow_partial)
    manifest = _read_json(directory / "manifest.json")
    raw_payloads = []
    client = _client()
    for record in manifest["species"]:
        if record["status"] != "ok":
            continue
        try:
            _read_species(directory, record, client)
            document = _read_hashed(directory, record)
        except ValueError:
            if not allow_partial:
                raise
            continue
        raw = _json_bytes(document["payload"])
        raw_payloads.append({"element": record["element"], "charge": record["charge"],
                             "retrieved_utc": document["retrieved_utc"],
                             "sha256": record["sha256"], "encoding": "gzip+base64",
                             "uncompressed_sha256": hashlib.sha256(raw).hexdigest(),
                             "payload_gzip_base64": base64.b64encode(
                                 gzip.compress(raw, mtime=0)).decode("ascii")})
    line_ids = {(r["element"], r["charge"], r["dataset_id"],
                 r.get("lower_state_id", r["lower_label"]),
                 r.get("upper_state_id", r["upper_label"]), r["source"])
                for r in rows}
    document = {
        "schema_version": 1, "source": "STARK-B", "exported_utc": _utc(),
        "endpoint": manifest["endpoint"],
        "complete": manifest["complete"] and len(raw_payloads) == len(manifest["species"]),
        "scope": manifest["scope"],
        "units": {"fwhm_angstrom": "angstrom (FWHM, not HWHM)",
                  "temperature_k": "K", "ne": "cm^-3",
                  "calculated_wavelength_angstrom": "angstrom"},
        "counts": {"species": len(raw_payloads), "elements": len({r["element"] for r in rows}),
                   "lines": len(line_ids), "tables": len(rows),
                   "samples": sum(len(r["samples"]) for r in rows)},
        "rows_sha256": hashlib.sha256(json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode('utf-8')).hexdigest(),
        "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
        "manifest": manifest, "rows": rows, "raw_payloads": raw_payloads,
        "notes": [
            "rows contains all downloaded electron FWHM tables, without MSE applicability filtering.",
            "raw_payloads retains lossless gzip+base64 original XSAMS/HTML payload JSON including other colliders and shifts.",
            "Unknown methods, C and fits remain unknown. Flags are retained, not silently removed.",
            "complete describes retrieval of the discovered scope; it does not establish physical validity.",
        ],
    }
    digest = _atomic_json(output, document)
    return {"path": str(output), "sha256": digest, "complete": document["complete"],
            "scope": document["scope"], "counts": document["counts"]}


def _cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output-dir', type=Path,
                        default=Path(__file__).resolve().parent / 'stark-b',
                        help='输出目录，默认脚本旁边的 stark-b')
    parser.add_argument('--refresh', action='store_true', help='重新发现并采集，不复用旧缓存')
    parser.add_argument('--workers', type=int, default=1, help='Concurrent species downloads, 1-4')
    parser.add_argument('--delay', type=float, default=1.0, help='每个 HTTP 请求的最小间隔秒数')
    parser.add_argument('--elements', nargs='+', help='元素符号列表，可空格或逗号分隔')
    parser.add_argument('--charges', nargs='+', help='实际电荷 q 列表，可空格或逗号分隔；含 0')
    parser.add_argument('--export-json', type=Path, help='导出供模拟使用的单个 JSON（含原始 XSAMS）')
    parser.add_argument('--export-only', action='store_true', help='仅校验和导出已有下载，不联网')
    parser.add_argument('--allow-partial', action='store_true', help='显式允许导出带失败清单的部分数据')
    args = parser.parse_args(argv)
    if args.export_only and args.export_json is None:
        parser.error('--export-only requires --export-json')
    try:
        elements = ([item for value in args.elements for item in value.replace(',', ' ').split()]
                    if args.elements is not None else None)
        charges = ([int(item) for value in args.charges for item in value.replace(',', ' ').split()]
                   if args.charges is not None else None)
        if args.export_only:
            manifest = _read_json(args.output_dir / 'manifest.json')
        else:
            manifest = fetch_stark_database(args.output_dir, refresh=args.refresh, delay=args.delay,
                                             elements=elements, charges=charges, workers=args.workers)
        if args.export_json is not None:
            result = export_stark_database(args.output_dir, args.export_json,
                                           allow_partial=args.allow_partial)
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except Exception as exc:
        print('STARK-B 采集失败：{}: {}'.format(type(exc).__name__, exc), file=sys.stderr)
        return 1
    print(json.dumps({key: manifest[key] for key in ('complete', 'scope', 'counts', 'failures')},
                     ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if manifest['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(_cli())
