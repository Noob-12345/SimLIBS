import { canonical, numeric, symbols, validateParams, type BatchSample, type Composition, type ElementDraft, type ParameterDraft, type Spectrum, type ValidParams } from './model'

// Deliberately synthetic. No line database, scientific transitions, or engine calls.
export function generateSpectrum(params: ValidParams, composition: Composition[], id = 'illustrative-preview', nodeLimit = 12000): Spectrum {
  const span = params.high - params.low
  const requested = Math.ceil(span / (params.resampleStep ?? params.step))
  const count = Math.max(600, Math.min(nodeLimit, requested))
  const xs = Array.from({ length: count + 1 }, (_, i) => i === count ? params.high : params.low + span * i / count)
  // Bounded visual composition only: each peak responds differently, even after normalization.
  // At the default Te=1 / Ne=1e17 the weights remain 1. No physical transitions are modelled.
  const visualTe = Math.tanh((params.te - 1) / .6)
  const visualNe = Math.tanh(Math.log10(params.ne) - 17)
  const elements = composition.filter(c => c.pct > 0).map(c => {
    const seed = symbols.indexOf(c.symbol) + 1
    const peaks = Array.from({ length: 16 }, (_, i) => {
      // Exponent is bounded to [-1.2, 1.2], giving finite, strictly positive relative weights.
      const visualWeight = Math.exp(.65 * visualTe * Math.sin((i + 1) * 1.71 + seed * .31) + .55 * visualNe * Math.cos((i + 1) * 1.13 + seed * .47))
      return { at: .025 + ((seed * 37 + i * 73) % 947) / 1000, height: (.12 + ((seed * 29 + i * 41) % 83) / 100) * visualWeight }
    })
    const width = params.broaden ? Math.min(.045, Math.max(.0014, 1.1 / Math.sqrt(params.resolution) * .14 + (params.gaussian + params.lorentz) / span)) : .0013
    const amplitude = c.pct / 100 * (.8 + params.te * .2) * (1 + (Math.log10(params.ne) - 17) * .08)
    const ys = xs.map((_, index) => (.004 + .001 * (1 + Math.sin(index / count * (175 + seed)))) * amplitude)
    for (const p of peaks) {
      const height = p.height * (params.flux === 'energy' ? 1.25 - p.at * .4 : 1)
      if (height < params.threshold) continue
      const first = Math.max(0, Math.floor((p.at - width * 6) * count)), last = Math.min(count, Math.ceil((p.at + width * 6) * count))
      for (let i = first; i <= last; i++) ys[i] += height * Math.exp(-(((i / count - p.at) / width) ** 2)) * amplitude
    }
    return { symbol: c.symbol, ys }
  })
  const total = xs.map((_, i) => elements.reduce((sum, e) => sum + e.ys[i]!, 0))
  return { id, title: `${composition.map(c => `${c.symbol} ${formatPct(c.pct)}%`).join(' / ')}`, xs, total, elements, params: { ...params }, composition: composition.map(c => ({ ...c })), source: { kind: 'frontend_demo', illustrative: true, description: '程序生成的高斯峰示意；Te/Ne 对各峰相对权重的确定性响应仅作视觉编排，不是真实物理模型，也不来自 NIST、线库或 Python，不具有科学计算意义。每帧独立生成，不做帧间谱线 morph。', generatedAt: new Date().toISOString(), nodes: xs.length, samplingNote: `演示网格 ${xs.length} 节点（600–${nodeLimit} 区间限制）；请求步长 ${params.resampleStep ?? params.step} nm。导出与悬停使用同一组原始示意节点。` } }
}
function formatPct(n: number) { return Number(n.toFixed(3)) }
export function spectrumCsv(s: Spectrum): string {
  const header = ['source', 'illustrative', 'wavelength_nm', 'total_au', ...s.elements.map(e => `${e.symbol}_au`)]
  return header.join(',') + '\n' + s.xs.map((x, i) => ['frontend_demo', 'true', x, s.total[i], ...s.elements.map(e => e.ys[i])].join(',')).join('\n')
}
const quote = (value: string) => '"' + value.replace(/"/g, '""') + '"'
export function batchCsv(samples: BatchSample[]): string {
  const els = [...new Set(samples.flatMap(s => s.composition.map(c => c.symbol)))]
  return ['source', 'illustrative', 'name', 'Te[eV]', 'Ne[cm^-3]', 'R', ...els.map(e => `${e}_at%`)].join(',') + '\n' + samples.map(s => ['frontend_demo', 'true', quote(s.name), s.params.te, s.params.ne, s.params.resolution, ...els.map(e => s.composition.find(c => c.symbol === e)?.pct ?? 0)].join(',')).join('\n')
}
export const templateCsv = 'source,illustrative,name,Fe_at%,Al_at%,Te[eV],Ne[cm^-3],R\nfrontend_demo,true,Fe-demo,100,0,1,1e17,1000\nfrontend_demo,true,Fe-Al-demo,70,30,1.2,2e17,2000\nfrontend_demo,true,Al-demo,0,100,0.9,8e16,1500\n'
export function parseCsv(text: string): string[][] {
  if (text.length > 2_000_000) throw new Error('演示 CSV 最大支持 2 MB')
  const rows: string[][] = []; let row: string[] = [], field = '', quoted = false, closedQuote = false
  for (let i = 0; i < text.length; i++) {
    const char = text[i]!
    if (closedQuote && ![',','\n','\r',' ','\t'].includes(char)) throw new Error('CSV 闭合引号后须为分隔符或换行')
    if (char === '"') { if (quoted && text[i + 1] === '"') { field += '"'; i++ } else if (quoted) { quoted = false; closedQuote = true } else if (field === '') quoted = true; else throw new Error('CSV 引号须从字段起始处开始') }
    else if (char === ',' && !quoted) { row.push(field.trim()); field = ''; closedQuote = false }
    else if ((char === '\n' || char === '\r') && !quoted) { if (char === '\r' && text[i + 1] === '\n') i++; row.push(field.trim()); if (row.some(c => c !== '')) rows.push(row); row = []; field = ''; closedQuote = false }
    else field += char
  }
  if (quoted) throw new Error('CSV 引号没有闭合')
  row.push(field.trim()); if (row.some(c => c !== '')) rows.push(row)
  return rows
}
export function validateTemplate(text: string, base: ParameterDraft): BatchSample[] {
  const rows = parseCsv(text.replace(/^\uFEFF/, '')), header = rows.shift()
  if (!header || !rows.length) throw new Error('CSV 须包含表头及至少 1 行样本')
  if (rows.length > 500) throw new Error('界面演示最多支持 500 行 CSV 样本')
  if (new Set(header).size !== header.length) throw new Error('CSV 存在重复表头')
  const compColumns = header.map((h, i) => ({ match: /^([A-Za-z]{1,3})_at%$/.exec(h), i })).filter(c => c.match)
  if (!compColumns.length || compColumns.length > 32) throw new Error('CSV 须包含 1–32 个元素列，例如 Fe_at%')
  const compSymbols = compColumns.map(c => canonical(c.match![1]!))
  if (compSymbols.some(e => !e) || new Set(compSymbols).size !== compSymbols.length) throw new Error('CSV 元素列无效或大小写重复')
  for (const h of header) if (!/^[A-Za-z]{1,3}_at%$/.test(h) && !['source','illustrative','name','Te[eV]','Ne[cm^-3]','R'].includes(h)) throw new Error(`不支持的列：${h}`)
  return rows.map((row, i) => {
    try {
      if (row.length !== header.length) throw new Error(`列数为 ${row.length}，表头为 ${header.length}`)
      const get = (key: string) => header.includes(key) ? row[header.indexOf(key)]! : undefined
      const p = { ...base, te: get('Te[eV]') ?? base.te, ne: get('Ne[cm^-3]') ?? base.ne, resolution: get('R') ?? base.resolution }
      const composition = compColumns.map((c, j) => ({ symbol: compSymbols[j]!, pct: numeric(row[c.i]!, `${compSymbols[j]} 占比`, 0, 100) }))
      if (Math.abs(composition.reduce((s, c) => s + c.pct, 0) - 100) > 1e-6) throw new Error('元素占比总和须为 100%')
      return { name: get('name') || `CSV-demo-${i + 1}`, params: validateParams(p), composition }
    } catch (e) { throw new Error(`第 ${i + 2} 行：${e instanceof Error ? e.message : '数据无效'}`) }
  })
}
export interface RandomRules { te: boolean; teMin: string; teMax: string; ne: boolean; neMin: string; neMax: string }
export function seededRandom(seed: number) { let value = seed >>> 0; return () => { value += 0x6D2B79F5; let t = value; t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296 } }
export function randomSamples(p: ParameterDraft, rows: ElementDraft[], rules: RandomRules, count: number, seed: number): BatchSample[] {
  const rng = seededRandom(seed)
  const bounds = (enabled: boolean, min: string, max: string, label: string, lo: number, hi: number) => { if (!enabled) return null; const a = numeric(min, `${label} 下界`, lo, hi), b = numeric(max, `${label} 上界`, lo, hi); if (a > b) throw new Error(`${label} 下界不能大于上界`); return [a, b] as const }
  const te = bounds(rules.te, rules.teMin, rules.teMax, 'Te', .01, 100), ne = bounds(rules.ne, rules.neMin, rules.neMax, '实际 Ne', 1e10, 1e23)
  const base = validateParams(p, { ...(te ? { te: te[0] } : {}), ...(ne ? { ne: ne[0] } : {}) })
  if (!rows.length || rows.length > 32) throw new Error('组成须包含 1–32 个元素')
  const concentrations = rows.map(e => { const symbol = canonical(e.symbol); if (!symbol) throw new Error('随机组成存在无效元素'); const min = numeric(e.random ? e.min : e.pct, `${symbol} 浓度下界 / 固定值`, 0, 100), max = e.random ? numeric(e.max, `${symbol} 浓度上界`, 0, 100) : min; if (min > max) throw new Error(`${symbol} 浓度下界不能大于上界`); return { symbol, min, max } })
  if (new Set(concentrations.map(c => c.symbol)).size !== rows.length) throw new Error('随机组成元素重复')
  const sumMin = concentrations.reduce((s, c) => s + c.min, 0), sumMax = concentrations.reduce((s, c) => s + c.max, 0)
  if (sumMin > 100 + 1e-7 || sumMax < 100 - 1e-7) throw new Error('浓度上下界无法容纳 100%，请调整固定值或范围')
  return Array.from({ length: count }, (_, i) => {
    let remaining = 100
    const composition = concentrations.map((c, j) => {
      const rest = concentrations.slice(j + 1), min = Math.max(c.min, remaining - rest.reduce((s, e) => s + e.max, 0)), max = Math.min(c.max, remaining - rest.reduce((s, e) => s + e.min, 0))
      const pct = j === concentrations.length - 1 ? remaining : min + rng() * Math.max(0, max - min)
      remaining -= pct; return { symbol: c.symbol, pct }
    })
    const params = { ...base, te: te ? te[0] + rng() * (te[1] - te[0]) : base.te, ne: ne ? ne[0] + rng() * (ne[1] - ne[0]) : base.ne }
    if (p.mode === 'local' && p.broaden && p.temperatureMode === 'linked') params.temperature = params.te * 11604.518
    return { name: `Random-demo-${i + 1}`, params, composition }
  })
}
