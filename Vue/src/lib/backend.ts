import { reactive } from 'vue'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { savedPreferences, type Preferences } from './preferences'
import { validateParams, type ValidParams, type Composition, type Spectrum, type ParameterDraft } from './model'
export const service = reactive({ connected: false, busy: false, error: '', endpoint: '', token: '', python: '', label: '连接中', status: {} as Record<string, unknown>, capabilities: null as null | {ready: boolean; elements: string[]; error?: string}, defaults: null as any })
export type RuntimeState = 'ok' | 'warning' | 'error' | 'unknown' | 'checking'
export interface RuntimeReport {
  schema: number; checked_at: string
  interpreter: { executable: string; version: string; worker_executable: string }
  dependencies: { state: RuntimeState; summary: string; checks: { module: string; distribution: string; state: RuntimeState; summary: string; affected: string }[] }
  local: { state: RuntimeState; summary: string; root: string; evidence: string[]; guidance: string }
  online: { state: RuntimeState; summary: string; guidance: string }
}
export const runtime = reactive({ checking: false, heartbeat: 'unknown' as RuntimeState, pingAt: 0, checkedAt: 0, report: null as RuntimeReport | null, note: '' })
let runtimeRevision = 0, runtimeAbort: AbortController | undefined, runtimeFlight: Promise<void> | undefined
export function safeRuntimeText(value: unknown): string {
  let text = String(value ?? '')
  for (const secret of [service.token, savedPreferences.value.backendToken]) if (secret) text = text.split(secret).join('[已隐藏凭证]')
  return text.replace(/(token|authorization|password)([\s:="']+)[^\s,;]+/gi, '$1=[已隐藏]').replace(/\b[0-9a-f]{32,}\b/gi, '[已隐藏]').slice(0, 16000)
}
function resetRuntime(state: RuntimeState = 'unknown') {
  runtimeRevision++; runtimeAbort?.abort(); runtimeFlight = undefined
  Object.assign(runtime, { checking: false, heartbeat: state, pingAt: 0, checkedAt: 0, report: null, note: '' })
}
let connecting: Promise<void> | undefined
export async function connectBackend(restart = false, python?: string, preferences?: Preferences) {
  if (connecting) { await connecting.catch(() => {}); return connectBackend(restart, python, preferences) }
  const attempt = (async () => {
    resetRuntime('checking')
    service.busy = true; service.error = ''; service.connected = false; service.capabilities = null; service.defaults = null; service.status = {}; service.python = ''
    try {
      const prefs = preferences ?? savedPreferences.value
      if (isTauri() && !prefs.endpoint.trim()) Object.assign(service, await invoke('backend_connect', { restart, python: python || null }))
      else { const endpoint = prefs.endpoint.trim(); if (!endpoint) throw new Error('浏览器开发模式请配置服务地址及 session token'); const url = new URL(endpoint); if (!['http:', 'https:'].includes(url.protocol)) throw new Error('服务地址须使用 HTTP(S)'); service.endpoint = endpoint.replace(/\/$/, ''); service.token = prefs.backendToken || '' }
      const status = await request<Record<string, unknown>>('/status', undefined, false)
      service.status = status; service.label = String(status.engine_label)
      const defaults = await request('/params', undefined, false)
      service.defaults = defaults; service.capabilities = defaults.local_capabilities; service.connected = true
    } catch (e) { resetRuntime('error'); service.connected = false; service.error = safeRuntimeText(e instanceof Error ? e.message : e); service.label = '连接失败'; throw e }
    finally { service.busy = false }
  })()
  connecting = attempt
  try { await attempt }
  finally { if (connecting === attempt) connecting = undefined }
}
// Status checks never restart a live service or alter request/task semantics.
export function checkRuntime(full = true): Promise<void> {
  if (runtimeFlight) return runtimeFlight
  if (!service.connected || service.busy) return Promise.resolve()
  const revision = runtimeRevision, endpoint = service.endpoint, token = service.token
  const abort = new AbortController(); runtimeAbort = abort
  runtime.checking = true
  if (full) { runtime.report = null; runtime.note = '' }
  const current = () => revision === runtimeRevision && endpoint === service.endpoint && token === service.token && !abort.signal.aborted
  const read = async (path: string, timeout: number) => {
    const response = await fetch(endpoint + '/api' + path, { headers: { 'X-SimLIBS-Token': token }, signal: AbortSignal.any([abort.signal, AbortSignal.timeout(timeout)]) })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response.json()
  }
  let flight!: Promise<void>
  flight = (async () => {
    try {
      let status: Record<string, unknown>
      try { status = await read('/status', 5000); if (!status || typeof status !== 'object' || Array.isArray(status)) throw new Error('状态响应无效') }
      catch (error) {
        if (current()) {
          resetRuntime('error'); service.connected = false; service.capabilities = null; service.status = {}; service.defaults = null
          service.error = '后端存活检查失败：' + safeRuntimeText(error instanceof Error ? error.message : error); service.label = '连接中断'
        }
        return
      }
      if (!current()) return
      service.status = status; runtime.heartbeat = 'ok'; runtime.pingAt = Date.now()
      if (status.local && typeof status.local === 'object') service.capabilities = status.local as typeof service.capabilities
      if (!full) return
      try {
        const report = await read('/diagnostics', 22000)
        if (!current()) return
        if (report?.schema !== 1 || !report.interpreter || !Array.isArray(report.dependencies?.checks) || !report.local || !report.online) throw new Error('诊断格式不受支持')
        runtime.report = JSON.parse(safeRuntimeText(JSON.stringify(report))) as RuntimeReport
        runtime.checkedAt = Date.now()
      } catch (error) {
        if (current()) { runtime.report = null; runtime.note = `未取得依赖诊断证据（${safeRuntimeText(error instanceof Error ? error.message : error)}）。外部服务可能不支持此接口；连接与本地能力按实际返回单独显示。` }
      }
    } catch (error) {
      if (current()) { runtime.report = null; runtime.note = '诊断暂不可用：' + safeRuntimeText(error instanceof Error ? error.message : error) }
    } finally {
      if (runtimeFlight === flight) { runtimeFlight = undefined; runtime.checking = false; runtimeAbort = undefined }
    }
  })()
  runtimeFlight = flight
  return flight
}
export async function recheckRuntime() {
  if (service.busy || runtime.checking) return
  if (!service.connected) {
    try { await connectBackend(false, savedPreferences.value.pythonPath) }
    catch { return }
  }
  await checkRuntime(true)
}
export function disposeRuntime() { resetRuntime() }
export async function request<T = any>(path: string, body?: unknown, ensure = true, signal?: AbortSignal): Promise<T> {
  if (ensure && !service.connected) await connectBackend()
  const response = await fetch(service.endpoint + '/api' + path, { method: body === undefined ? 'GET' : 'POST', headers: { 'X-SimLIBS-Token': service.token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, body: body === undefined ? undefined : JSON.stringify(body), signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(120000)]) : AbortSignal.timeout(120000) })
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error?.message || `计算服务 HTTP ${response.status}`) }
  return response.json()
}
export async function download(job: string, kind: string, frame?: number): Promise<Blob> {
  if (!service.connected) await connectBackend()
  const response = await fetch(`${service.endpoint}/api/jobs/${job}/export?kind=${kind}${frame === undefined ? '' : `&frame=${frame}`}`, { headers: { 'X-SimLIBS-Token': service.token }, signal: AbortSignal.timeout(180000) })
  if (!response.ok) { const data = await response.json(); throw new Error(data.error?.message || '导出失败') }
  return response.blob()
}
export function apiParams(p: ValidParams) {
  return { te: p.te, ne: p.ne, resolution: p.resolution, low_w: p.low, up_w: p.high, max_ion_charge: p.charge, mode: p.mode, mode_version: 2,
    headless: p.headless, intensity_scale: p.flux, resample: p.resample, resample_step: p.resampleStep ?? .005,
    broadening: p.mode === 'server' ? 'nist' : 'local', broaden_convention: p.mode === 'server' ? 'nist' : p.convention,
    broaden_grid_step: p.step, broaden_center_decimals: p.center, broaden_min_rel_int: p.threshold,
    local_gaussian_nm: p.gaussian, local_lorentz_nm: p.lorentz, local_temperature_mode: p.temperatureMode ?? 'manual',
    local_temperature_K: p.temperatureMode === 'linked' ? 0 : p.temperature, local_broadening_enabled: p.broaden }
}
export const apiComposition = (comp: Composition[]) => comp.map(c => ({ el: c.symbol, pct: c.pct }))
export function fromParameters(p: any): ValidParams {
  const draft: ParameterDraft = { te: String(p.Te), ne: String(p.Ne), resolution: String(p.resolution), low: String(p.low_w), high: String(p.upper_w), step: String(p.broaden_grid_step), charge: String(p.max_ion_charge),
    mode: p.webscraping, flux: p.intensity_scale, broaden: p.local_broadening_enabled, gaussian: String(p.local_gaussian_nm), lorentz: String(p.local_lorentz_nm),
    temperatureMode: p.local_temperature_mode, temperature: String(p.local_temperature_K), convention: p.broaden_convention, center: p.broaden_center_decimals === null ? '' : String(p.broaden_center_decimals), threshold: String(p.broaden_min_rel_int), resample: p.resample, resampleStep: String(p.step), headless: p.headless }
  return validateParams(draft)
}
export function spectrumResult(data: any, job: string): Spectrum {
  const p = data.origin.parameters, params = fromParameters(p)
  if (Number.isFinite(data.meta.actual_resolution)) params.resolution = data.meta.actual_resolution
  const raw = p.webscraping === 'local' && !p.local_broadening_enabled && !p.resample
  const main = raw ? data.series.raw : data.series.interpolated ?? data.series.raw
  const curves = raw ? data.series.elements.raw : data.series.elements.interpolated ?? data.series.elements.raw
  if (!Array.isArray(main.xs) || main.xs.length !== main.ys.length) throw new Error('光谱节点结构无效')
  const elements = (curves?.curves ?? []).map((e: any) => ({ symbol: e.label, ys: e.ys }))
  if (elements.some((e: any) => e.ys.length !== main.xs.length)) throw new Error('元素贡献与总谱网格不一致')
  if (data.comparison && (data.comparison.xs.length !== main.xs.length || data.comparison.xs.some((x: number, i: number) => x !== main.xs[i]))) throw new Error('高级对照网格不一致')
  return { id: job, jobId: job, title: p.elements.join(' / '), xs: main.xs, total: main.ys, elements, params, comparison: data.comparison ? {thin: data.comparison.thin, nominal: data.comparison.nominal} : undefined,
    composition: p.elements.map((symbol: string, i: number) => ({ symbol, pct: p.percentages[i] })),
    source: { kind: data.origin.kind, illustrative: false, description: data.origin.label, generatedAt: data.manifest.created_at, nodes: main.xs.length,
      samplingNote: '完整实际 CSV 节点', origin: data.origin, manifest: data.manifest, style: data.meta.spectrum_style } }
}
export function realSpectrumCsv(s: Spectrum) { return [['wavelength','intensity',...s.elements.map(e => `${e.symbol}_intensity`),...(s.comparison ? ['matrix_thin','nominal_thin'] : [])].join(','), ...s.xs.map((x, i) => [x, s.total[i], ...s.elements.map(e => e.ys[i]), ...(s.comparison ? [s.comparison.thin[i],s.comparison.nominal[i]] : [])].join(','))].join('\n') }
