import { computed, onScopeDispose, reactive, watch } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { service } from './backend'

export interface SettingsTarget { endpoint: string; token: string }
export interface ServiceSettings {
  output_dir: string; driver: string
  line_database_override?: string; line_database?: string; default_line_database?: string
  settings_rollback?: string
}
export const targetKey = (target: SettingsTarget) => `${target.endpoint}\n${target.token}`
export const currentTarget = (): SettingsTarget => ({ endpoint: service.endpoint, token: service.token })
export const isCurrentTarget = (target: SettingsTarget) => service.connected && targetKey(target) === targetKey(currentTarget())
export const supportsLibrary = (config: ServiceSettings) => ['line_database_override', 'line_database', 'default_line_database'].every(key => typeof config[key as keyof ServiceSettings] === 'string')

// Capture the transport for the whole transaction, including rollback. A connection
// change must never send an old server's library or rollback settings to a new one.
export async function settingsRequest<T = ServiceSettings>(target: SettingsTarget, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${target.endpoint}/api${path}`, { method: body === undefined ? 'GET' : 'POST', headers: { 'X-SimLIBS-Token': target.token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(120000) })
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error?.message || `计算服务 HTTP ${response.status}`) }
  return response.json()
}
export async function refreshLocalCapabilities(target: SettingsTarget) {
  const status = await settingsRequest<Record<string, any>>(target, '/status?mode=local')
  if (!isCurrentTarget(target)) throw new Error('连接已切换，请重新读取设置')
  service.status = status; service.capabilities = status.local ?? null
}
export function rollbackSettings(config: ServiceSettings): Record<string, string> {
  return { output_dir: config.output_dir, driver: config.driver, ...(supportsLibrary(config) ? { line_database_override: config.line_database_override! } : {}) }
}

export function useLibrarySettings() {
  const state = reactive({ draft: '', saved: '', effective: '', defaultPath: '', owner: '', supported: false, loaded: false, loading: false, selecting: false, error: '' })
  const dirty = computed(() => state.draft !== state.saved)
  let sequence = 0, editRevision = 0, internal = false
  const setDraft = (value: string) => { internal = true; state.draft = value; internal = false }
  watch(() => state.draft, () => { if (!internal) editRevision++ }, { flush: 'sync' })
  function accept(config: ServiceSettings, target: SettingsTarget, resetDraft = true) {
    if (!isCurrentTarget(target)) return false
    sequence++; state.owner = targetKey(target); state.supported = supportsLibrary(config); state.loaded = true; state.loading = false
    state.saved = state.supported ? config.line_database_override! : ''
    state.effective = config.line_database ?? ''; state.defaultPath = config.default_line_database ?? ''
    state.error = state.supported ? '' : '当前服务不支持本地谱线库设置，请更新服务后重试。'
    if (resetDraft) setDraft(state.saved)
    return true
  }
  async function load(target = currentTarget()) {
    if (!isCurrentTarget(target) || service.busy) return
    const owner = targetKey(target)
    if (owner !== state.owner) { state.owner = owner; state.saved = ''; setDraft(''); state.effective = ''; state.defaultPath = ''; state.supported = false; state.loaded = false }
    const revision = ++sequence, edit = editRevision, preserve = dirty.value
    state.loading = true; state.error = ''
    try {
      const config = await settingsRequest(target, '/settings')
      if (revision !== sequence || !isCurrentTarget(target)) return
      accept(config, target, !preserve && edit === editRevision)
    } catch (error) { if (revision === sequence && isCurrentTarget(target)) state.error = `谱线库设置读取失败：${String(error)}` }
    finally { if (revision === sequence) state.loading = false }
  }
  function discard() { setDraft(state.saved); state.error = state.supported ? '' : state.error }
  function restore(snapshot: typeof state) { if (snapshot.owner !== targetKey(currentTarget())) return; sequence++; Object.assign(state, snapshot, { loading: false, selecting: false }); editRevision++ }
  async function chooseDirectory(allowed: () => boolean) {
    if (!isTauri() || !allowed() || state.selecting) return
    const target = currentTarget(), owner = state.owner
    state.selecting = true; state.error = ''
    try {
      const path = await open({ directory: true, multiple: false, title: '选择本地谱线库目录' })
      if (path === null) return
      if (!allowed() || !isCurrentTarget(target) || owner !== state.owner) throw new Error('连接已变化，所选目录未应用')
      if (typeof path !== 'string') throw new Error('请选择单个目录')
      state.draft = path
    } catch (error) { state.error = `目录选择失败：${String(error)}` }
    finally { state.selecting = false }
  }
  watch(() => [service.connected, service.busy, service.endpoint, service.token], () => { sequence++; state.loading = false; if (service.connected && !service.busy) void load() }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { sequence++ })
  return { state, dirty, load, accept, discard, restore, chooseDirectory }
}
