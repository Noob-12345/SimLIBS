import { computed, reactive, ref, watch } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { defaultOutputDirectory, ensureDefaultOutputDirectory } from './outputDirectory'
export type ThemeMode = 'light' | 'dark' | 'system'
export type Palette = 'amber' | 'ocean' | 'violet' | 'forest' | 'rose'
export interface Preferences { mode: ThemeMode; palette: Palette; reducedMotion: boolean; endpoint: string; pythonPath: string; driverPath: string; outputDirectory: string }
const key = 'simlibs-vue-preferences-v1'
const defaults: Preferences = { mode: 'light', palette: 'amber', reducedMotion: false, endpoint: 'http://127.0.0.1:8517', pythonPath: '', driverPath: '', outputDirectory: defaultOutputDirectory }
export const palettes: { id: Palette; label: string; color: string; dark: string; text: string }[] = [
  { id: 'amber', label: '琥珀', color: '#e5a327', dark: '#efbb58', text: '#94600d' }, { id: 'ocean', label: '海蓝', color: '#73b1e4', dark: '#83bff0', text: '#326a96' }, { id: 'violet', label: '鸢尾', color: '#ac92da', dark: '#bda1ee', text: '#7250a0' }, { id: 'forest', label: '松绿', color: '#80b9a1', dark: '#85c9ac', text: '#386b55' }, { id: 'rose', label: '蔷薇', color: '#da92a0', dark: '#eea6b4', text: '#965367' }
]
export const storageMessage = ref('')
function load(): Preferences { try { const raw = JSON.parse(localStorage.getItem(key) || '{}') as Partial<Preferences>; return { mode: ['light','dark','system'].includes(raw.mode ?? '') ? raw.mode! : 'light', palette: palettes.some(p => p.id === raw.palette) ? raw.palette! : 'amber', reducedMotion: raw.reducedMotion === true, endpoint: typeof raw.endpoint === 'string' ? raw.endpoint : defaults.endpoint, pythonPath: typeof raw.pythonPath === 'string' ? raw.pythonPath : '', driverPath: typeof raw.driverPath === 'string' ? raw.driverPath : '', outputDirectory: typeof raw.outputDirectory === 'string' && raw.outputDirectory.trim() ? raw.outputDirectory : defaultOutputDirectory } } catch { storageMessage.value = '本地偏好无法读取，已采用默认外观'; return { ...defaults } } }
export const outputDirectoryError = ref('')
void ensureDefaultOutputDirectory().catch(() => { outputDirectoryError.value = '默认输出目录无法创建，请检查目录权限' })
export const savedPreferences = ref(load())
export const preferences = reactive<Preferences>({ ...savedPreferences.value })
const media = window.matchMedia('(prefers-color-scheme: dark)'), systemDark = ref(media.matches)
const listener = () => { systemDark.value = media.matches }; media.addEventListener('change', listener)
const reduceMedia = window.matchMedia('(prefers-reduced-motion: reduce)'), systemReduced = ref(reduceMedia.matches)
const reduceListener = () => { systemReduced.value = reduceMedia.matches }; reduceMedia.addEventListener('change', reduceListener)
function appearanceSnapshot() { return { mode: preferences.mode, palette: preferences.palette, dark: preferences.mode === 'dark' || preferences.mode === 'system' && systemDark.value } }
const appliedAppearance = reactive(appearanceSnapshot())
export const actualDark = computed(() => appliedAppearance.dark)
export const appearancePhase = ref<'idle' | 'blurring' | 'clearing'>('idle')
let appearanceInitialized = false, appearanceRevision = 0
let blurTimer: ReturnType<typeof setTimeout> | undefined, clearTimer: ReturnType<typeof setTimeout> | undefined
export const preferenceDirty = computed(() => JSON.stringify(preferences) !== JSON.stringify(savedPreferences.value))
export const nativeThemeError = ref('')
let nativeBusy = false, disposed = false, themeRevision = 0
let requestedMode: ThemeMode = preferences.mode
async function syncNativeTheme() {
  if (nativeBusy || disposed || !isTauri()) return
  nativeBusy = true
  try {
    while (!disposed) {
      const revision = themeRevision, theme = requestedMode === 'system' ? null : requestedMode
      try { await getCurrentWindow().setTheme(theme); if (!disposed && revision === themeRevision) nativeThemeError.value = '' }
      catch { if (!disposed && revision === themeRevision) nativeThemeError.value = '原生标题栏主题同步失败' }
      if (revision === themeRevision) break
    }
  } finally { nativeBusy = false }
}
// Media changes update CSS only. Native requests depend solely on the selected mode.
const stopNative = watch(() => appliedAppearance.mode, mode => { requestedMode = mode; themeRevision++; void syncNativeTheme() }, { immediate: true, flush: 'sync' })
function apply() {
  const dark = actualDark.value, palette = palettes.find(p => p.id === appliedAppearance.palette) ?? palettes[0]!, root = document.documentElement
  root.dataset.theme = dark ? 'dark' : 'light'; root.dataset.reducedMotion = String(preferences.reducedMotion)
  root.style.setProperty('--accent', palette.color); root.style.setProperty('--chart', dark ? palette.dark : palette.text)
  root.style.setProperty('--accent-text', dark ? palette.dark : palette.text)
  root.style.setProperty('--accent-soft', `color-mix(in srgb, ${palette.color} ${dark ? '12%' : '11%'}, var(--panel))`)
  const switchPalette = palettes[(palettes.indexOf(palette) + 1) % palettes.length]!
  root.style.setProperty('--switch-text', dark ? switchPalette.dark : switchPalette.text)
}
function clearAppearanceTimers() { clearTimeout(blurTimer); clearTimeout(clearTimer) }
function commitAppearance(snapshot: ReturnType<typeof appearanceSnapshot>) { Object.assign(appliedAppearance, snapshot); apply() }
function requestAppearance() {
  const snapshot = appearanceSnapshot(), boot = window.__SIMLIBS_BOOT__
  document.documentElement.dataset.reducedMotion = String(preferences.reducedMotion)
  const same = snapshot.mode === appliedAppearance.mode && snapshot.palette === appliedAppearance.palette && snapshot.dark === appliedAppearance.dark
  if (!appearanceInitialized || boot && boot.phase !== 'ready' || preferences.reducedMotion || systemReduced.value) {
    appearanceInitialized = true; appearanceRevision++; clearAppearanceTimers(); commitAppearance(snapshot); appearancePhase.value = 'idle'; return
  }
  if (same && appearancePhase.value === 'idle') return
  const revision = ++appearanceRevision; clearAppearanceTimers()
  // setTheme(null) can refresh the system media query just after the peak.
  // Commit that resolved system color under the existing veil, without replaying it.
  if (!same && appearancePhase.value === 'clearing' && snapshot.mode === 'system' && appliedAppearance.mode === 'system' && snapshot.palette === appliedAppearance.palette) {
    commitAppearance(snapshot); clearTimer = setTimeout(() => { if (revision === appearanceRevision) appearancePhase.value = 'idle' }, 180); return
  }
  if (same) {
    appearancePhase.value = 'clearing'; clearTimer = setTimeout(() => { if (revision === appearanceRevision) appearancePhase.value = 'idle' }, 180); return
  }
  appearancePhase.value = 'blurring'
  blurTimer = setTimeout(() => {
    if (disposed || revision !== appearanceRevision) return
    commitAppearance(snapshot); appearancePhase.value = 'clearing'
    clearTimer = setTimeout(() => { if (!disposed && revision === appearanceRevision) appearancePhase.value = 'idle' }, 180)
  }, 200)
}
const stop = watch([() => preferences.mode, () => preferences.palette, () => preferences.mode === 'system' && systemDark.value, () => preferences.reducedMotion, systemReduced], requestAppearance, { immediate: true, flush: 'sync' })
export function savePreferences(): boolean { try { localStorage.setItem(key, JSON.stringify(preferences)); savedPreferences.value = { ...preferences }; storageMessage.value = '外观与配置已保存到本地'; return true } catch { storageMessage.value = '本地存储不可用，偏好尚未保存'; return false } }
export function discardPreferences() { Object.assign(preferences, savedPreferences.value); storageMessage.value = '已恢复上次保存的偏好' }
export function setThemeMode(mode: ThemeMode) {
  preferences.mode = mode
  try { const next = { ...savedPreferences.value, mode }; localStorage.setItem(key, JSON.stringify(next)); savedPreferences.value = next; storageMessage.value = '' } catch { storageMessage.value = '主题仅在当前应用生效，本地保存失败' }
}
export function setPalette(palette: Palette) {
  if (!palettes.some(option => option.id === palette)) return
  preferences.palette = palette
  try { const next = { ...savedPreferences.value, palette }; localStorage.setItem(key, JSON.stringify(next)); savedPreferences.value = next; storageMessage.value = '' } catch { storageMessage.value = '配色仅在当前应用生效，本地保存失败' }
}
export function disposePreferences() { disposed = true; appearanceRevision++; clearAppearanceTimers(); appearancePhase.value = 'idle'; stopNative(); stop(); media.removeEventListener('change', listener); reduceMedia.removeEventListener('change', reduceListener) }
