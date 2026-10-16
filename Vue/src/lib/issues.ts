import { canonical, numeric, type ElementDraft, type ParameterDraft } from './model'
import { type RandomRules } from './demo'
export type Issues = Record<string, string>
function numberIssue(out: Issues, key: string, value: string | number, label: string, min: number, max: number, integer = false): number | undefined {
  try { return numeric(value, label, min, max, integer) } catch (error) { out[key] = error instanceof Error ? error.message : '输入无效'; return undefined }
}
export function issueAttrs(message: string | undefined, id: string) { return { 'aria-invalid': !!message, 'aria-describedby': message ? id : undefined, 'aria-description': message || undefined, 'data-issue': message || undefined } }
export function parameterIssues(p: ParameterDraft, overrides: Partial<Record<'te' | 'ne' | 'resolution', number>> = {}): Issues {
  const out: Issues = {}
  if (overrides.te === undefined) numberIssue(out, 'te', p.te, 'Te', .01, 100)
  if (overrides.ne === undefined) numberIssue(out, 'ne', p.ne, '实际 Ne', 1e10, 1e23)
  if (overrides.resolution === undefined) numberIssue(out, 'resolution', p.resolution, 'R', 1, 1000000, true)
  const low = numberIssue(out, 'low', p.low, '波长下界', 1, 100000), high = numberIssue(out, 'high', p.high, '波长上界', 1, 100000)
  if (low !== undefined && high !== undefined && high <= low) out.high = '波长上界须大于下界'
  numberIssue(out, 'step', p.step, '采样步长', .000001, low !== undefined && high !== undefined && high > low ? high - low : Number.MAX_VALUE)
  numberIssue(out, 'charge', p.charge, '离子上限', 0, 2, true)
  if (p.mode === 'local' && p.broaden) {
    numberIssue(out, 'gaussian', p.gaussian, '高斯 FWHM', 0, 100); numberIssue(out, 'lorentz', p.lorentz, '洛伦兹 FWHM', 0, 100)
    if (p.temperatureMode === 'manual') numberIssue(out, 'temperature', p.temperature, '重粒子温度', 0, 1e8)
  }
  if (p.mode === 'client') { if (p.center.trim()) numberIssue(out, 'center', p.center, '线中心舍入位', 0, 12, true); numberIssue(out, 'threshold', p.threshold, '选线阈值', 0, 1) }
  if (p.resample) numberIssue(out, 'resampleStep', p.resampleStep, '统一网格步长', .000001, low !== undefined && high !== undefined && high > low ? high - low : Number.MAX_VALUE)
  return out
}
export function compositionIssues(rows: ElementDraft[], random = false): Issues {
  const out: Issues = {}, seen = new Set<string>(), concentrations: { row: ElementDraft; min: number; max: number }[] = []
  rows.forEach((row, index) => {
    const key = `${row.id}.`, symbol = canonical(row.symbol)
    if (!symbol || seen.has(symbol)) out.composition = '请使用有效元素，并移除重复项。'; seen.add(symbol)
    if (random) {
      const min = numberIssue(out, key + (row.random ? 'min' : 'pct'), row.random ? row.min : row.pct, `${symbol} 浓度下界 / 固定值`, 0, 100)
      const max = row.random ? numberIssue(out, key + 'max', row.max, `${symbol} 浓度上界`, 0, 100) : min
      if (min !== undefined && max !== undefined) { if (min > max) out[key + 'max'] = `${symbol} 浓度下界不能大于上界`; concentrations.push({ row, min, max }) }
    } else if (index < rows.length - 1 || rows.length === 1) numberIssue(out, key + 'pct', row.pct, `${symbol} 比例`, 0, 100)
  })
  if (!random) {
    const preceding = rows.slice(0, -1), total = preceding.reduce((sum, row) => sum + Number(row.pct), 0)
    if (!Object.keys(out).length && total > 100 + 1e-6) preceding.filter(row => Number(row.pct) > 0).forEach(row => { out[`${row.id}.pct`] = '前序元素比例合计已超过 100%，请调小前序元素比例，为最后一个元素释放余额。' })
    if (!Object.keys(out).length && rows.length) numberIssue(out, `${rows[rows.length - 1]!.id}.pct`, rows[rows.length - 1]!.pct, '最后一个元素比例', 0, 100)
  } else if (!Object.keys(out).length && concentrations.length === rows.length) {
    const min = concentrations.reduce((sum, c) => sum + c.min, 0), max = concentrations.reduce((sum, c) => sum + c.max, 0)
    if (min > 100 + 1e-7 || max < 100 - 1e-7) concentrations.forEach(c => { out[`${c.row.id}.${c.row.random ? min > 100 ? 'min' : 'max' : 'pct'}`] = '请调整元素浓度范围，使总比例能够达到 100%。' })
  }
  return out
}
export function batchIssues(mode: string, count: string, packageSize: string, seed: string, rules: RandomRules, text: string): Issues {
  const out: Issues = {}; numberIssue(out, 'packageSize', packageSize, '每包数', 1, 5000, true)
  if (mode === 'template') { const error = text ? '' : '请选择本地 CSV 模板'; if (error) out.template = error; return out }
  numberIssue(out, 'count', count, '样本数', 1, 5000, true)
  if (mode === 'random') {
    numberIssue(out, 'seed', seed, '随机种子', 0, 4294967295, true)
    for (const key of ['te', 'ne'] as const) if (rules[key]) {
      const a = numberIssue(out, key + 'Min', rules[key === 'te' ? 'teMin' : 'neMin'], `${key} 下界`, key === 'te' ? .01 : 1e10, key === 'te' ? 100 : 1e23)
      const b = numberIssue(out, key + 'Max', rules[key === 'te' ? 'teMax' : 'neMax'], `${key} 上界`, key === 'te' ? .01 : 1e10, key === 'te' ? 100 : 1e23)
      if (a !== undefined && b !== undefined && a > b) out[key + 'Max'] = '下界不能大于上界'
    }
  }
  return out
}
export function scanIssues(axis: 'te' | 'ne' | 'resolution', from: string, to: string, count: string): Issues {
  const out: Issues = {}, min = axis === 'te' ? .01 : axis === 'ne' ? 1e10 : 1, max = axis === 'te' ? 100 : axis === 'ne' ? 1e23 : 1000000
  const a = numberIssue(out, 'from', from, '扫描起点', min, max, axis === 'resolution'), b = numberIssue(out, 'to', to, '扫描终点', min, max, axis === 'resolution')
  if (a !== undefined && b !== undefined && a >= b) out.to = '扫描终点须大于起点'
  numberIssue(out, 'count', count, '帧数', 2, 200, true); return out
}
