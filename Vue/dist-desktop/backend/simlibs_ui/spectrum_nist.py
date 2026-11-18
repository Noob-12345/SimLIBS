"""Verified NIST Handbook Persistent Lines client and parser."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = 'https://physics.nist.gov'
PERIODIC_URL = BASE + '/PhysRefData/Handbook/periodictable.htm'
MAX_HTML = 16_000_000
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 18
OVERALL_TIMEOUT = 35
SPECIES = (('I', 3), ('II', 4))


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split())


def _cells(row):
    cells = row.find_all(['th', 'td'], recursive=False)
    if len(cells) < 2:
        cells = row.find_all(['th', 'td'])
    return [_text(cell) for cell in cells]


def _header_map(values):
    normalized = [re.sub(r'[\s.]+', '', value.lower()) for value in values]
    aliases = {
        'intensity': ('intensity',),
        'wavelength': ('wavelength',),
        'aki': ('aki',),
        'energy': ('energylevels', 'energy'),
        'configuration': ('configurations', 'configuration'),
        'term': ('terms', 'term'),
        'j': ('j',),
        'line_ref': ('lineref',),
        'aki_ref': ('akiref',),
    }
    result = {}
    for key, names in aliases.items():
        for index, value in enumerate(normalized):
            if (key == 'aki' and value.startswith('aki') and 'ref' not in value) or (key != 'aki' and any(value == name or (key in ('wavelength', 'energy') and value.startswith(name)) for name in names)):
                result[key] = index
                break
    return result


def _state(row, indices, row_number, units):
    def value(key):
        index = indices.get(key)
        return row[index].strip() if index is not None and index < len(row) else ''
    return {
        'line': row_number,
        'role': 'source row',
        'intensity': value('intensity'),
        'aki': value('aki'),
        'aki_unit': units['aki'],
        'energy': value('energy'),
        'energy_unit': units['energy'],
        'configuration': value('configuration'),
        'term': value('term'),
        'j': value('j'),
        'line_ref': value('line_ref'),
        'aki_ref': value('aki_ref'),
    }


def parse_html(html: bytes, url: str, element: str, species: str):
    """Parse one verified Persistent Lines page, preserving source rows."""
    _safe_url(url)
    if species not in ('I', 'II') or not re.fullmatch(r'[A-Z][a-z]?', element or ''):
        raise ValueError('NIST元素/电离态无效')
    if len(html) > MAX_HTML:
        raise ValueError('NIST响应超过16MB限制')
    soup = BeautifulSoup(html, 'html.parser')
    title = _text(soup.title) if soup.title else ''
    identity = r'\(\s*' + re.escape(element) + r'\s+' + re.escape(species) + r'\s*\)'
    if not title or 'persistent lines' not in title.lower() or not re.search(identity, title):
        raise ValueError(f'NIST页面元素/电离态校验失败：{title or "无标题"}')
    table = None; indices = None; header_values = []
    for candidate in soup.find_all('table'):
        for row in candidate.find_all('tr'):
            if row.find_parent('table') is not candidate:
                continue
            cells = row.find_all(['th', 'td'], recursive=False)
            if any(cell.find('table') for cell in cells):
                continue
            values = [value for value in _cells(row) if value]
            current = _header_map(values)
            if {'intensity', 'wavelength', 'aki', 'energy', 'configuration', 'term', 'j', 'line_ref', 'aki_ref'} <= set(current):
                table, indices, header_values = candidate, current, values
                break
        if table is not None:
            break
    if table is None:
        raise ValueError(f'NIST {element} {species} 无可读取的持久线数据（页面未提供有效Persistent Lines表）')
    if len(header_values) != 9 or 'Å' not in header_values[indices['wavelength']]:
        raise ValueError('NIST表头结构或Å单位不受支持')
    aki_header = header_values[indices['aki']] if indices['aki'] < len(header_values) else ''
    energy_header = header_values[indices['energy']] if indices['energy'] < len(header_values) else ''
    aki_unit = '10^8 s^-1' if re.search(r'10\s*[⁸8]|10\s*\^\s*8', aki_header) else ('s^-1' if 's' in aki_header.lower() else '')
    energy_unit = 'cm^-1' if 'cm' in energy_header.lower() else ('eV' if re.search(r'\bev\b', energy_header, re.I) else '')
    units = {'aki': aki_unit, 'energy': energy_unit}
    positions = {}; current_wavelength = None
    for row_number, row in enumerate(table.find_all('tr'), 1):
        if row.find_parent('table') is not table:
            continue
        values = _cells(row)
        cells = row.find_all(['th', 'td'], recursive=False)
        if len(values) != 9 or not any(values) or any(cell.find('table') for cell in cells):
            current_wavelength = None
            continue
        wavelength = values[indices['wavelength']].strip() if indices['wavelength'] < len(values) else ''
        state = _state(values, indices, row_number, units)
        if not wavelength:
            # Carry a displayed wavelength only for an immediately following
            # source state row. Keep each row independent, never infer a pair.
            if current_wavelength is not None and state['energy']:
                state.update(wavelength_angstrom='', wavelength_nm=current_wavelength / 10)
                positions[current_wavelength].append({'states': [state], 'page_row': row_number, 'wavelength_angstrom': ''})
            else:
                current_wavelength = None
            continue
        try:
            angstrom = float(wavelength.replace(',', ''))
        except ValueError:
            current_wavelength = None
            continue
        if not math.isfinite(angstrom) or not 0 < angstrom < 10_000_000:
            current_wavelength = None
            continue
        current_wavelength = angstrom
        state.update(wavelength_angstrom=wavelength, wavelength_nm=angstrom / 10)
        positions.setdefault(angstrom, []).append({'states': [state], 'page_row': row_number, 'wavelength_angstrom': wavelength})
    if not positions:
        raise ValueError('NIST Persistent Lines表为空')
    digest = hashlib.sha256(html).hexdigest()
    fetched = datetime.now(timezone.utc).isoformat()
    group = {
        'id': hashlib.sha256((url + element + species + digest).encode()).hexdigest()[:32],
        'element': element,
        'species': species,
        'label': f'{element} {species} · NIST Persistent Lines',
        'xs': sorted(value / 10 for value in positions),
        'positions': [dict(wavelength_nm=value / 10, wavelength_angstrom=str(value), records=positions[value]) for value in sorted(positions)],
        'source': url,
        'sha256': digest,
        'original_unit': 'angstrom',
        'unit': 'nm',
        'count': len(positions),
        'originKind': 'nist',
        'unit_contract': 'NIST Handbook table wavelength (Å), converted to nm by /10; no air/vacuum conversion',
        'metadata': {'url': url, 'fetched_at': fetched, 'html_sha256': digest, 'title': title, 'source': 'NIST Handbook Persistent Lines', 'aki_header': aki_header, 'aki_multiplier': 100000000 if aki_unit == '10^8 s^-1' else None, 'energy_header': energy_header, 'row_contract': 'Each source row is independent; no inferred lower/upper pairing.'},
    }
    return group


def _safe_url(url):
    parsed = urlparse(url)
    valid_path = parsed.path == '/PhysRefData/Handbook/periodictable.htm' or re.fullmatch(r'/PhysRefData/Handbook/Tables/[a-z]+table[134]\.htm', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'physics.nist.gov' or parsed.query or parsed.fragment or not valid_path:
        raise ValueError('NIST URL仅允许官方HTTPS Handbook路径')


def _get(session, url, deadline):
    _safe_url(url)
    if time.monotonic() >= deadline:
        raise ValueError('NIST请求超过整体超时')
    remaining = deadline - time.monotonic()
    try:
        with session.get(url, timeout=(min(CONNECT_TIMEOUT, remaining), min(READ_TIMEOUT, remaining)), stream=True, verify=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError(f'NIST HTTP {response.status_code}：{url}')
            _safe_url(response.url)
            if response.url != url or 'html' not in response.headers.get('Content-Type', '').lower():
                raise ValueError('NIST响应URL或Content-Type校验失败')
            if int(response.headers.get('Content-Length', '0')) > MAX_HTML:
                raise ValueError('NIST响应超过16MB限制')
            chunks = []; size = 0
            for chunk in response.iter_content(4096):
                size += len(chunk)
                if size > MAX_HTML:
                    raise ValueError('NIST响应超过16MB限制')
                if time.monotonic() >= deadline:
                    raise ValueError('NIST请求超过整体超时')
                chunks.append(chunk)
            if time.monotonic() >= deadline:
                raise ValueError('NIST请求超过整体超时')
            return b''.join(chunks)
    except requests.RequestException as error:
        raise ValueError('NIST网络/TLS/超时错误：' + str(error)) from error


def element_urls(element: str, session=None, deadline=None):
    if not re.fullmatch(r'[A-Z][a-z]?', element or ''):
        raise ValueError('NIST元素必须是合法元素符号')
    session = session or requests.Session()
    html = _get(session, PERIODIC_URL, deadline or time.monotonic() + OVERALL_TIMEOUT)
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.title or 'nist' not in _text(soup.title).lower() or 'atomic spectroscopic data' not in _text(soup.title).lower():
        raise ValueError('NIST周期表标题校验失败')
    href = None
    for anchor in soup.find_all('a', href=True):
        if _text(anchor) == element:
            href = urljoin(PERIODIC_URL, anchor['href'])
            break
    if not href:
        raise ValueError(f'NIST周期表未找到元素 {element}')
    _safe_url(href)
    parsed = urlparse(href)
    if parsed.scheme != 'https' or parsed.netloc != 'physics.nist.gov' or not re.fullmatch(r'/PhysRefData/Handbook/Tables/[A-Za-z]+table1\.htm', parsed.path):
        raise ValueError('NIST元素链接不属于允许的Handbook路径')
    return {species: href.replace('table1.htm', f'table{table}.htm') for species, table in SPECIES}


def fetch(element: str):
    start = time.monotonic(); deadline = start + OVERALL_TIMEOUT
    session = requests.Session(); session.headers.update({'User-Agent': 'SimLIBS/1.0 NIST Persistent Lines reader'})
    try:
        urls = element_urls(element, session, deadline)
        groups = []; issues = []; states = {}
        for species, url in urls.items():
            try:
                html = _get(session, url, deadline)
                groups.append(parse_html(html, url, element, species)); states[species] = 'available'
            except (requests.RequestException, ValueError) as error:
                states[species] = 'missing'
                issues.append({'file': url, 'error': f'{element} {species}：{error}'})
        if not groups:
            raise ValueError(f'NIST {element} I/II均不可用：' + '; '.join(item['error'] for item in issues))
        result = {'groups': groups, 'issues': issues, 'source': 'NIST Handbook Persistent Lines (online)', 'element': element, 'available_states': states}
        if len(json.dumps(result, ensure_ascii=False).encode()) > 12_000_000:
            raise ValueError('NIST参考响应超过12MB')
        return result
    finally:
        session.close()
