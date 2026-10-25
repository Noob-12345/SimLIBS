import { advanced } from './workbench'
import { apiComposition, apiParams } from './backend'
import { numeric, validateComposition, validateParams } from './model'
import type { OpenResult } from './fileAccess'
export function applyAdvancedStark(result: OpenResult): string {
  if (result.status === 'opened') { advanced.starkText = result.text; advanced.starkName = result.name }
  return result.status === 'failed' ? result.message + '；原系数文件已保留' : ''
}
export function clearAdvancedStark() { advanced.starkText = ''; advanced.starkName = '' }
export const advancedModels = [{ value: 'nist', label: '客户端模拟' }] as const
export const densityChoices = [{ value: 'charge_balance', label: '由 Ne 与全阶段布居按电荷守恒反推' }, { value: 'specified', label: '指定总原子/离子数密度' }] as const
export function changeAdvancedModel(_value: string) {
  advanced.model = 'nist'
  if (advanced.selfAbsorption) advanced.starkBroadening = true
}
export function setAdvancedAbsorption(value: boolean) {
  advanced.selfAbsorption = value
  if (value) advanced.starkBroadening = true
}
export function setAdvancedStark(value: boolean) {
  advanced.starkBroadening = value
  if (!value) advanced.selfAbsorption = false
}
export function prepareAdvanced(compositionError = '') {
  if (compositionError) throw Error(compositionError)
  const p = validateParams({ ...advanced.params, mode: 'local', flux: 'photon', broaden: true, temperatureMode: 'manual', temperature: '0', gaussian: '0', lorentz: '0', resample: false })
  const comp = validateComposition(advanced.composition)
  if (advanced.selfAbsorption && !advanced.starkBroadening) throw Error('开启自吸收必须启用 Stark 展宽')
  const responses = Object.fromEntries(comp.map(e => [e.symbol, advanced.matrix ? numeric(advanced.responses[e.symbol] ?? '1', `${e.symbol} 响应`, 0, 1e6) : 1]))
  if (advanced.matrix && !comp.some(e => e.pct > 0 && responses[e.symbol]! > 0)) throw Error('有效元素响应不能全为零')
  return { params: apiParams(p), composition: apiComposition(comp), advanced: {
    model: 'nist', self_absorption: advanced.selfAbsorption, instrument_broadening: advanced.instrumentBroadening, matrix: advanced.matrix,
    path_length_m: !advanced.selfAbsorption ? 0 : numeric(advanced.pathLength, '光程 L', 0, 1e6), responses,
    te_factor: advanced.matrix ? numeric(advanced.teFactor, 'Te倍率', 1e-4, 1e4) : 1, ne_factor: advanced.matrix ? numeric(advanced.neFactor, 'Ne倍率', 1e-4, 1e4) : 1,
    stark_broadening: advanced.starkBroadening, density_mode: advanced.selfAbsorption ? advanced.densityMode : 'charge_balance', number_density_cm3: advanced.selfAbsorption && advanced.densityMode === 'specified' ? numeric(advanced.numberDensity, '总数密度', 1e-30, 1e24) : 1e16, stark_csv: advanced.starkBroadening ? advanced.starkText : '', stark_name: advanced.starkBroadening ? advanced.starkName : '', missing_stark: advanced.missingStark || 'unbroadened'
  } }
}
export function isNistAdvanced(version: unknown) { return typeof version === 'string' && version.startsWith('nist-lines-') }
export function advancedFlags(origin?: Record<string, unknown>) {
  const config = origin?.advanced as Record<string, unknown> | undefined
  const known = isNistAdvanced(origin?.model_version) || origin?.model_version === 'paper-eq7-stark-sa-1'
  const flag = (key: string, fallback: boolean) => typeof origin?.[key] === 'boolean' ? origin[key] as boolean : typeof config?.[key] === 'boolean' ? config[key] as boolean : fallback
  return { known, absorption: flag('self_absorption', true), stark: flag('stark_broadening', true), instrument: flag('instrument_broadening', true) }
}
export function advancedResultLabel(version: unknown, origin?: Record<string, unknown>) {
  if (isNistAdvanced(version)) {
    const flags = advancedFlags(origin)
    if (version === 'nist-lines-sticks-1') return '客户端模拟 · 未展宽网格投影'
    if (version === 'nist-lines-instrument-1') return '客户端模拟 · 仪器高斯'
    return flags.absorption && version !== 'nist-lines-stark-1' ? '客户端模拟 · 逐线自吸收' : flags.instrument ? '客户端模拟 · Stark / 仪器 Voigt' : '客户端模拟 · 纯 Stark Lorentz'
  }
  return version === 'paper-eq7-stark-sa-1' ? '离线论文 Eq.7 / Stark' : '已保存的旧高级模型'
}
