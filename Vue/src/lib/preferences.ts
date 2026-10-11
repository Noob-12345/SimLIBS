import { computed, reactive, ref, watch } from 'vue'
export type ThemeMode = 'light' | 'dark' | 'system'
export type Palette = 'amber' | 'ocean' | 'violet' | 'forest' | 'rose'
export interface Preferences { mode: ThemeMode; palette: Palette; reducedMotion: boolean; endpoint: string; pythonPath: string; driverPath: string }
const key = 'simlibs-vue-preferences-v1'
const defaults: Preferences = { mode: 'light', palette: 'amber', reducedMotion: false, endpoint: 'http://127.0.0.1:8517', pythonPath: '', driverPath: '' }
export const palettes: { id: Palette; label: string; color: string; dark: string; text: string }[] = [
  { id: 'amber', label: '琥珀', color: '#e5a327', dark: '#efbb58', text: '#94600d' }, { id: 'ocean', label: '海蓝', color: '#73b1e4', dark: '#83bff0', text: '#326a96' }, { id: 'violet', label: '鸢尾', color: '#ac92da', dark: '#bda1ee', text: '#7250a0' }, { id: 'forest', label: '松绿', color: '#80b9a1', dark: '#85c9ac', text: '#386b55' }, { id: 'rose', label: '蔷薇', color: '#da92a0', dark: '#eea6b4', text: '#965367' }
]
export const storageMessage = ref('')
function load(): Preferences { try { const raw = JSON.parse(localStorage.getItem(key) || '{}') as Partial<Preferences>; return { mode: ['light','dark','system'].includes(raw.mode ?? '') ? raw.mode! : 'light', palette: palettes.some(p => p.id === raw.palette) ? raw.palette! : 'amber', reducedMotion: raw.reducedMotion === true, endpoint: typeof raw.endpoint === 'string' ? raw.endpoint : defaults.endpoint, pythonPath: typeof raw.pythonPath === 'string' ? raw.pythonPath : '', driverPath: typeof raw.driverPath === 'string' ? raw.driverPath : '' } } catch { storageMessage.value = '本地偏好无法读取，已采用默认外观'; return { ...defaults } } }
export const savedPreferences = ref(load())
export const preferences = reactive<Preferences>({ ...savedPreferences.value })
const media = window.matchMedia('(prefers-color-scheme: dark)'), systemDark = ref(media.matches)
const listener = () => { systemDark.value = media.matches }; media.addEventListener('change', listener)
export const actualDark = computed(() => preferences.mode === 'dark' || preferences.mode === 'system' && systemDark.value)
export const preferenceDirty = computed(() => JSON.stringify(preferences) !== JSON.stringify(savedPreferences.value))
function apply() {
  const dark = actualDark.value, palette = palettes.find(p => p.id === preferences.palette) ?? palettes[0]!, root = document.documentElement
  root.dataset.theme = dark ? 'dark' : 'light'; root.dataset.reducedMotion = String(preferences.reducedMotion)
  root.style.setProperty('--accent', palette.color); root.style.setProperty('--chart', dark ? palette.dark : palette.text)
  root.style.setProperty('--accent-text', dark ? palette.dark : palette.text)
  root.style.setProperty('--accent-soft', `color-mix(in srgb, ${palette.color} ${dark ? '12%' : '11%'}, var(--panel))`)
}
const stop = watch([preferences, actualDark], apply, { deep: true, immediate: true })
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
export function disposePreferences() { stop(); media.removeEventListener('change', listener) }
