"""Task-local transport/cache/error bridge; upstream Stark algorithms stay byte-identical."""
from contextlib import contextmanager, ExitStack
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import time
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup


def cache_directory():
    """Only trusted process configuration selects a path, never an HTTP parameter."""
    if os.environ.get('SIMLIBS_STARK_CACHE_DIR'):
        return Path(os.environ['SIMLIBS_STARK_CACHE_DIR']).expanduser().resolve()
    if os.environ.get('SIMLIBS_STATE_DIR'):
        return Path(os.environ['SIMLIBS_STATE_DIR']).resolve()/'cache'/'stark-v1'
    root = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))
    return root/'simLIBS'/'stark-v1'


def json_value(value):
    """Preserve nested ranges and optional values in strict JSON, including mixed-source rows."""
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class StarkTransport:
    def __init__(self, settings, cancelled, report, request=None):
        self.settings, self.cancelled, self.report = settings, cancelled, report
        self.request = request
        self.evidence, self.snapshots = [], []
        self.response_bytes = 0

    @contextmanager
    def stage(self, condition, progress):
        """Each worker owns its imports; patches are scoped and restored even on cancellation."""
        source = importlib.import_module('simLIBS.stark_b')
        identities = importlib.import_module('simLIBS.nist_stark')
        resolver = importlib.import_module('simLIBS.stark_resolver')
        access_error = source.StarkDataAccessError
        end = time.monotonic()+min(600., max(180., self.settings.static_deadline*3))
        current_message = ['Stark数据级联']
        last_response = {}

        def failure(message, code='stark_data_access'):
            error = access_error(message)
            error.code = code
            return error

        def check():
            if self.cancelled():
                raise InterruptedError('高级Stark取数已取消')
            if time.monotonic() >= end:
                raise failure('Stark取数阶段超过有限时限', 'stark_timeout')

        def announce(message):
            check()
            current_message[0] = message
            self.report(progress, condition+'：'+message, max(1., end-time.monotonic())+10)

        def pause(seconds):
            until = min(end, time.monotonic()+seconds)
            while time.monotonic() < until:
                check()
                time.sleep(min(.05, max(0, until-time.monotonic())))

        def bounded_request(session, method, url, **kwargs):
            kwargs.pop('timeout', None)
            for attempt in range(3):
                announce(current_message[0])
                remaining = end-time.monotonic()
                response = None
                try:
                    send = self.request or session.request
                    response = send(method, url, stream=True,
                                    timeout=(min(self.settings.connect_timeout, remaining), min(self.settings.read_timeout, remaining)),
                                    verify=self.settings.tls_verify, **kwargs)
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        check()
                        size += len(chunk)
                        if size > 4_000_000 or self.response_bytes+size > 32_000_000:
                            raise failure('Stark/身份响应超过大小上限', 'stark_response_size')
                        chunks.append(chunk)
                    content = b''.join(chunks)
                    check()
                    text = content.decode('utf-8-sig')
                    if BeautifulSoup(text, 'html.parser').select_one('#error') is not None:
                        raise failure('STARK-B / NIST服务返回错误页面', 'stark_service_format')
                    self.response_bytes += size
                    self.evidence.append(dict(method=method, url=getattr(response, 'url', None) or url,
                                              response_sha256=hashlib.sha256(content).hexdigest(), bytes=size))
                    last_response.update(status_code=getattr(response, 'status_code', 200),
                                         headers=dict(getattr(response, 'headers', {})))
                    return text
                except requests.RequestException as error:
                    status = getattr(getattr(error, 'response', None), 'status_code', None)
                    if isinstance(error, requests.exceptions.SSLError) or attempt == 2 or (status is not None and status not in (429,500,502,503,504)):
                        raise failure('Stark数据请求失败：'+str(error), 'stark_network') from error
                    pause(.5*(attempt+1))
                except UnicodeError as error:
                    raise failure('Stark/身份响应编码错误', 'stark_service_format') from error
                finally:
                    if response is not None:
                        response.close()

        original_cache = source.SourceCache.get
        def cached(cache, key, fetch):
            check()
            path = cache.directory/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            hit = path.exists()
            try:
                document = original_cache(cache, key, fetch)
            except InterruptedError:
                raise
            except access_error as error:
                if not hasattr(error, 'code'):
                    error.code = 'stark_cache_corrupt' if 'integrity error' in str(error) else 'stark_cache_miss' if 'network is disabled' in str(error) else 'stark_service_format'
                raise
            except OSError as error:
                raise failure('Stark缓存读写失败：'+str(error), 'stark_cache_io') from error
            check()
            self.snapshots.append(dict(key=key, cache_hit=hit, sha256=document['sha256'], retrieved_utc=document['retrieved_utc']))
            parts = key.split(':')
            species = parts[1]+' '+source._roman(int(parts[2])+1) if len(parts)>2 and parts[2].isdigit() else ''
            label = 'NIST' if key.startswith('nist-') else 'STARK-B'
            announce(label+'：'+species+'，'+('读取已校验缓存' if hit else '已校验并保存来源缓存'))
            return document

        def checked_parser(parser):
            def wrapped(*args, **kwargs):
                check()
                try:
                    return parser(*args, **kwargs)
                except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
                    raise failure('Stark/身份数据格式错误：'+str(error), 'stark_service_format') from error
            return wrapped

        try:
            class MockResponse:
                def __init__(self, text):
                    self.text = text
                    self.content = text.encode('utf-8')
                    self.status_code = last_response['status_code']
                    self.headers = last_response['headers']
                def raise_for_status(self):
                    pass
            def vamdc_get(url, **kwargs):
                with requests.Session() as session:
                    res = bounded_request(session, 'GET', url, **kwargs)
                return MockResponse(res)
            with ExitStack() as stack:
                stack.enter_context(patch.object(source.StarkBClient, '_request', staticmethod(bounded_request)))
                stack.enter_context(patch.object(source.SourceCache, 'get', cached))
                stack.enter_context(patch.object(source, 'parse_table', checked_parser(source.parse_table)))
                stack.enter_context(patch.object(identities, 'parse_identities', checked_parser(identities.parse_identities)))
                stack.enter_context(patch.object(resolver, 'report_progress', announce))
                stack.enter_context(patch.object(resolver, 'check_cancelled', check))
                try:
                    vamdc = importlib.import_module('simLIBS.stark_vamdc')
                    stack.enter_context(patch.object(vamdc.requests, 'get', vamdc_get))
                except ImportError:
                    pass
                yield
                check()
        except ValueError as error:
            if str(error).startswith('Ambiguous '):
                error.code = 'stark_ambiguous'
            raise
        except access_error as error:
            if not getattr(error, 'code', None):
                error.code = 'stark_service_format'
            raise


def merge_missing(rows):
    """One editable coefficient row per identity; retain all conditions/reasons as JSON text."""
    keys = ('element','charge','wavelength_nm','lower_eV','upper_eV','gA_s')
    groups = {}
    for row in rows:
        key = tuple(row.get(name) for name in keys)
        group = groups.setdefault(key, dict(row, conditions=[], condition_details=[]))
        if row['condition'] not in group['conditions']:
            group['conditions'].append(row['condition'])
        detail = {name: row.get(name) for name in ('condition','Te_eV','Ne_cm3','stark_missing_reason',
                                                  'stark_b_missing_reason','stark_mse_missing_reason',
                                                  'stark_layer_reasons','stark_access_failures')}
        if detail not in group['condition_details']:
            group['condition_details'].append(detail)
    for group in groups.values():
        group['condition'] = ' / '.join(group['conditions'])
        group['stark_missing_reason'] = ' / '.join(dict.fromkeys(d['stark_missing_reason'] or '' for d in group['condition_details']))
        group['condition_details'] = json.dumps(json_value(group['condition_details']), ensure_ascii=False, allow_nan=False)
        group['conditions'] = json.dumps(group['conditions'], ensure_ascii=False)
    return list(groups.values())
