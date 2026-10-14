export type Page = 'single' | 'batch' | 'scan' | 'advanced' | 'jobs' | 'settings'
export type TaskKind = 'single' | 'batch' | 'scan' | 'advanced'
export type Mode = 'local' | 'server' | 'client'
export interface ParameterDraft {
  te: string; ne: string; resolution: string; low: string; high: string; step: string; charge: string
  mode: Mode; flux: 'photon' | 'energy'; broaden: boolean; gaussian: string; lorentz: string
  temperatureMode: 'linked' | 'manual'; temperature: string; convention: 'physics' | 'nist'
  center: string; threshold: string; resample: boolean; resampleStep: string; headless: boolean
}
export interface ElementDraft { id: number; symbol: string; pct: string; random: boolean; min: string; max: string }
export interface Composition { symbol: string; pct: number }
export interface ValidParams {
  te: number; ne: number; resolution: number; low: number; high: number; step: number; charge: number
  mode: Mode; flux: 'photon' | 'energy'; broaden: boolean; gaussian: number; lorentz: number
  temperature: number; temperatureMode?: 'linked' | 'manual'; convention: 'physics' | 'nist'; center: number | null; threshold: number
  resample: boolean; resampleStep: number | null; headless: boolean
}
export interface Spectrum {
  comparison?: { thin: number[]; nominal: number[] }
  id: string; title: string; xs: number[]; total: number[]; elements: { symbol: string; ys: number[] }[]
  params: ValidParams; composition: Composition[]; source: { kind: string; illustrative: boolean; description: string; generatedAt: string; nodes: number; samplingNote: string; origin?: Record<string, unknown>; manifest?: Record<string, unknown>; style?: string }; jobId?: string
}
export interface BatchSample { name: string; params: ValidParams; composition: Composition[] }
export interface ScanResult { axis: 'te' | 'ne' | 'resolution'; frames: { value: number; spectrum?: Spectrum }[]; jobId?: string }
export interface DemoTask {
  id: string; kind: TaskKind; status: 'running' | 'completed' | 'cancelled' | 'failed'; progress: number
  startedAt: number; endedAt?: number; summary: string; detail: string
  result?: Spectrum | BatchSample[] | ScanResult
  resumable?: boolean; events?: string[]; duration?: string
  resultError?: string
}
export const symbols = 'H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split(' ')
let nextElement = 1
export function elementDraft(symbol = 'Fe', pct = '100'): ElementDraft { return { id: nextElement++, symbol, pct, random: false, min: '0', max: '100' } }
export function defaults(): ParameterDraft { return { te: '1', ne: '1e17', resolution: '1000', low: '200', high: '500', step: '0.05', charge: '2', mode: 'local', flux: 'photon', broaden: false, gaussian: '0', lorentz: '0', temperatureMode: 'linked', temperature: '0', convention: 'physics', center: '', threshold: '0', resample: false, resampleStep: '0.1', headless: true } }
export function numeric(value: string | number, label: string, min = Number.MIN_VALUE, max = Number.MAX_VALUE, integer = false): number {
  const text = String(value).trim()
  if (!text || !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text)) throw new Error(`${label}须为有效数值，不能留空`)
  const number = Number(text)
  if (!Number.isFinite(number) || number < min || number > max) throw new Error(`${label}须在 ${min === Number.MIN_VALUE ? '大于 0' : min} 至 ${max === Number.MAX_VALUE ? '有限值' : max} 范围内`)
  if (integer && !Number.isSafeInteger(number)) throw new Error(`${label}须为安全整数`)
  return number
}
export function validateParams(p: ParameterDraft, overrides: Partial<Record<'te' | 'ne' | 'resolution', number>> = {}): ValidParams {
  const te = overrides.te ?? numeric(p.te, 'Te', .01, 100)
  const ne = overrides.ne ?? numeric(p.ne, '实际 Ne', 1e10, 1e23)
  const resolution = overrides.resolution ?? numeric(p.resolution, 'R', 1, 1000000, true)
  numeric(te, 'Te', .01, 100); numeric(ne, '实际 Ne', 1e10, 1e23); numeric(resolution, 'R', 1, 1000000, true)
  const low = numeric(p.low, '波长下界', 1, 100000), high = numeric(p.high, '波长上界', 1, 100000)
  if (high <= low) throw new Error('波长上界须大于下界')
  const broaden = p.mode !== 'local' || p.broaden
  return { te, ne, resolution, low, high, step: numeric(p.step, '采样步长', .000001, high - low), charge: numeric(p.charge, '离子上限', 0, 2, true), mode: p.mode, flux: p.mode === 'local' ? 'photon' : p.flux, broaden,
    gaussian: p.mode === 'local' && broaden ? numeric(p.gaussian, '高斯 FWHM', 0, 100) : 0,
    lorentz: p.mode === 'local' && broaden ? numeric(p.lorentz, '洛伦兹 FWHM', 0, 100) : 0,
    temperature: p.mode === 'local' && broaden ? p.temperatureMode === 'linked' ? te * 11604.518 : numeric(p.temperature, '重粒子温度', 0, 1e8) : 0,
    temperatureMode: p.temperatureMode,
    convention: p.mode === 'client' ? p.convention : p.mode === 'server' ? 'nist' : 'physics',
    center: p.mode === 'client' && p.center.trim() ? numeric(p.center, '线中心舍入位', 0, 12, true) : null,
    threshold: p.mode === 'client' ? numeric(p.threshold, '选线阈值', 0, 1) : 0,
    resample: p.resample, resampleStep: p.resample ? numeric(p.resampleStep, '统一网格步长', .000001, high - low) : null, headless: p.mode === 'server' && p.headless }
}
export function canonical(value: string): string { return symbols.find(s => s.toLowerCase() === value.trim().toLowerCase()) || '' }
export function validateComposition(rows: ElementDraft[]): Composition[] {
  if (!rows.length || rows.length > 32) throw new Error('组成须包含 1 至 32 个元素')
  if (rows.slice(0, -1).reduce((sum, e) => sum + Number(e.pct), 0) > 100 + 1e-6) throw new Error('已输入占比超过 100%，请减少前置元素占比；余额暂不可用')
  const comp = rows.map(e => { const symbol = canonical(e.symbol); if (!symbol) throw new Error(`无效元素：${e.symbol || '空值'}`); return { symbol, pct: numeric(e.pct, `${symbol} 比例`, 0, 100) } })
  if (new Set(comp.map(e => e.symbol)).size !== comp.length) throw new Error('元素重复，请使用不同元素')
  if (Math.abs(comp.reduce((sum, e) => sum + e.pct, 0) - 100) > 1e-6) throw new Error('元素占比总和须为 100%，请检查余额')
  if (!comp.some(e => e.pct > 0)) throw new Error('至少一个元素的比例须大于 0')
  return comp
}
export function balance(rows: ElementDraft[]) {
  if (!rows.length) return
  const values = rows.slice(0, -1).map(e => e.pct.trim() ? Number(e.pct) : NaN)
  if (values.some(v => !Number.isFinite(v) || v < 0 || v > 100)) { rows[rows.length - 1]!.pct = ''; return }
  const remaining = 100 - values.reduce((a, b) => a + b, 0)
  rows[rows.length - 1]!.pct = remaining < -1e-6 ? '' : String(Math.max(0, Number(remaining.toFixed(8))))
}
export function errorOf(fn: () => unknown): string { try { fn(); return '' } catch (e) { return e instanceof Error ? e.message : '输入无效' } }
export function format(value: number): string { return Math.abs(value) >= 1e5 || (Math.abs(value) < .001 && value !== 0) ? value.toExponential(3) : Number(value.toPrecision(6)).toString() }
export function elementColor(symbol: string): string { const index = Math.max(0, symbols.indexOf(symbol)); return symbol === 'Fe' ? '#ca962e' : ['#548ccc','#ae75c9','#439f98','#d77c59','#83974e','#c8759c'][index % 6]! }
export const kindLabels: Record<TaskKind, string> = { single: '单次模拟', batch: '批量模拟', scan: '参数扫描', advanced: '高级模拟' }
export const statusLabels: Record<DemoTask['status'], string> = { running: '运行中', completed: '已完成', cancelled: '已取消', failed: '失败' }
