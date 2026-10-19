"""NIST 与 STARK-B 的身份桥接：补齐量子态，严格匹配有来源的系数。

NIST LIBS 网页只有能量/gA。额外请求 ASD TSV，用同源的真空 Ritz 波长、
上下能量和 gA 确认跃迁，再按组态、项、J 匹配 STARK-B。绝不以最近波长替代。
调试断点：parse_identities -> identify -> same_state -> match_width。
"""
from collections import defaultdict
import csv
from fractions import Fraction
import io
import math
import re

import requests

from .stark_b import (SourceCache, StarkBClient, StarkBUnavailable, StarkDataAccessError,
                      evaluate_width, _roman)


ASD_URL = 'https://physics.nist.gov/cgi-bin/ASD/lines1.pl'


def parse_identities(text, *, element, charge, cmev):
    """解析 ASD 真空 nm、能量 cm^-1 导出；保留 NIST 能级 ID 和引用标识。

    缺少 Aki、能量、组态等身份信息的行不用于自动匹配，避免把残缺数据强行
    对上。方括号是 NIST 能量标记，原文保留于快照，数值仍采用同源表值。
    """
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), delimiter='\t')
    required = {'ritz_wl_vac(nm)', 'Aki(s^-1)', 'Ei(cm-1)', 'Ek(cm-1)',
                'conf_i', 'term_i', 'J_i', 'conf_k', 'term_k', 'J_k', 'g_k'}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise ValueError('Unrecognised NIST identity export; expected vacuum wavelengths and cm-1 energies')
    rows = []
    for row in reader:
        try:
            numbers = {key: float(row[key].strip().strip('[]')) for key in
                       ('ritz_wl_vac(nm)', 'Aki(s^-1)', 'Ei(cm-1)', 'Ek(cm-1)', 'g_k')}
        except (ValueError, TypeError, AttributeError):
            continue
        if (not all(math.isfinite(x) for x in numbers.values()) or
                numbers['ritz_wl_vac(nm)'] <= 0 or numbers['Aki(s^-1)'] <= 0 or numbers['g_k'] <= 0):
            continue
        labels = [' '.join(row[k+'_'+suffix].strip() for k in ('conf', 'term', 'J')).strip()
                  for suffix in ('i', 'k')]
        rows.append(dict(element=element, charge=charge, wavelength_nm=numbers['ritz_wl_vac(nm)'],
                         gA_s=numbers['Aki(s^-1)']*numbers['g_k'],
                         lower_eV=numbers['Ei(cm-1)']/cmev, upper_eV=numbers['Ek(cm-1)']/cmev,
                         lower_label=labels[0], upper_label=labels[1],
                         nist_lower_id=row.get('ID_i', ''), nist_upper_id=row.get('ID_k', ''),
                         nist_transition_reference=row.get('tp_ref', ''), nist_line_reference=row.get('line_ref', '')))
    return rows


def identify(line, identities):
    """数值身份同时一致才接入量子态；只容忍浮点运算的四个 ULP 舍入误差。"""
    keys = ('wavelength_nm', 'gA_s', 'lower_eV', 'upper_eV')
    candidates = [row for row in identities if row['element'] == line['element'] and row['charge'] == line['charge']
                  and all(abs(row[key]-line[key]) <= 4*max(math.ulp(row[key]), math.ulp(line[key])) for key in keys)]
    if len(candidates) > 1:
        raise ValueError(f'Ambiguous NIST identity for {line["element"]} {line["wavelength_nm"]} nm')
    return candidates[0] if candidates else None


def _state(label):
    """拆分组态/项/J；只统一 o 与 * 的奇宇称写法，保留母项与项前缀。"""
    tokens = label.strip().split()
    if len(tokens) < 2:
        return None
    j = None
    if re.fullmatch(r'\d+(?:/\d+|\.\d+)?', tokens[-1]):
        try:
            j = Fraction(tokens.pop())
        except ZeroDivisionError:
            return None
        if j < 0 or (2*j).denominator != 1:
            return None
    term = tokens.pop()
    if tokens and re.fullmatch('[a-z]', tokens[-1]):
        term = tokens.pop()+term
    # 只自动处理明确的 LS 项；问号、多值 J 和未知耦合不能变成通配符。
    if not re.fullmatch(r'[a-z]?\d+[SPDFGHIKLMNOQRTUVWXYZ](?:o|\*)?', term) or not tokens:
        return None
    configuration = ''.join(tokens)
    def parity(value):
        return re.sub(r'(?<=[SPDFGHIKLMNOQRTUVWXYZ])o(?=\)|$)', '*', value)
    configuration = parity(re.sub(r'\s+', '', configuration))
    configuration = configuration.replace('.(', '(')
    return configuration, parity(term), j


def same_state(database_label, nist_label):
    """组态和项必须相同；STARK-B 明确不分辨 J 时允许覆盖该多重态的分量。

    若 STARK-B 给出 J，则 NIST 也必须给出同一 J。不删母项、项编号或芯层；
    来源使用不同命名且不能证明等价时，返回不匹配而不扩大波长容差。
    """
    a, b = _state(database_label), _state(nist_label)
    return bool(a and b and b[2] is not None and a[:2] == b[:2] and (a[2] is None or a[2] == b[2]))


def match_width(line, identity, tables, *, temperature_k, ne, methods=('SCP', 'MSE')):
    """匹配态后检查适用条件；同优先级多来源直接报歧义，不取平均或猜选。

    methods 是明确的方法优先序。每种方法内优先使用给出更多 J 的逐线记录，
    没有逐线记录时才用数据库明确给出的多重态记录并保留匹配方式。
    """
    if identity is None:
        return None, 'NIST numerical transition identity not found'
    candidates = [r for r in tables if r['element'] == line['element'] and r['charge'] == line['charge']
                  and same_state(r['lower_label'], identity['lower_label'])
                  and same_state(r['upper_label'], identity['upper_label'])]
    reasons = []
    for method in methods:
        usable = []
        for row in candidates:
            if row['method'] != method:
                continue
            try:
                width = evaluate_width(row, temperature_k=temperature_k, ne=ne, wavelength_nm=line['wavelength_nm'])
            except StarkBUnavailable as exc:
                reasons.append(str(exc))
                continue
            specificity = sum(_state(row[k])[2] is not None for k in ('lower_label', 'upper_label'))
            usable.append((specificity, row, width))
        if usable:
            best = max(item[0] for item in usable)
            usable = [item for item in usable if item[0] == best]
            if len(usable) > 1:
                raise ValueError(f'Ambiguous STARK-B sources for {line["element"]} {line["wavelength_nm"]} nm ({method})')
            _, row, width = usable[0]
            width.update(stark_match='configuration/term/J' if best == 2 else 'configuration/term (published multiplet)',
                         stark_lower_label=row['lower_label'], stark_upper_label=row['upper_label'],
                         stark_snapshot_sha256=row.get('snapshot_sha256'), stark_retrieved_utc=row.get('retrieved_utc'),
                         **{k: v for k, v in identity.items() if k.startswith('nist_')})
            return dict(line, **width), ''
    if candidates and not reasons:
        reasons.append('no enabled calculation method')
    return None, '; '.join(sorted(set(reasons))) or 'no matching configuration/term/J state pair'


def _fetch_identities(element, charge, low, high):
    """按物种/窗口请求 ASD 全量 TSV，禁用页面分页，固定单位和输出字段。"""
    params = dict(spectra=element+' '+_roman(charge+1), output_type=0, low_w=low, upp_w=high,
                  unit=1, de=0, plot_out=0, format=3, line_out=0, remove_js='on', no_spaces='on',
                  en_unit=0, output=0, bibrefs=1, page_size=100, show_obs_wl=1, show_calc_wl=1,
                  unc_out=1, order_out=0, ids_out=1, show_av=3, A_out=0, allowed_out=1, forbid_out=1,
                  conf_out='on', term_out='on', enrg_out='on', J_out='on', g_out='on')
    # 复用有限重试与 TLS 检查；TSV 是纯数据，不执行页面脚本。
    with requests.Session() as session:
        text = StarkBClient._request(session, 'GET', ASD_URL, params=params)
    url = requests.Request('GET', ASD_URL, params=params).prepare().url
    return dict(text=text, url=url)


def resolve_online(records, *, te, ne, cmev, cache_dir=None, allow_network=True, methods=('SCP', 'MSE')):
    """按物种批量获取，不逐线联网；返回已匹配和带原因的缺失行，保持输入次序。

    网络/源格式错误不伪装成物理无数据；缺失原因区分物种、密度、量子态和温度。
    Te 从 eV 转 K 后只使用已发布的温度数据，随后渲染和重新采样不再联网。
    """
    from scipy.constants import e, k
    cache = SourceCache(cache_dir, allow_network=allow_network)
    client = StarkBClient(cache)
    groups = defaultdict(list)
    for index, line in enumerate(records):
        groups[(line['element'], line['charge'])].append((index, line))
    found, missing = {}, {}
    for (element, charge), indexed in groups.items():
        tables, document = client.species(element, charge, ne)
        identities = []
        if tables:
            low = max(0, min(line['wavelength_nm'] for _, line in indexed)-.05)
            high = max(line['wavelength_nm'] for _, line in indexed)+.05
            key = f'nist-asd-identity-v1:{element}:{charge}:{low:.12g}:{high:.12g}'
            def fetch_validated():
                """先验证纯数据响应再写快照，防止临时 HTTP 200 错误页污染缓存。"""
                payload = _fetch_identities(element, charge, low, high)
                try:
                    parse_identities(payload['text'], element=element, charge=charge, cmev=cmev)
                except ValueError as exc:
                    raise StarkDataAccessError(f'NIST identity response invalid: {payload["url"]}: {exc}') from exc
                return payload
            snapshot = cache.get(key, fetch_validated)
            identities = parse_identities(snapshot['payload']['text'], element=element, charge=charge, cmev=cmev)
        for index, line in indexed:
            out, reason = match_width(line, identify(line, identities), tables, temperature_k=te*e/k, ne=ne, methods=methods)
            if out is not None:
                found[index] = out
            else:
                if not tables:
                    data = document['payload']
                    reason = data.get('status') or '; '.join(sorted(set(d.get('status', 'no electron data') for d in data['datasets'])))
                missing[index] = dict(line, stark_missing_reason=reason, stark_width_nm=None)
    return found, missing
