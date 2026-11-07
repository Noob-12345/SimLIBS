"""将 STARK-B 电子 FWHM 与修正半经验模型逐点比较。

只在显式调用函数或 CLI 子命令时工作；导入本模块不抓取、不读写文件、
不加载绘图库。数据库与模型共同使用原表的 T、Ne 和计算波长，不插值。
抓取范围默认全部物种，模型计算范围始终限于实际电荷 q=2、3。
原子输入依赖 stark_atomic_data 的严格身份键，绝不只按波长匹配。

输出 comparison.csv、skipped.csv、summary.json、中文 report.md；有有效
比较且 matplotlib 可用时生成 Agg 四面板 comparison.png。零有效点不画
占位图，也不据此得出精度结论。显式 MSE 参考表单独分层。
CLI 选项建议放在子命令之后；--elements/--charges 仅限制抓取阶段，
compare 与 fetch-atomic 读取指定缓存中的全部表。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import warnings
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path


REFERENCE_DENSITY_CM3 = 1e17
MODEL_METHOD = 'Dimitrijevic-Konjevic 1980 MSE, Eqs. (6)-(10)'
SUPPORTED_CHARGES = (2, 3)

_IDENTITY_FIELDS = (
    'element', 'charge', 'dataset_id', 'transition_id', 'lower_label',
    'upper_label', 'lower_state_id', 'upper_state_id', 'source', 'source_ids',
    'source_url', 'source_format', 'calculated_wavelength_angstrom',
)
_CSV_FIELDS = (
    'key', 'line_id', 'table_index', 'sample_index', 'record_kind', 'element',
    'charge', 'dataset_id', 'transition_id', 'lower_label', 'upper_label',
    'lower_state_id', 'upper_state_id', 'wavelength_nm',
    'calculated_wavelength_angstrom', 'temperature_k', 'electron_density_cm3',
    'fwhm_db_angstrom', 'fwhm_db_nm', 'fwhm_model_nm', 'alpha_db_nm_cm3',
    'alpha_model_nm_cm3', 'fwhm_db_at_1e17_nm', 'fwhm_model_at_1e17_nm',
    'signed_relative_error_percent', 'absolute_relative_error_percent',
    'ratio', 'log10_ratio', 'source', 'source_ids', 'method',
    'reference_method_family', 'reference_independence', 'atomic_quality',
    'atomic_source', 'atomic_status', 'atomic_reason', 'flag',
    'c_angstrom_cm3', 'isolation_status', 'isolation_density_limit_cm3',
    'model_method', 'reason_code', 'reason', 'reason_codes', 'source_url',
    'source_format', 'environment_id', 'collider_ref', 'table_metadata',
    'sample_metadata', 'atomic_metadata',
)


def _plain(value):
    """将元数据变为严格 JSON 值；非有限原始数值以文字保留。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


def _number(value, name, *, zero=False):
    """校验有限数值，拒绝布尔值、缺失值和不合法的符号。"""
    if isinstance(value, bool) or value is None:
        raise ValueError(f'{name} 必须是有限数值')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f'{name} 不是合法数值: {value!r}') from exc
    if not math.isfinite(number) or (number < 0 if zero else number <= 0):
        qualifier = '非负' if zero else '正'
        raise ValueError(f'{name} 必须是有限{qualifier}数值: {value!r}')
    return number


def _integer(value, name):
    """读取整数，拒绝布尔值和被 int 静默截断的小数。"""
    if isinstance(value, bool) or value is None:
        raise ValueError(f'{name} 必须是整数')
    try:
        result = int(value)
        if float(value) != result:
            raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f'{name} 必须是整数: {value!r}') from exc
    return result


def _reference_family(method):
    """仅按明确报告的方法识别 MSE，不从文献或来源猜测方法。"""
    text = str(method).strip().lower()
    if text in ('', 'unreported', 'unknown', 'none', 'n/a'):
        return 'unreported'
    if (re.search(r'\bmse\b', text) or
            re.search(r'modified[\s_-]+semi[\s_-]*empirical', text) or
            '修正半经验' in text):
        return 'reference-mse'
    return 'other-reported'


def _context(table, table_index, key):
    """保留表的身份、来源及未知条件，供成功和跳过记录共用。"""
    out = {name: _plain(table.get(name)) for name in _IDENTITY_FIELDS}
    method = table.get('method')
    method = str(method).strip() if method is not None else ''
    out.update(
        key=key, line_id=key, table_index=table_index, sample_index=None,
        record_kind='table', method=method or 'unreported',
        reference_method_family=_reference_family(method),
        atomic_quality='unknown', atomic_source=None, atomic_status='missing',
        atomic_reason='尚未关联原子输入', c_angstrom_cm3=_plain(table.get('c_angstrom_cm3')),
        isolation_status='unknown', isolation_density_limit_cm3=None,
        model_method=MODEL_METHOD, table_metadata=_plain(
            {name: value for name, value in table.items() if name != 'samples'}),
    )
    family = out['reference_method_family']
    out['reference_independence'] = (
        'shared_method_not_independent_validation' if family == 'reference-mse'
        else 'unknown_reference_method' if family == 'unreported'
        else 'independence_not_established')
    return out


def _level(data, name, Level, Perturber):
    """只用显式原子数据构造能级；不补 phi 或同 n 矩阵元。"""
    if not isinstance(data, Mapping):
        raise ValueError(f'{name} 缺少能级对象')
    same_n = data.get('same_n')
    if not isinstance(same_n, (list, tuple)) or not same_n:
        raise ValueError(f'{name}.same_n 必须显式列出完整扰动阵列')
    perturbers = []
    for index, item in enumerate(same_n):
        if not isinstance(item, Mapping):
            raise ValueError(f'{name}.same_n[{index}] 不是对象')
        perturbers.append(Perturber(
            delta_e_ev=_number(item.get('delta_e_ev'), f'{name}.delta_e_ev'),
            matrix_element_sq_a0=_number(item.get('matrix_element_sq_a0'),
                                         f'{name}.matrix_element_sq_a0', zero=True),
            label=str(item.get('label') or ''),
        ))
    different = data.get('different_n_sum_a0_sq')
    if different is not None:
        different = _number(different, f'{name}.different_n_sum_a0_sq', zero=True)
    # different_n_sum=None 使用原模型式 (9)，不等于补造同 n 原子数据。
    return Level(n_eff=_number(data.get('n_eff'), f'{name}.n_eff'),
                 l=_integer(data.get('l'), f'{name}.l'),
                 same_n=tuple(perturbers), different_n_sum_a0_sq=different)


def _skip(skipped, context, issues):
    """每个原始点只记一条跳过记录，同时保留全部已发现原因。"""
    skipped.append(dict(context, reason_code=issues[0][0],
                        reason_codes=[code for code, _ in issues],
                        reason='；'.join(message for _, message in issues)))


def compare_tables(tables, models):
    """逐原始 T、Ne 比较并返回 (成功点列表, 跳过记录列表)。

    models 是 load_model_inputs 返回的身份键到原子样本映射。多个密度表
    共享原子样本，但每个原始点均单独计算；不按最近波长选择候选。
    任意非空 flag、非 q=2/3、缺原子数据或计算失败都明确进入 skipped。
    """
    from stark_atomic_data import table_key
    from stark_semiempirical import Level, Perturber, calculate_stark_width

    if not isinstance(models, Mapping):
        raise TypeError('models 必须是身份键到原子样本的映射')
    if isinstance(tables, (str, bytes, Mapping)):
        raise TypeError('tables 必须是 STARK 表的可迭代对象')
    rows, skipped, prepared = [], [], {}
    for table_index, table in enumerate(tables):
        if not isinstance(table, Mapping):
            _skip(skipped, dict(key=f'invalid-table:{table_index}',
                                line_id=f'invalid-table:{table_index}',
                                table_index=table_index, record_kind='table',
                                table_metadata=_plain(table)),
                  [('invalid_table', 'STARK 表不是对象，无法读取原始点')])
            continue
        issues = []
        try:
            key = table_key(table)
            if not isinstance(key, str) or not key.strip():
                raise ValueError('table_key 未返回非空字符串')
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            key = f'invalid-table:{table_index}'
            issues.append(('invalid_identity', f'谱线身份键无效: {exc}'))
        context = _context(table, table_index, key)
        try:
            charge = _integer(table.get('charge'), 'charge')
            context['charge'] = charge
            if charge not in SUPPORTED_CHARGES:
                issues.append(('unsupported_charge', f'q={charge} 超出模型 q=2/3 适用范围'))
        except ValueError as exc:
            issues.append(('invalid_charge', str(exc)))
        for name in ('element', 'dataset_id', 'lower_label', 'upper_label'):
            if not isinstance(table.get(name), str) or not table[name].strip():
                issues.append(('incomplete_identity', f'缺少明确身份字段 {name}'))
        try:
            context['wavelength_nm'] = _number(
                table.get('calculated_wavelength_angstrom'),
                'calculated_wavelength_angstrom') / 10.
            _number(context['wavelength_nm'], 'wavelength_nm')
        except ValueError as exc:
            issues.append(('invalid_wavelength', str(exc)))
        model = models.get(key)
        levels = None
        if isinstance(model, Mapping):
            context.update(atomic_quality=_plain(model.get('atomic_quality') or 'unknown'),
                           atomic_source=_plain(model.get('atomic_source')),
                           atomic_status=_plain(model.get('status')),
                           atomic_reason=_plain(model.get('reason')),
                           atomic_metadata=_plain({name: value for name, value in model.items()
                                                   if name not in ('lower', 'upper')}))
        if not issues:
            if not isinstance(model, Mapping):
                issues.append(('atomic_data_missing', '找不到相同身份键的原子输入'))
            elif model.get('key') != key:
                issues.append(('atomic_key_mismatch', '原子样本 key 与表的完整身份键不一致'))
            elif model.get('status') != 'ready':
                issues.append(('atomic_data_missing', str(
                    model.get('reason') or '原子输入未就绪，且未说明缺失原因')))
            elif not model.get('atomic_source'):
                issues.append(('atomic_source_missing', 'ready 原子输入缺少 atomic_source 来源'))
            else:
                if key not in prepared:
                    try:
                        prepared[key] = (_level(model.get('lower'), 'lower', Level, Perturber),
                                         _level(model.get('upper'), 'upper', Level, Perturber))
                    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
                        prepared[key] = str(exc)
                if isinstance(prepared[key], str):
                    issues.append(('invalid_atomic_input', prepared[key]))
                else:
                    levels = prepared[key]
        samples = table.get('samples')
        if not isinstance(samples, (list, tuple)) or not samples:
            _skip(skipped, context, issues + [('missing_samples', '原表没有可读取的电子 FWHM 样本')])
            continue
        for sample_index, sample in enumerate(samples):
            point = dict(context, sample_index=sample_index, record_kind='point',
                         sample_metadata=_plain(sample))
            point_issues = list(issues)
            if not isinstance(sample, Mapping):
                _skip(skipped, point, point_issues + [('invalid_sample', '原始样本不是对象')])
                continue
            point.update(temperature_k=_plain(sample.get('temperature_k')),
                         electron_density_cm3=_plain(sample.get('ne')),
                         fwhm_db_angstrom=_plain(sample.get('fwhm_angstrom')),
                         flag=_plain(sample.get('flag')),
                         environment_id=_plain(sample.get('environment_id')),
                         collider_ref=_plain(sample.get('collider_ref')))
            flag = sample.get('flag')
            if flag is not None and flag != '':
                point_issues.append(('flagged_sample', f'原始 flag 非空，默认排除: {flag!r}'))
            try:
                temperature = _number(sample.get('temperature_k'), 'temperature_k')
                density = _number(sample.get('ne'), 'ne')
                db_angstrom = _number(sample.get('fwhm_angstrom'), 'fwhm_angstrom')
                db_nm = _number(db_angstrom / 10., 'fwhm_db_nm')
                point.update(temperature_k=temperature, electron_density_cm3=density,
                             fwhm_db_angstrom=db_angstrom, fwhm_db_nm=db_nm)
                c_value = table.get('c_angstrom_cm3')
                if c_value is not None:
                    try:
                        limit = _number(c_value, 'c_angstrom_cm3') / db_angstrom
                        point['isolation_density_limit_cm3'] = _number(
                            limit, 'isolation_density_limit_cm3')
                        point['isolation_status'] = ('below_c_over_fwhm_limit'
                                                     if density < limit
                                                     else 'at_or_above_c_over_fwhm_limit')
                        if density >= limit:
                            point_issues.append(('isolation_limit_exceeded', 'Ne 不小于原表 C/FWHM 隔离密度界限'))
                    except ValueError:
                        point['isolation_status'] = 'unknown'
            except ValueError as exc:
                point_issues.append(('invalid_sample_values', str(exc)))
            if point_issues:
                _skip(skipped, point, point_issues)
                continue
            try:
                result = calculate_stark_width(
                    wavelength_nm=point['wavelength_nm'], temperature_k=temperature,
                    electron_density_cm3=density, ion_charge=context['charge'],
                    lower=levels[0], upper=levels[1])
                model_nm = _number(result.fwhm_nm, 'fwhm_model_nm')
                # 数据库值原本就是 FWHM，此处只做 Å -> nm，绝不乘二。
                ratio = _number(model_nm / db_nm, 'ratio')
                signed = (ratio - 1.) * 100.
                alpha_db = _number(db_nm / density, 'alpha_db_nm_cm3')
                alpha_model = _number(model_nm / density, 'alpha_model_nm_cm3')
                normalized_db = _number(alpha_db * REFERENCE_DENSITY_CM3, 'fwhm_db_at_1e17_nm')
                normalized_model = _number(alpha_model * REFERENCE_DENSITY_CM3, 'fwhm_model_at_1e17_nm')
                if not math.isfinite(signed):
                    raise ValueError('相对误差溢出，不能纳入统计')
                rows.append(dict(point, fwhm_model_nm=model_nm,
                                 alpha_db_nm_cm3=alpha_db, alpha_model_nm_cm3=alpha_model,
                                 fwhm_db_at_1e17_nm=normalized_db,
                                 fwhm_model_at_1e17_nm=normalized_model,
                                 signed_relative_error_percent=signed,
                                 absolute_relative_error_percent=abs(signed),
                                 ratio=ratio, log10_ratio=math.log10(ratio)))
            except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
                _skip(skipped, point, [('model_calculation_failed', str(exc))])
    return rows, skipped


def _line_id(row):
    """统计使用完整身份键；外部行缺键时采用完整身份组合。"""
    if row.get('line_id') or row.get('key'):
        return str(row.get('line_id') or row['key'])
    identity = {name: _plain(row.get(name)) for name in _IDENTITY_FIELDS}
    return json.dumps(identity, sort_keys=True, ensure_ascii=False)


def _weighted_mean(values, weights):
    """用缩放避免大误差在求和中溢出。"""
    scale = max((abs(value) for value in values), default=0.)
    if scale == 0:
        return 0.
    average = math.fsum((value / scale) * weight
                        for value, weight in zip(values, weights)) / math.fsum(weights)
    return scale * average


def _weighted_rms(values, weights):
    """以缩放平方和计算 RMS，避免直接平方大残差。"""
    scale = max((abs(value) for value in values), default=0.)
    if scale == 0:
        return 0.
    fraction = math.fsum((value / scale) ** 2 * weight
                         for value, weight in zip(values, weights)) / math.fsum(weights)
    return scale * math.sqrt(fraction)


def _weighted_median(values, weights):
    """求加权中位数；权重恰好平分时取相邻值中点。"""
    ordered = sorted(zip(values, weights))
    half, cumulative = math.fsum(weights) / 2., 0.
    for index, (value, weight) in enumerate(ordered):
        cumulative += weight
        if math.isclose(cumulative, half, rel_tol=1e-12, abs_tol=0.):
            if index + 1 < len(ordered):
                return value / 2. + ordered[index + 1][0] / 2.
            return value
        if cumulative > half:
            return value
    return ordered[-1][0]


def _metrics(rows, *, line_balanced=False):
    """计算点统计或每条线总权重相同的统计，不把温度点当独立谱线。"""
    names = (
        'mare_percent', 'median_absolute_relative_error_percent', 'bias_percent',
        'median_signed_relative_error_percent', 'rms_relative_error_percent',
        'mean_log10_ratio', 'median_log10_ratio', 'rms_log10_error',
        'std_log10_ratio', 'mean_absolute_log10_error', 'geometric_mean_ratio',
        'median_ratio', 'within_factor_two_fraction', 'within_20_percent_fraction',
    )
    counts = Counter(_line_id(row) for row in rows)
    out = dict(point_count=len(rows), unique_line_count=len(counts),
               weighting='each_line_equal_then_each_point_equal_within_line'
               if line_balanced else 'each_point_equal')
    if not rows:
        out.update({name: None for name in names})
        return out
    weights = [1. / counts[_line_id(row)] if line_balanced else 1. for row in rows]
    signed = [row['signed_relative_error_percent'] for row in rows]
    absolute = [row['absolute_relative_error_percent'] for row in rows]
    logs = [row['log10_ratio'] for row in rows]
    mean_log = _weighted_mean(logs, weights)
    try:
        geometric_ratio = 10. ** mean_log
    except OverflowError:
        geometric_ratio = None
    out.update(
        mare_percent=_weighted_mean(absolute, weights),
        median_absolute_relative_error_percent=_weighted_median(absolute, weights),
        bias_percent=_weighted_mean(signed, weights),
        median_signed_relative_error_percent=_weighted_median(signed, weights),
        rms_relative_error_percent=_weighted_rms(signed, weights),
        mean_log10_ratio=mean_log, median_log10_ratio=_weighted_median(logs, weights),
        rms_log10_error=_weighted_rms(logs, weights),
        std_log10_ratio=_weighted_rms([value - mean_log for value in logs], weights),
        mean_absolute_log10_error=_weighted_mean([abs(value) for value in logs], weights),
        geometric_mean_ratio=geometric_ratio,
        median_ratio=_weighted_median([row['ratio'] for row in rows], weights),
        within_factor_two_fraction=_weighted_mean(
            [float(.5 <= row['ratio'] <= 2.) for row in rows], weights),
        within_20_percent_fraction=_weighted_mean(
            [float(abs(row['ratio'] - 1.) <= .2) for row in rows], weights),
    )
    return out


def _coverage(rows, skipped):
    """区分输入点、表级异常和完整身份谱线，并报告 q=2/3 子集覆盖率。"""
    skipped_points = [row for row in skipped if row.get('record_kind', 'point') == 'point']
    all_records = rows + [row for row in skipped if row.get('record_kind') != 'run']
    all_points = rows + skipped_points
    compared_lines = {_line_id(row) for row in rows}
    all_lines = {_line_id(row) for row in all_records}
    eligible = [row for row in all_points if row.get('charge') in SUPPORTED_CHARGES]
    eligible_lines = {_line_id(row) for row in all_records
                      if row.get('charge') in SUPPORTED_CHARGES}
    table_ids = {row.get('table_index') for row in all_records if row.get('table_index') is not None}
    return dict(
        input_table_count=len(table_ids), input_points=len(all_points),
        compared_points=len(rows), skipped_points=len(skipped_points),
        skipped_records=len(skipped),
        table_level_failure_records=sum(row.get('record_kind') == 'table' for row in skipped),
        run_level_failure_records=sum(row.get('record_kind') == 'run' for row in skipped),
        input_unique_lines=len(all_lines), compared_unique_lines=len(compared_lines),
        skipped_unique_lines=len({_line_id(row) for row in skipped if row.get('record_kind') != 'run'}),
        unique_lines_without_comparison=len(all_lines - compared_lines),
        point_coverage_fraction=len(rows) / len(all_points) if all_points else None,
        line_coverage_fraction=len(compared_lines) / len(all_lines) if all_lines else None,
        q23_input_points=len(eligible), q23_input_unique_lines=len(eligible_lines),
        q23_point_coverage_fraction=len(rows) / len(eligible) if eligible else None,
        q23_line_coverage_fraction=len(compared_lines) / len(eligible_lines) if eligible_lines else None,
    )


def _group_statistics(rows, skipped, fields):
    """按明确字段分层，保留没有成功比较的组及其覆盖率。"""
    grouped_rows, grouped_skips, labels = defaultdict(list), defaultdict(list), {}
    for target, records in ((grouped_rows, rows), (grouped_skips, skipped)):
        for row in records:
            label = {field: _plain(row.get(field)) for field in fields}
            token = json.dumps(label, sort_keys=True, ensure_ascii=False)
            labels[token] = label
            target[token].append(row)
    result = []
    for token in sorted(labels):
        selected = grouped_rows[token]
        result.append(dict(labels[token], coverage=_coverage(selected, grouped_skips[token]),
                           point_weighted=_metrics(selected),
                           line_balanced=_metrics(selected, line_balanced=True)))
    return result


def summarize(rows, skipped):
    """汇总覆盖率、点/谱线均衡误差、逐线结果和来源方法等分层。

    line_balanced 为每个完整身份谱线总权重 1，其内部点权重 1/n。
    加权中位数针对该权重分布；不是把各线中位数再作平均。
    MSE 方法参考不能作为独立实验精度证明，未知方法不标成 SCP。
    """
    rows, skipped = list(rows), list(skipped)
    reasons, all_reasons = Counter(), Counter()
    for row in skipped:
        reasons[row.get('reason_code', 'unspecified')] += 1
        all_reasons.update(row.get('reason_codes') or [row.get('reason_code', 'unspecified')])
    strata = {
        'element': _group_statistics(rows, skipped, ('element',)),
        'charge': _group_statistics(rows, skipped, ('charge',)),
        'source_method': _group_statistics(rows, skipped, ('source', 'method')),
        'atomic_quality': _group_statistics(rows, skipped, ('atomic_quality',)),
        'reference_method_family': _group_statistics(rows, skipped, ('reference_method_family',)),
    }
    lines = defaultdict(list)
    for row in rows:
        lines[_line_id(row)].append(row)
    per_line = []
    for key in sorted(lines):
        selected, first = lines[key], lines[key][0]
        per_line.append(dict(
            {name: _plain(first.get(name)) for name in (
                'element', 'charge', 'dataset_id', 'lower_label', 'upper_label',
                'wavelength_nm', 'source', 'source_ids', 'method', 'reference_method_family',
                'atomic_quality', 'atomic_source')},
            key=key, metrics=_metrics(selected)))
    return dict(
        schema_version=1, generated_at_utc=datetime.now(timezone.utc).isoformat(),
        status='ok' if rows else 'no_comparable_points',
        conclusion_available=bool(rows), coverage=_coverage(rows, skipped),
        overall=dict(point_weighted=_metrics(rows), line_balanced=_metrics(rows, line_balanced=True)),
        stratified=strata, per_line=per_line,
        skipped_reasons=dict(sorted(reasons.items())),
        skipped_all_reason_counts=dict(sorted(all_reasons.items())),
        conventions=dict(
            database_width='electron FWHM; fwhm_angstrom / 10 = nm; never multiply by two',
            shared_conditions='original sample T and Ne; calculated_wavelength_angstrom / 10 for both',
            interpolation='none', model_method=MODEL_METHOD, supported_charges=list(SUPPORTED_CHARGES),
            coefficient='alpha_nm_cm3 = FWHM_nm / Ne_cm^-3',
            normalized_width='alpha_nm_cm3 * 1e17 cm^-3; arithmetic normalization only',
            normalized_density_cm3=REFERENCE_DENSITY_CM3,
            relative_error='100 * (model / database - 1)', log_error='log10(model / database)',
            unique_line='complete table_key including element, q, dataset, states, wavelength and sources; excludes density',
            line_balanced='each unique line weight 1; each of its n points weight 1/n',
            median='weighted median of points under the specified weighting',
            missing_c='isolation unknown; no evidence of validity inferred',
            flags='all nonempty flags excluded',
            reference_mse='separate stratum; shared theory is not independent experimental validation',
            unknown_method='unreported; never presumed SCP',
        ),
        limitations=[
            '统计仅描述成功比较的子集，缺失原子数据与适用性筛选会产生选择效应。',
            '同一谱线的温度/密度点不独立；谱线身份含数据集与来源，不代表独立实验次数。',
            '未报告 C 时隔离条件未知；无 flag 不证明碰撞近似或 LS 耦合成立。',
            '归一化到 1e17 cm^-3 仅用于比较系数，不证明该密度下仍满足隔离与碰撞条件。',
            'MSE 参考与待检模型可能共享理论；其他来源的实验独立性也需另行审查。',
        ],
    )


def _csv_cell(value):
    """在 CSV 单元格中无损保留结构化元数据。"""
    value = _plain(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return value


def _write_csv(path, records):
    """即使零行也写出稳定列头，便于下游程序读取。"""
    extra = sorted({name for row in records for name in row} - set(_CSV_FIELDS))
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_CSV_FIELDS) + extra)
        writer.writeheader()
        for row in records:
            writer.writerow({name: _csv_cell(value) for name, value in row.items()})


def _plot_comparison(rows, summary, path):
    """用真实有效点绘制 Agg 四面板图，明确标出参考方法层。"""
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt

    if not rows:
        raise ValueError('没有可比较点，不生成图')
    # 图中文字使用英文，避免主机缺少中文字体导致输出方框。
    families = (('unreported', 'Reference method unreported', 'tab:blue', 'o'),
                ('reference-mse', 'Reference MSE (shared theory)', 'tab:orange', '^'),
                ('other-reported', 'Other reported method', 'tab:green', 's'))
    elements = [group for group in summary['stratified']['element']
                if group['line_balanced']['point_count']]
    height = max(8., 5. + .22 * len(elements))
    with plt.rc_context({'font.size': 10, 'axes.grid': True, 'grid.alpha': .2}):
        figure, axes = plt.subplots(2, 2, figsize=(13., height))
        try:
            parity, residual, histogram, bars = axes.flat
            xvalues = [row['alpha_db_nm_cm3'] for row in rows]
            yvalues = [row['alpha_model_nm_cm3'] for row in rows]
            minimum, maximum = min(xvalues + yvalues), max(xvalues + yvalues)
            if minimum == maximum:
                lower, upper = minimum / 2., maximum * 2.
            else:
                lower, upper = minimum / 1.4, maximum * 1.4
            parity.fill_between([lower, upper], [lower / 2., upper / 2.],
                                [lower * 2., upper * 2.], color='0.88', label='Factor 2 band')
            parity.plot([lower, upper], [lower, upper], color='black', linewidth=1., label='1:1')
            for family, label, color, marker in families:
                group = [row for row in rows if row['reference_method_family'] == family]
                if not group:
                    continue
                parity.scatter([row['alpha_db_nm_cm3'] for row in group],
                               [row['alpha_model_nm_cm3'] for row in group],
                               s=19, alpha=.65, color=color, marker=marker, label=label,
                               edgecolors='none', rasterized=True)
                residual.scatter([row['temperature_k'] for row in group],
                                 [row['signed_relative_error_percent'] for row in group],
                                 s=19, alpha=.65, color=color, marker=marker, label=label,
                                 edgecolors='none', rasterized=True)
            parity.set(xscale='log', yscale='log', xlim=(lower, upper), ylim=(lower, upper),
                       xlabel=r'STARK-B $\alpha$ (nm cm$^3$)',
                       ylabel=r'Model $\alpha$ (nm cm$^3$)',
                       title='(a) Electron FWHM / original Ne')
            parity.set_aspect('equal', adjustable='box')
            parity.legend(fontsize=7, loc='best')
            residual.axhline(0., color='black', linewidth=1.)
            residual.set(xscale='log', xlabel='Original electron temperature (K)',
                         ylabel='100 (model / STARK-B - 1) (%)', title='(b) Signed relative residual')
            bin_count = min(60, max(5, int(math.sqrt(len(rows)))))
            logvalues = [row['log10_ratio'] for row in rows]
            lo, hi = min(logvalues), max(logvalues)
            if lo == hi:
                lo, hi = lo - .25, hi + .25
            bins = [lo + (hi - lo) * index / bin_count for index in range(bin_count + 1)]
            for family, label, color, _ in families:
                values = [row['log10_ratio'] for row in rows if row['reference_method_family'] == family]
                if values:
                    histogram.hist(values, bins=bins, histtype='step',
                                   linewidth=1.6, color=color, label=label)
            histogram.axvline(0., color='black', linewidth=1.)
            histogram.axvline(math.log10(2.), color='0.5', linestyle='--', linewidth=.8)
            histogram.axvline(-math.log10(2.), color='0.5', linestyle='--', linewidth=.8)
            histogram.set(xlabel='log10(model / STARK-B)', ylabel='Number of points',
                          title='(c) Point distribution (temperature points correlated)')
            histogram.legend(fontsize=7)
            elements.sort(key=lambda group: (group['line_balanced']['mare_percent'], str(group['element'])))
            positions = list(range(len(elements)))
            values = [group['line_balanced']['mare_percent'] for group in elements]
            bars.barh(positions, values, color='tab:blue', alpha=.8)
            bars.set_yticks(positions)
            bars.set_yticklabels([str(group['element'] or 'unknown') for group in elements])
            max_value = max(values, default=0.)
            span = max(max_value, 1.)
            bars.set_xlim(0., span * 1.55)
            for position, group, value in zip(positions, elements, values):
                stats = group['line_balanced']
                bars.text(value + .02 * span, position,
                          f"L={stats['unique_line_count']}, P={stats['point_count']}",
                          va='center', fontsize=8)
            bars.set(xlabel='Line-balanced MARE (%)',
                     title='(d) Element comparison (all reference methods)')
            coverage = summary['coverage']
            figure.suptitle(
                f"STARK-B vs DK1980 MSE: {len(rows)} points, "
                f"{coverage['compared_unique_lines']} source-specific lines\n"
                'Same original T, Ne and wavelength; no interpolation; method unknown stays unknown',
                fontsize=12)
            figure.tight_layout(rect=(0., 0., 1., .94))
            figure.savefig(path, dpi=200)
        finally:
            plt.close(figure)


def _fmt(value, digits=3):
    """将空指标明确显示为不可计算。"""
    return '不可计算' if value is None else f'{value:.{digits}g}'


def _percent(value):
    """将覆盖率分数显示为百分比。"""
    return '不可计算' if value is None else f'{value * 100.:.2f}%'


def _md(value):
    """防止来源文字中的换行和竖线破坏 Markdown 表格。"""
    if value is None or value == '':
        return '未报告'
    return str(value).replace('|', r'\|').replace('\r', ' ').replace('\n', ' ')


def _report(summary):
    """从实际汇总结果生成中文分析，空样本不产生精度结论。"""
    coverage = summary['coverage']
    point, line = summary['overall']['point_weighted'], summary['overall']['line_balanced']
    text = [
        '# STARK-B 电子 FWHM 与修正半经验模型比较', '',
        f"生成时间（UTC）：{summary['generated_at_utc']}。", '',
    ]
    text.extend(_run_report(summary.get('run')))
    text.extend([
        '## 数据与覆盖率', '',
        f"读取 {coverage['input_table_count']} 张表、{coverage['input_points']} 个原始点、"
        f"{coverage['input_unique_lines']} 条含数据集与来源身份的谱线。"
        f"成功比较 {coverage['compared_points']} 点、{coverage['compared_unique_lines']} 条线；"
        f"跳过 {coverage['skipped_points']} 点，另有 {coverage['table_level_failure_records']} 条表级异常、"
        f"{coverage['run_level_failure_records']} 条运行级异常。", '',
        f"全部输入的点覆盖率 {_percent(coverage['point_coverage_fraction'])}，"
        f"谱线覆盖率 {_percent(coverage['line_coverage_fraction'])}。"
        f"q=2/3 子集有 {coverage['q23_input_points']} 点、{coverage['q23_input_unique_lines']} 条线，"
        f"对应覆盖率为 {_percent(coverage['q23_point_coverage_fraction'])}、"
        f"{_percent(coverage['q23_line_coverage_fraction'])}。这些是已加载数据的覆盖率，"
        '不能替代抓取 manifest 对全库完整性的证明。', '',
    ])
    if not summary['conclusion_available']:
        text.extend([
            '## 当前结果', '',
            '**没有可用比较点，不能评价模型精度、偏差或元素间优劣。** '
            '误差统计在 JSON 中保留为 null；comparison.csv 仅含列头，skipped.csv 保留原因。'
            '不生成比较图，也不以合成点或缺省原子参数补齐数据。', '',
        ])
    else:
        text.extend([
            '## 误差与数据所支持的结论', '',
            '| 指标 | 每点等权 | 每条谱线等权 |',
            '|---|---:|---:|',
        ])
        for label, key in (
                ('MARE（%）', 'mare_percent'),
                ('绝对相对误差中位数（%）', 'median_absolute_relative_error_percent'),
                ('平均有符号偏差（%）', 'bias_percent'),
                ('相对误差 RMS（%）', 'rms_relative_error_percent'),
                ('log10 比值均值', 'mean_log10_ratio'),
                ('log10 比值中位数', 'median_log10_ratio'),
                ('log10 误差 RMS（dex）', 'rms_log10_error'),
                ('比值几何均值', 'geometric_mean_ratio'),
                ('两倍以内比例', 'within_factor_two_fraction')):
            text.append(f'| {label} | {_fmt(point[key])} | {_fmt(line[key])} |')
        bias = line['bias_percent']
        direction = '平均高估' if bias > 0 else '平均低估' if bias < 0 else '平均有符号偏差为零'
        text.extend([
            '', f"在当前成功子集中，每线等权 MARE 为 {_fmt(line['mare_percent'])}%，"
            f"绝对相对误差中位数为 {_fmt(line['median_absolute_relative_error_percent'])}%，"
            f"有符号偏差为 {_fmt(bias)}%（{direction}）。"
            f"两倍以内的加权比例为 {_percent(line['within_factor_two_fraction'])}，"
            f"log10 误差 RMS 为 {_fmt(line['rms_log10_error'])} dex。"
            '有符号均值存在抵消，不能替代绝对误差。', '',
            '每线等权表示一条完整身份谱线总权重为 1，线内每个原始 T、Ne 点的权重为 1/n。'
            '每点等权会让采样较密的线贡献更多；二者同时保留，不把温度点视作独立实验。'
            '线的身份包含来源与数据集，同一物理跃迁的不同出版物会分开统计。', '',
        ])
    for title, field, fields in (
            ('元素分层', 'element', ('element',)),
            ('电荷分层', 'charge', ('charge',)),
            ('原子数据质量分层', 'atomic_quality', ('atomic_quality',)),
            ('参考方法分层', 'reference_method_family', ('reference_method_family',)),
            ('来源与报告方法分层', 'source_method', ('source', 'method'))):
        text.extend([f'## {title}', '',
                     '| 组 | 比较点 / 输入点 | 比较线 / 输入线 | 每线 MARE（%） | 每线偏差（%） |',
                     '|---|---:|---:|---:|---:|'])
        for group in summary['stratified'][field]:
            label = '；'.join(_md(group.get(name)) for name in fields)
            count, stats = group['coverage'], group['line_balanced']
            text.append(
                f"| {label} | {count['compared_points']} / {count['input_points']} | "
                f"{count['compared_unique_lines']} / {count['input_unique_lines']} | "
                f"{_fmt(stats['mare_percent'])} | {_fmt(stats['bias_percent'])} |")
        text.append('')
    mse = next((group for group in summary['stratified']['reference_method_family']
                if group['reference_method_family'] == 'reference-mse'), None)
    unknown = next((group for group in summary['stratified']['reference_method_family']
                    if group['reference_method_family'] == 'unreported'), None)
    text.extend(['## 来源独立性与解释边界', ''])
    if mse and mse['coverage']['compared_points']:
        text.append(
            f"明确报告为 MSE 的参考包含 {mse['coverage']['compared_points']} 个成功点，"
            f"{mse['coverage']['compared_unique_lines']} 条线；已单独列层。"
            '该层可能与被检模型共享理论，接近数据库只能说明方法间一致性，不能作为独立实验精度证据。')
    else:
        text.append('成功比较中没有明确标为 MSE 的参考方法；这不证明数据库参考与本模型相互独立。')
    if unknown and unknown['coverage']['compared_points']:
        text.append(
            f"有 {unknown['coverage']['compared_points']} 个成功点的参考方法未报告，"
            '保留为 unreported，不改标为 SCP，也不从来源标题猜测方法。')
    text.extend([''] + [f'- {item}' for item in summary['limitations']] + [
        '', '## 跳过原因', '',
        '每个失败或缺失原始点记一条 skipped.csv；表没有样本时记表级异常，'
        '加载流水线失败时记运行级异常。'
        '下表按首要原因计数，同一记录的其他原因保留在 reason_codes；'
        'summary.json 的 skipped_all_reason_counts 包含全部原因，因此可能重复计数。', '',
        '| 首要原因 | 记录数 |', '|---|---:|',
    ])
    for reason, count in sorted(summary['skipped_reasons'].items(), key=lambda item: (-item[1], item[0])):
        text.append(f'| {_md(reason)} | {count} |')
    if not summary['skipped_reasons']:
        text.append('| 无跳过记录 | 0 |')
    text.extend([
        '', '## 数值约定与文件', '',
        '共同波长 λ = calculated_wavelength_angstrom / 10（nm）。数据库宽度 '
        'FWHM_db_nm = fwhm_angstrom / 10，不乘二。每个原始点在其原始 T 和 Ne 下'
        '直接计算，不插值、不重采样。α = FWHM_nm / Ne，单位 nm·cm³；'
        '归一化宽度 = α × 10¹⁷ cm⁻³。ratio = model/db，signed relative error = '
        '100 × (ratio−1)，absolute relative error = 其绝对值。', '',
        'comparison.csv 保存成功点和来源；skipped.csv 保存缺失或失败原因；'
        'summary.json 保存点权重、线均衡、逐线与分层结果。', '',
    ])
    plot = summary.get('plot', {})
    if plot.get('status') == 'written':
        text.extend([
            'comparison.png 的四个面板分别为 α 的双对数 parity（1:1 与两倍带）、'
            '有符号残差对原始温度（温度对数轴）、log10 比值直方图、'
            '每元素线均衡 MARE（L 为谱线数，P 为点数）。前三图按参考方法区分，'
            '元素条图包含全部参考方法，应结合上述方法分层解读。', '',
            '![电子 FWHM 比较](comparison.png)', '',
        ])
    elif plot.get('status') == 'failed':
        text.extend([f"绘图失败：{plot.get('reason')}。数值结果已保存；本次未生成可交付图。", ''])
    else:
        text.extend(['没有可比较点，未生成 comparison.png。', ''])
    return '\n'.join(text)


def _manifest_snapshot(directory):
    """在实际运行时保留原 manifest、摘要与哈希，不进行任何采集。"""
    path = Path(directory) / 'manifest.json'
    snapshot = dict(path=str(path), status='missing', sha256=None,
                    scope='unknown', filters=None, complete=None, failures=[], manifest=None)
    try:
        raw = path.read_bytes()
        snapshot['sha256'] = hashlib.sha256(raw).hexdigest()
        manifest = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(manifest, Mapping):
            raise ValueError('manifest 必须是对象')
    except FileNotFoundError:
        snapshot['reason'] = 'manifest 文件不存在，不能推断完整性或采集范围'
        return snapshot
    except (OSError, UnicodeError, ValueError) as exc:
        snapshot.update(status='unreadable', reason=f'{type(exc).__name__}: {exc}')
        return snapshot
    snapshot.update(status='available', manifest=_plain(manifest),
                    scope=_plain(manifest.get('scope') or 'unknown'),
                    filters=_plain(manifest.get('filters')),
                    complete=manifest.get('complete') if type(manifest.get('complete')) is bool else None)
    species = manifest.get('species')
    species = species if isinstance(species, list) else []
    snapshot['species_status_counts'] = dict(Counter(
        str(item.get('status', 'unknown')) for item in species if isinstance(item, Mapping)))
    reported = manifest.get('failures')
    if isinstance(reported, list):
        snapshot['failures'] = _plain(reported)
    else:
        snapshot['failures'] = [
            _plain(item) for item in species if isinstance(item, Mapping)
            and item.get('status') not in ('ok', 'ready', 'no data')
        ]
    snapshot['failure_count'] = len(snapshot['failures'])
    return snapshot


def _run_metadata(args, tables, models, load_warnings):
    """保存本次有效输入范围、采集失败和手工覆盖后的原子样本状态。"""
    stark = _manifest_snapshot(args.stark_dir)
    atomic = _manifest_snapshot(args.sample_dir)
    actual = defaultdict(lambda: dict(table_count=0, point_count=0))
    for table in tables:
        key = (table.get('element'), table.get('charge'))
        actual[key]['table_count'] += 1
        actual[key]['point_count'] += len(table.get('samples') or [])
    loaded = [dict(element=element, charge=charge, **counts)
              for (element, charge), counts in sorted(actual.items(), key=lambda item: str(item[0]))]
    manifest = stark.get('manifest') or {}
    discrepancies = []
    for record in manifest.get('species') or []:
        if not isinstance(record, Mapping):
            continue
        key = (record.get('element'), record.get('charge'))
        retained = actual.get(key, dict(table_count=0, point_count=0))
        if (record.get('status') != 'ok' or
                record.get('table_count') != retained['table_count'] or
                record.get('sample_count') != retained['point_count']):
            discrepancies.append(dict(
                element=key[0], charge=key[1], manifest_status=record.get('status'),
                manifest_table_count=record.get('table_count'),
                manifest_point_count=record.get('sample_count'),
                loaded_table_count=retained['table_count'], loaded_point_count=retained['point_count'],
                error=record.get('error')))
    stark_load_warnings = [item for item in load_warnings
                           if not item['category'].startswith('AtomicInput')]
    full_snapshot = (stark['status'] == 'available' and stark['scope'] == 'all'
                     and stark['complete'] is True and not discrepancies and not stark_load_warnings)
    model_statuses = Counter(str(model.get('status') or 'unknown')
                             for model in models.values() if isinstance(model, Mapping))
    qualities = Counter(str(model.get('atomic_quality') or 'unknown')
                        for model in models.values() if isinstance(model, Mapping))
    return dict(
        command=args.command, stark_dir=str(args.stark_dir), sample_dir=str(args.sample_dir),
        output_dir=str(args.output_dir), allow_partial=args.allow_partial,
        fetch_options=dict(elements=args.elements, charges=args.charges,
                           refresh=args.refresh, delay_seconds=args.delay),
        compare_filter_policy='load_all_cached_tables; elements/charges only affect fetch-stark',
        comparison_supported_charges=list(SUPPORTED_CHARGES),
        stark_manifest=stark, sample_manifest=atomic,
        loaded_species=loaded, loader_warnings=load_warnings,
        manifest_load_discrepancies=_plain(discrepancies),
        full_discovered_database_snapshot_loaded=full_snapshot,
        full_database_meaning='all species discovered at manifest retrieval time; not all physics or all model coverage',
        effective_model_status_counts=dict(model_statuses), effective_atomic_quality_counts=dict(qualities),
        manual_input_file_present=(args.sample_dir / 'manual_inputs.json').is_file(),
        atomic_completeness_meaning='source retrieval completion does not imply all lines have ready atomic inputs',
    )


def _run_report(run):
    """用实际 manifest 描述全库/筛选范围和失败，绝不凭 CLI 缺省值推断。"""
    if not run:
        return ['## 输入范围与运行上下文', '',
                '本输出通过函数接口生成，未提供 STARK/sample manifest 运行上下文。'
                '只能描述传入的行与跳过记录，不能判断采集完整性或全库覆盖率。', '']
    stark, atomic = run['stark_manifest'], run['sample_manifest']
    full = run['full_discovered_database_snapshot_loaded']
    result = [
        '## 输入范围与采集完整性', '',
        f"STARK manifest：`{_md(stark['path'])}`；SHA-256：`{stark.get('sha256') or '未取得'}`。"
        f"读取状态 {_md(stark['status'])}，scope={_md(stark['scope'])}，"
        f"complete={stark['complete']}，filters="
        f"`{json.dumps(stark['filters'], ensure_ascii=False)}`。", '',
        ('已加载 manifest 采集时发现的全部物种快照；这不代表全部谱线都能进行模型比较。'
         if full else
         '**本次不能声称完整加载 STARK-B 全库。** 筛选范围、不完整采集或加载时跳过的物种'
         '均不纳入已加载数据的覆盖率分母，请结合下列记录解释结果。'), '',
        f"本次 --allow-partial={run['allow_partial']}。允许 partial 是读取策略，"
        '不改变 manifest 声明的范围和完整性；即使 complete=True，scope=filtered 仍是筛选子集。', '',
        '`--elements` 与 `--charges` 只用于 fetch-stark；compare/fetch-atomic 不进一步筛选缓存。'
        '实际比较读取指定缓存的所有表，仅 q=2/3 可以计算，其余记录写入 skipped.csv。'
        f"本次 CLI 抓取范围参数为 `{json.dumps(run['fetch_options'], ensure_ascii=False)}`。", '',
        f"sample manifest：`{_md(atomic['path'])}`；SHA-256：`{atomic.get('sha256') or '未取得'}`。"
        f"读取状态 {_md(atomic['status'])}，scope={_md(atomic['scope'])}，"
        f"filters=`{json.dumps(atomic['filters'], ensure_ascii=False)}`，complete={atomic['complete']}。"
        '其 complete 仅描述原子来源采集，不意味着每条谱线都满足严格模型输入要求。'
        f"手工覆盖后的输入状态为 `{json.dumps(run['effective_model_status_counts'], ensure_ascii=False)}`，"
        f"质量层为 `{json.dumps(run['effective_atomic_quality_counts'], ensure_ascii=False)}`。", '',
    ]
    for label, snapshot in (('STARK', stark), ('原子数据', atomic)):
        failures = snapshot.get('failures') or []
        result.append(f'{label} manifest 报告的失败/未完成记录数：{len(failures)}。')
        if snapshot.get('reason'):
            result.append(f"{label} manifest 信息限制：{_md(snapshot['reason'])}。")
        if failures:
            result.extend(['', '| 阶段或物种 | 状态/原因 |', '|---|---|'])
            for item in failures:
                if isinstance(item, Mapping):
                    identity = item.get('stage') or (
                        f"{item.get('element', 'unknown')} q={item.get('charge', 'unknown')}")
                    reason = item.get('error') or item.get('reason') or item.get('status') or item
                else:
                    identity, reason = label, item
                result.append(f'| {_md(identity)} | {_md(reason)} |')
        result.append('')
    discrepancies = run['manifest_load_discrepancies']
    if discrepancies:
        result.extend(['manifest 与实际加载的数量差异/失败物种：', '',
                       '| 物种 | manifest 表/点 | 实际加载表/点 | 状态/原因 |',
                       '|---|---:|---:|---|'])
        for item in discrepancies:
            result.append(
                f"| {_md(item['element'])} q={item['charge']} | "
                f"{item['manifest_table_count']} / {item['manifest_point_count']} | "
                f"{item['loaded_table_count']} / {item['loaded_point_count']} | "
                f"{_md(item['error'] or item['manifest_status'])} |")
        result.append('')
    if run['loader_warnings']:
        result.extend(['加载器警告（包括 partial 模式跳过损坏物种）：', ''])
        result.extend(f"- {_md(item['category'])}: {_md(item['message'])}" for item in run['loader_warnings'])
        result.append('')
    result.extend(['summary.json 的 run 字段保留两个 manifest 的完整内容及 SHA-256、'
                   '加载物种计数、全部失败、加载警告与数量差异。', ''])
    return result


def _save_outputs(rows, skipped, output_dir, run=None):
    """共享写入实现；CLI 可附加 manifest 上下文，函数接口不猜目录。"""
    rows, skipped = list(rows), list(skipped)
    summary = summarize(rows, skipped)
    if run is not None:
        summary['run'] = run
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / 'comparison.csv', rows)
    _write_csv(output_dir / 'skipped.csv', skipped)
    plot_path = output_dir / 'comparison.png'
    if plot_path.exists():
        plot_path.unlink()
    if rows:
        try:
            _plot_comparison(rows, summary, plot_path)
            summary['plot'] = dict(status='written', path='comparison.png')
        except Exception as exc:
            if plot_path.exists():
                plot_path.unlink()
            summary['plot'] = dict(status='failed', reason=f'{type(exc).__name__}: {exc}')
    else:
        summary['plot'] = dict(status='not_generated', reason='没有可比较点，不生成图')
    summary['files'] = dict(comparison='comparison.csv', skipped='skipped.csv',
                           summary='summary.json', report='report.md',
                           plot='comparison.png' if summary['plot']['status'] == 'written' else None)
    (output_dir / 'summary.json').write_text(
        json.dumps(_plain(summary), ensure_ascii=False, indent=2, allow_nan=False) + '\n',
        encoding='utf-8')
    (output_dir / 'report.md').write_text(_report(summary), encoding='utf-8')
    return summary


def write_outputs(rows, skipped, output_dir):
    """保存数值、中文报告和有数据时的图，返回含绘图状态的 summary。

    绘图失败仍保存 CSV、JSON 与报告；CLI 使用失败退出码。零可用点时
    不加载 matplotlib，并清除旧 comparison.png，避免把旧图误当新结果。
    此函数不推断采集范围，完整 manifest 上下文由 CLI 写入 run 字段。
    """
    return _save_outputs(rows, skipped, output_dir)


def _parser():
    """创建 CLI；含列表的选项建议放在子命令之后。"""
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--stark-dir', type=Path, default=argparse.SUPPRESS,
                        help='STARK-B 缓存目录，默认脚本目录/stark-b')
    shared.add_argument('--sample-dir', type=Path, default=argparse.SUPPRESS,
                        help='原子输入目录，默认脚本目录/sample')
    shared.add_argument('--output-dir', type=Path, default=argparse.SUPPRESS,
                        help='比较输出目录，默认脚本目录/stark-b/comparison')
    shared.add_argument('--refresh', action='store_true', default=argparse.SUPPRESS,
                        help='抓取阶段刷新缓存；compare 始终只读取本地文件')
    shared.add_argument('--delay', type=float, default=argparse.SUPPRESS,
                        help='抓取请求间隔秒数（默认 1）；compare 不使用')
    shared.add_argument('--workers', type=int, default=argparse.SUPPRESS,
                        help='STARK 物种下载并发数 1-4（默认 1），共享请求节流')
    shared.add_argument('--elements', nargs='+', default=argparse.SUPPRESS, metavar='ELEMENT',
                        help='抓取元素范围，空格或逗号分隔；默认全部；compare 不筛选已缓存数据')
    shared.add_argument('--charges', nargs='+', default=argparse.SUPPRESS, metavar='Q',
                        help='抓取实际电荷范围，默认全部；比较始终仅 q=2/3')
    shared.add_argument('--allow-partial', action='store_true', default=argparse.SUPPRESS,
                        help='显式允许从未完整的抓取缓存加载数据，并在报告中注明')
    parser = argparse.ArgumentParser(description=__doc__, parents=[shared],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', metavar='COMMAND')
    for command, help_text in (
            ('fetch-stark', '抓取 STARK-B 全部电子 FWHM；可显式限制物种范围'),
            ('fetch-atomic', '读取本地 STARK 表，准备严格原子输入及 missing 清单'),
            ('compare', '只用本地缓存比较、写报告并绘图'),
            ('all', '依次执行 fetch-stark、fetch-atomic、compare')):
        commands.add_parser(command, parents=[shared], help=help_text, description=help_text)
    # 解析后填充缺省值，避免子命令缺省值覆盖前置公共选项。
    return parser


def _options(args):
    """规范目录和抓取范围，默认范围为全部物种而不是 q=2/3。"""
    root = Path(__file__).resolve().parent
    defaults = dict(stark_dir=root / 'stark-b', sample_dir=root / 'sample',
                    output_dir=root / 'stark-b' / 'comparison', refresh=False,
                    delay=1., workers=1, elements=None, charges=None, allow_partial=False)
    for name, default in defaults.items():
        if not hasattr(args, name):
            setattr(args, name, default)
    if not math.isfinite(args.delay) or args.delay < 0:
        raise ValueError('--delay 必须是有限非负秒数')
    if not 1 <= args.workers <= 4:
        raise ValueError('--workers 必须为 1 到 4')
    if args.elements is not None:
        elements = [part.strip() for token in args.elements for part in token.split(',') if part.strip()]
        if not elements or any(not re.fullmatch(r'[A-Z][a-z]?', part) for part in elements):
            raise ValueError('--elements 必须使用元素符号，例如 Si Fe 或 Si,Fe')
        args.elements = list(dict.fromkeys(elements))
    if args.charges is not None:
        values = [part.strip() for token in args.charges for part in token.split(',') if part.strip()]
        if not values or any(not re.fullmatch(r'[0-9]+', part) for part in values):
            raise ValueError('--charges 必须是非负整数实际电荷，例如 0 1 2 3')
        args.charges = list(dict.fromkeys(int(value) for value in values))
    return args


def _show_manifest(stage, manifest):
    """打印阶段状态和简短计数，不打印可能很大的原始 payload。"""
    if isinstance(manifest, Mapping):
        selected = {name: _plain(manifest[name]) for name in (
            'status', 'scope', 'filters', 'complete', 'counts', 'ready', 'missing',
            'candidate_tables', 'error', 'reason') if name in manifest}
        print(f'{stage}: ' + json.dumps(selected, ensure_ascii=False, allow_nan=False), flush=True)
    else:
        print(f'{stage}: {_plain(manifest)}', flush=True)


def _check_fetch_manifest(manifest, allow_partial):
    """识别抓取器明确报告的不完整状态；完整性仍由加载器严格校验。"""
    if not isinstance(manifest, Mapping):
        raise ValueError('fetch_stark_database 必须返回 manifest 对象')
    status = str(manifest.get('status') or '').lower()
    if status in ('failed', 'error'):
        raise RuntimeError(f"STARK-B 抓取失败: {manifest.get('reason') or manifest.get('error') or status}")
    for failure in manifest.get('failures') or []:
        print('STARK-B 采集问题: ' + json.dumps(_plain(failure), ensure_ascii=False),
              file=sys.stderr, flush=True)
    incomplete = (manifest.get('complete') is False or status in ('partial', 'incomplete'))
    if incomplete:
        if not allow_partial:
            raise RuntimeError('STARK-B 抓取未完整；查看抓取 manifest。需继续时显式指定 --allow-partial')
        print('警告：显式允许使用不完整 STARK-B 抓取结果。', file=sys.stderr, flush=True)


def _compare_stage(args, tables, load_warnings):
    """串联本地比较并输出清晰结果；零比较点和绘图失败使用非零退出码。"""
    from stark_atomic_data import load_model_inputs

    try:
        models = load_model_inputs(args.sample_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # 原子文件缺失或校验失败时不猜参数，仍保留每点 missing 清单。
        models = {}
        message = f'原子输入不可用: {type(exc).__name__}: {exc}'
        category = 'AtomicInputMissing' if isinstance(exc, FileNotFoundError) else 'AtomicInputInvalid'
        load_warnings = load_warnings + [dict(category=category, message=message)]
        print(message, file=sys.stderr, flush=True)
    rows, skipped = compare_tables(tables, models)
    run = _run_metadata(args, tables, models, load_warnings)
    summary = _save_outputs(rows, skipped, args.output_dir, run=run)
    coverage = summary['coverage']
    print(
        f"compare: {coverage['compared_points']} 点 / {coverage['compared_unique_lines']} 条线；"
        f"跳过 {coverage['skipped_records']} 条记录；输出 {args.output_dir}", flush=True)
    if not rows:
        print('无可用比较点，不能评价模型精度；请查看 skipped.csv 与 report.md。',
              file=sys.stderr, flush=True)
        return 2
    if summary['plot']['status'] == 'failed':
        print(f"绘图失败，数值与报告已保存: {summary['plot']['reason']}", file=sys.stderr, flush=True)
        return 1
    print(f"每线等权 MARE={summary['overall']['line_balanced']['mare_percent']:.4g}%", flush=True)
    return 0


def _load_tables(args, loader):
    """保留 partial 加载警告，供 summary/report 与终端共同审查。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        tables = loader(args.stark_dir, allow_partial=args.allow_partial)
    retained = [dict(category=item.category.__name__, message=str(item.message)) for item in caught]
    for item in retained:
        print(f"加载警告 [{item['category']}]: {item['message']}", file=sys.stderr, flush=True)
    return tables, retained


def _failure_outputs(args, exc):
    """比较流水线在加载阶段失败时仍保留运行级 skipped 和无结论报告。"""
    message = f'{type(exc).__name__}: {exc}'
    notices = [dict(category='PipelineFailure', message=message)]
    run = _run_metadata(args, [], {}, notices)
    run['pipeline_error'] = message
    skipped = []
    _skip(skipped, dict(record_kind='run', element=None, charge=None,
                        atomic_quality='unknown', method='unreported',
                        reference_method_family='unreported'),
          [('pipeline_failed', f'{args.command} 在逐点比较前失败: {message}')])
    _save_outputs([], skipped, args.output_dir, run=run)
    print(f'失败上下文已保存到 {args.output_dir}；没有生成比较图。', file=sys.stderr, flush=True)


def main(argv=None):
    """运行显式 CLI 子命令；没有任务时仅显示帮助，不执行任何阶段。"""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    options_ready, incomplete_stage = False, False
    try:
        args = _options(args)
        options_ready = True
        from stark_data_collect import fetch_stark_database, load_stark_tables

        if args.command in ('compare', 'fetch-atomic') and (args.elements is not None or args.charges is not None):
            print('说明：--elements/--charges 仅用于 fetch-stark；本子命令读取缓存全部表。',
                  file=sys.stderr, flush=True)
        if args.command in ('fetch-stark', 'all'):
            print('fetch-stark: 开始抓取电子 FWHM；抓取范围默认全部物种。', flush=True)
            manifest = fetch_stark_database(
                args.stark_dir, refresh=args.refresh, delay=args.delay,
                elements=args.elements, charges=args.charges, workers=args.workers)
            _show_manifest('fetch-stark', manifest)
            _check_fetch_manifest(manifest, args.allow_partial)
            incomplete_stage = manifest.get('complete') is False
            if args.command == 'fetch-stark':
                return 1 if incomplete_stage else 0
        tables, load_warnings = _load_tables(args, load_stark_tables)
        print(f'load-stark: 已加载 {len(tables)} 张原始表；模型只计算 q=2/3。', flush=True)
        if args.command in ('fetch-atomic', 'all'):
            from stark_atomic_data import prepare_atomic_samples

            manifest = prepare_atomic_samples(
                tables, args.sample_dir, refresh=args.refresh, delay=args.delay)
            _show_manifest('fetch-atomic', manifest)
            if isinstance(manifest, Mapping) and str(manifest.get('status')).lower() in ('failed', 'error'):
                raise RuntimeError(f"原子数据准备失败: {manifest.get('reason') or manifest.get('error')}")
            if isinstance(manifest, Mapping):
                incomplete_stage = incomplete_stage or manifest.get('complete') is False
                for species in manifest.get('species') or []:
                    if isinstance(species, Mapping) and species.get('status') not in ('ok', 'ready'):
                        print('原子采集问题: ' + json.dumps(_plain(species), ensure_ascii=False),
                              file=sys.stderr, flush=True)
            if args.command == 'fetch-atomic':
                return 1 if isinstance(manifest, Mapping) and manifest.get('complete') is False else 0
        result = _compare_stage(args, tables, load_warnings)
        if result == 0 and incomplete_stage:
            print('已保存可用子集的比较结果，但有采集阶段未完整，退出码为 1。',
                  file=sys.stderr, flush=True)
            return 1
        return result
    except KeyboardInterrupt:
        print('操作已中断；请检查阶段 manifest 后重试。', file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        print(f'{args.command} 失败: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        if options_ready and args.command in ('compare', 'all'):
            try:
                _failure_outputs(args, exc)
            except Exception as output_exc:
                print(f'无法保存失败报告: {type(output_exc).__name__}: {output_exc}',
                      file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
