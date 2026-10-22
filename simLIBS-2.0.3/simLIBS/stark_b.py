"""STARK-B 数据组件：取表、缓存、解析以及有出处的温度/密度换算。

优先使用官网表格；网页不可用时改用官方版本化 VAMDC 服务。
VAMDC 查询须补齐截断结果；未导出的拟合、方法和 C 参数明确记为未知。
本组件不按邻近波长猜跃迁；能级身份匹配交给 nist_stark 组件。
调试顺序：StarkBClient.species -> parse_table -> evaluate_width。
物理约定见 https://stark-b.obspm.fr/index.php/description ：表内 w 是
电子 FWHM（Angstrom），当前渲染器的 W 是参考电子密度下的半个 FWHM。
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import requests


BASE = 'https://stark-b.obspm.fr'
DESCRIPTION = BASE+'/index.php/description'


class StarkDataAccessError(RuntimeError):
    """网络、服务格式或缓存异常；区别于某条跃迁确实没有系数。"""


class StarkBUnavailable(ValueError):
    """已找到来源，但该跃迁/等离子体条件不能采用该记录。"""


class SourceCache:
    """保存原始响应的可复现快照；完整写入后原子替换，不缓存请求失败。

    allow_network=False 只读已有快照。sha256 校验 payload 是否损坏；缓存键
    包括源、版本、物种和密度，避免不同条件错误复用。默认位于用户缓存目录。
    """
    def __init__(self, directory=None, *, allow_network=True):
        root = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))
        self.directory = Path(directory) if directory is not None else root/'simLIBS'/'stark-v1'
        self.allow_network = allow_network

    def get(self, key, fetch):
        """命中时校验并返回快照；未命中才执行 fetch 并保存来源时间。"""
        path = self.directory/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        if path.exists():
            try:
                document = json.loads(path.read_text(encoding='utf-8'))
                digest = self._digest(document['payload'])
                if document['key'] != key or digest != document['sha256']:
                    raise ValueError('checksum mismatch')
                return document
            except (ValueError, KeyError, TypeError) as exc:
                raise StarkDataAccessError(f'Stark cache integrity error: {path}') from exc
        if not self.allow_network:
            raise StarkDataAccessError(f'No Stark cache snapshot for {key}; network is disabled')
        payload = fetch()
        document = dict(key=key, payload=payload, sha256=self._digest(payload),
                        retrieved_utc=datetime.now(timezone.utc).isoformat())
        self.directory.mkdir(parents=True, exist_ok=True)
        # 并发进程使用各自临时文件，避免相互覆盖未完成的 JSON。
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.directory,
                                             suffix='.tmp', delete=False) as out:
                temporary = Path(out.name)
                json.dump(document, out, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return document

    @staticmethod
    def _digest(payload):
        """排序后的 UTF-8 JSON 用于稳定校验，不依赖字典插入顺序。"""
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()


def _numeric(text):
    """读取表格正负科学计数值；空格为缺失，非有限数视作源格式错误。"""
    if not text.strip():
        return None
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('Nonfinite STARK-B table value')
    return value


def parse_table(html, *, element, charge, dataset_id, method):
    """解析官网电子碰撞列，保留状态标签、表值、已发布拟合及原文献。

    不读取质子/离子列作为电子宽度；不丢弃空值和星号，后续有效性判断需要它们。
    samples 的 density 来自宽度表；fit 的 density 单独读取，因为官网密度插值
    页面会保留原始参考密度的拟合系数，二者可能不同。
    """
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.select_one('#shiftings table')
    if table is None:
        raise ValueError('STARK-B response lacks width table')
    heads = table.select('thead tr')
    colliders = [x.get_text(' ', strip=True).lower() for x in heads[0].find_all('th')[1:]]
    if 'electron' not in colliders:
        raise ValueError('STARK-B table lacks electron collider')
    column = 8+4*colliders.index('electron')
    names = [x.get_text(' ', strip=True) for x in heads[-1].find_all('th')]
    if names[column:column+2] != ['*w', 'w (Å)']:
        raise ValueError('Unknown STARK-B electron width convention')
    references = soup.select_one('#references')
    if references is None:
        raise ValueError('STARK-B response lacks bibliography')
    source = references.get_text(' ', strip=True)
    source += ' '+ ' '.join(a['href'] for a in references.select('a[href]'))
    records = {}
    for tr in table.select('tbody tr'):
        cells = [x.get_text(' ', strip=True) for x in tr.find_all('td')]
        if len(cells) != len(names):
            raise ValueError('Inconsistent STARK-B width table columns')
        key = (cells[1], cells[2], cells[4])
        if key not in records:
            records[key] = dict(element=element, charge=charge, dataset_id=str(dataset_id), method=method,
                                lower_label=cells[1], upper_label=cells[2],
                                calculated_wavelength_angstrom=_numeric(cells[4]),
                                c_angstrom_cm3=_numeric(cells[5]), samples=[], fit=None,
                                source=source, source_url=DESCRIPTION)
        records[key]['samples'].append(dict(ne=_numeric(cells[0]), temperature_k=_numeric(cells[6]),
                                            flag=cells[column], fwhm_angstrom=_numeric(cells[column+1])))
    fit_table = soup.select_one('#fits table')
    if fit_table is not None:
        fit_heads = fit_table.select('thead tr')
        species = [x.get_text(' ', strip=True).lower() for x in fit_heads[0].find_all('th')[1:]]
        if 'electron' in species:
            start = 6+6*species.index('electron')
            for tr in fit_table.select('tbody tr'):
                cells = [x.get_text(' ', strip=True) for x in tr.find_all('td')]
                key = tuple(cells[i] for i in (1, 2, 4))
                coefficients = [_numeric(x) for x in cells[start:start+3]]
                if key in records and len(coefficients) == 3 and all(x is not None for x in coefficients):
                    records[key]['fit'] = dict(ne=_numeric(cells[0]), coefficients=coefficients)
    return list(records.values())


def evaluate_width(row, *, temperature_k, ne, wavelength_nm):
    """采用表值或已发布的 log10 温度拟合，转换为渲染器的 W 与出处。

    不做温度外推。只允许向较低密度线性缩放；密度插值由官网查询服务完成。
    官网允许按 (实测波长/计算波长)^2 换算线宽；匹配身份必须先独立确认。
    C 为空时明确记录隔离线密度上限未知，不虚构有效性保证。
    """
    for name, value in [('temperature', temperature_k), ('density', ne), ('wavelength', wavelength_nm)]:
        if not math.isfinite(value) or value <= 0:
            raise ValueError('STARK-B '+name+' must be finite and positive')
    samples = sorted(row['samples'], key=lambda x: x['temperature_k'])
    # eV/K 往返产生的个位 ULP 差异不算温度外推。
    if samples:
        for bound in (samples[0]['temperature_k'], samples[-1]['temperature_k']):
            if abs(temperature_k-bound) <= 4*max(math.ulp(temperature_k), math.ulp(bound)):
                temperature_k = bound
    if not samples or not samples[0]['temperature_k'] <= temperature_k <= samples[-1]['temperature_k']:
        raise StarkBUnavailable('temperature outside tabulated range')
    exact = [s for s in samples if math.isclose(s['temperature_k'], temperature_k, rel_tol=1e-10)]
    if exact:
        used = exact
        width = exact[0]['fwhm_angstrom']
        reference_ne = exact[0]['ne']
        temperature_method = 'tabulated'
    else:
        below = max((s for s in samples if s['temperature_k'] < temperature_k), key=lambda s:s['temperature_k'])
        above = min((s for s in samples if s['temperature_k'] > temperature_k), key=lambda s:s['temperature_k'])
        used = [below, above]
        fit = row['fit']
        if fit is None:
            if (row.get('source_format') != 'vamdc-xsams' or
                    row.get('temperature_interpolation') != 'linear'):
                raise StarkBUnavailable('no published temperature fit')
            if below['ne'] != above['ne']:
                raise StarkBUnavailable('mixed reference density in temperature interpolation')
            if any(s['fwhm_angstrom'] is None or s['fwhm_angstrom'] <= 0 for s in used):
                raise StarkBUnavailable('missing electron width for temperature interpolation')
            fraction = (temperature_k-below['temperature_k'])/(above['temperature_k']-below['temperature_k'])
            width = below['fwhm_angstrom'] + fraction*(above['fwhm_angstrom']-below['fwhm_angstrom'])
            reference_ne = below['ne']
            temperature_method = 'linear interpolation of tabulated widths'
        else:
            a0, a1, a2 = fit['coefficients']
            x = math.log10(temperature_k)
            width = 10**(a0+a1*x+a2*x*x)
            reference_ne = fit['ne']
            temperature_method = 'published log10 fit'
    if any(s['flag'] or s['fwhm_angstrom'] is None or s['fwhm_angstrom'] <= 0 for s in used):
        raise StarkBUnavailable('impact validity flag or missing electron width')
    # 拟合的原始密度可高于查询后的表密度；两者均约束外推方向。
    if ne > min(reference_ne, *(s['ne'] for s in used))*(1+1e-12):
        raise StarkBUnavailable('density above available reference density')
    # C 与宽度表的密度成对。拟合有自己的参考密度，先换到表密度再做 C/W，
    # 不把用户降低 Ne 后变窄的 W 混入该上限公式。
    c_reference_ne = used[0]['ne']
    width_at_c_reference = width*c_reference_ne/reference_ne
    limit = row['c_angstrom_cm3']/width_at_c_reference if row['c_angstrom_cm3'] is not None else None
    if limit is not None and ne >= limit:
        raise StarkBUnavailable('isolated line approximation density limit exceeded')
    width *= ne/reference_ne
    ratio = wavelength_nm*10/row['calculated_wavelength_angstrom']
    w_nm = width*.1*ratio**2/2
    if not math.isfinite(w_nm) or w_nm <= 0:
        raise StarkBUnavailable('invalid converted width')
    return dict(stark_width_nm=w_nm, stark_reference_ne_cm3=ne,
                stark_source='STARK-B: '+row['source'], stark_dataset_id=row['dataset_id'],
                stark_method=row['method'], stark_temperature_k=temperature_k,
                stark_temperature_method=temperature_method,
                stark_temperature_bracket_k=[s['temperature_k'] for s in used],
                stark_table_reference_ne_cm3=reference_ne,
                stark_source_format=row.get('source_format', 'html'),
                stark_temperature_range_k=[samples[0]['temperature_k'], samples[-1]['temperature_k']],
                stark_isolated_limit_cm3=limit,
                stark_wavelength_scale=ratio**2, stark_source_url=row['source_url'])


class StarkBClient:
    """每物种/密度读取一次完整数据集并缓存；Session 隔离官网表单状态。

    逐个 dataset 查询，保留不同方法的记录以供匹配层检测歧义。超过数据集最大
    电子密度时记录状态并跳过该数据集，不擅自向高密度外推。
    """
    def __init__(self, cache):
        self.cache = cache
        self._prefer_vamdc = False
        self._html_error = None

    def species(self, element, charge, ne):
        """返回 (完整候选表, 来源快照)；缺少物种与取数失败分别处理。"""
        if not re.fullmatch('[A-Z][a-z]?', element) or type(charge) is not int or charge < 0:
            raise ValueError('Invalid Stark species')
        key = f'stark-b-html-v1:{element}:{charge}:ne={ne:.12g}'
        def fetch_validated():
            payload = self._fetch(element, charge, ne)
            self._parse_payload(payload, element=element, charge=charge, ne=ne)
            return payload
        # 保留历史缓存键以兼容已有快照；实际格式由 payload.format 标识。
        document = self.cache.get(key, fetch_validated)
        rows = self._parse_payload(document['payload'], element=element, charge=charge, ne=ne)
        for row in rows:
            row['snapshot_sha256'] = document['sha256']
            row['retrieved_utc'] = document['retrieved_utc']
        return rows, document

    @staticmethod
    def _parse_payload(payload, *, element, charge, ne):
        """缓存前后均校验来源；HTML 舍入密度与 VAMDC 原始参考密度分别处理。"""
        try:
            if payload.get('format') == 'vamdc-xsams':
                from .stark_vamdc import parse_payload
                return parse_payload(payload, element=element, charge=charge, ne=ne)
            rows = []
            for data in payload['datasets']:
                if 'html' not in data:
                    continue
                parsed = parse_table(data['html'], element=element, charge=charge,
                                     dataset_id=data['id'], method=data['method'])
                for row in parsed:
                    row['source_url'] = data['url']
                    for sample in row['samples']:
                        printed = sample['ne']
                        if printed is None or printed <= 0:
                            raise ValueError('missing or invalid table density')
                        rounding = .5*10**(math.floor(math.log10(printed))-3)
                        if abs(printed-ne) > rounding*(1+1e-12):
                            raise ValueError(f'response density {printed:g} differs from requested density {ne:g}')
                        sample['printed_ne_cm3'] = printed
                        sample['ne'] = ne
                rows.extend(parsed)
            return rows
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise StarkDataAccessError(f'Invalid STARK-B source for {element} charge={charge}: {exc}') from exc

    @staticmethod
    def _request(session, method, url, **kwargs):
        """正常验证 TLS，HTTP/页面错误作为取数异常抛出，避免伪报成缺失谱线。"""
        timeout = kwargs.pop('timeout', 60)
        source = 'NIST ASD' if urlsplit(url).hostname == 'physics.nist.gov' else 'STARK-B'
        for attempt in range(3):
            try:
                response = session.request(method, url, timeout=timeout, **kwargs)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if attempt == 2 or (status is not None and status not in (429, 500, 502, 503, 504, 522)):
                    raise StarkDataAccessError(f'{source} data request failed: {url}: {exc}') from exc
                # 这里的 POST 只选择查询条件，不提交数据；暂时断连可安全重试。
                time.sleep(.5*(attempt+1))
        soup = BeautifulSoup(response.text, 'html.parser')
        if soup.select_one('#error') is not None:
            raise StarkDataAccessError(f'{source} service error: {url}: {soup.get_text(" ", strip=True)}')
        return response.text

    def _fetch(self, element, charge, ne):
        """网页源失败时使用正式 VAMDC 接口；同次模拟不反复请求已失败的网页。"""
        if not self._prefer_vamdc:
            try:
                return self._fetch_html(element, charge, ne)
            except (StarkDataAccessError, ValueError, IndexError) as exc:
                self._html_error = str(exc)
                self._prefer_vamdc = True
        from .stark_vamdc import fetch_species
        try:
            return fetch_species(element, charge, ne)
        except (requests.RequestException, ValueError) as exc:
            raise StarkDataAccessError(
                f'STARK-B data access failed for {element} charge={charge}, Ne={ne:g}; '
                f'HTML source: {self._html_error}; VAMDC source: {exc}') from exc

    def _fetch_html(self, element, charge, ne):
        """只读官网表单：元素 -> 电离阶段 -> 数据集 -> 密度 -> 完整表。"""
        with requests.Session() as session:
            def post(action, *, request_timeout=60, **params):
                return self._request(session, 'POST', BASE+'/index.php',
                                     timeout=request_timeout,
                                     data=dict(module='stark_b', action=action, **params))
            # 首步仅取元素列表；不可用时尽快切换后端，避免连续三个 60 秒等待。
            html = post('periodictable:datasets', element=element, request_timeout=(5, 10))
            soup = BeautifulSoup(html, 'html.parser')
            # 网站的电离阶段罗马数字由调用处的 charge 唯一生成。
            roman = _roman(charge+1)
            links = [a for a in soup.select('a[href]') if a.get_text(' ', strip=True) == element+' '+roman]
            if not links:
                if soup.select_one('#ion-datasets') is None:
                    raise StarkDataAccessError('Unrecognised STARK-B species listing')
                return dict(element=element, charge=charge, datasets=[], status='species not available')
            url = BASE+links[0]['href']
            ion_html = self._request(session, 'GET', url)
            options = BeautifulSoup(ion_html, 'html.parser').select('#dataset option')
            if not options:
                raise StarkDataAccessError('STARK-B dataset selector missing')
            datasets = []
            for option in options:
                if option.get('value') == '-1':
                    continue
                label = option.get_text(' ', strip=True)
                if 'electron' not in label.lower():
                    continue
                identifier = option['value']
                method = label.split('method :')[-1].strip()
                density_html = post('querypage:densities', datasetId=identifier)
                densities = [_numeric(o['value']) for o in BeautifulSoup(density_html, 'html.parser').select('#density option')
                             if re.fullmatch(r'[\d.eE+\-]+', o.get('value', '')) and _numeric(o['value']) > 0]
                if not densities:
                    raise StarkDataAccessError(f'STARK-B density selector missing: dataset {identifier}')
                data = dict(id=identifier, method=method, url=url, maximum_ne_cm3=max(densities))
                if ne > max(densities)*(1+1e-12):
                    data['status'] = 'density above available tables'
                else:
                    exact_density = next((n for n in densities if math.isclose(n, ne, rel_tol=1e-12)), None)
                    if exact_density is not None:
                        # 官网在已有密度处拒绝 interpolation 请求，必须走普通表单链。
                        post('querypage:transitions', density=f'{exact_density:.12g}')
                        post('querypage:temperatures', transition='all')
                        data['html'] = post('querypage:query', queryType='density', temperature='all', format='html')
                    else:
                        data['html'] = post('querypage:query', queryType='interpolatedDensity', density=f'{ne:.12g}', format='html')
                    parse_table(data['html'], element=element, charge=charge, dataset_id=identifier, method=method)
                datasets.append(data)
            return dict(element=element, charge=charge, requested_ne_cm3=ne, datasets=datasets)


def _roman(value):
    """只用于官网电离阶段标签，charge=0 对应 I。"""
    out = ''
    for n, symbol in [(100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'),
                      (5, 'V'), (4, 'IV'), (1, 'I')]:
        count, value = divmod(value, n)
        out += symbol*count
    return out
