<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { discardPreferences, outputDirectoryError, palettes, preferenceDirty, preferences, savePreferences, storageMessage, type ThemeMode } from '../lib/preferences'
import { connectBackend, service, request } from '../lib/backend'
import { savedPreferences } from '../lib/preferences'
import { outputDirectoryIssue } from '../lib/outputDirectory'
import { isTauri } from '@tauri-apps/api/core'
import { currentTarget, isCurrentTarget, refreshLocalCapabilities, rollbackSettings, settingsRequest, supportsLibrary, targetKey, useLibrarySettings, type ServiceSettings, type SettingsTarget } from '../lib/librarySettings'
const saveError = ref('')
const saving = ref(false)
const librarySettings = useLibrarySettings(), library = librarySettings.state, libraryDirty = librarySettings.dirty
const settingsDirty = computed(() => preferenceDirty.value || libraryDirty.value)
const connectionChanged = computed(() => preferences.pythonPath !== savedPreferences.value.pythonPath || preferences.endpoint !== savedPreferences.value.endpoint || preferences.backendToken !== savedPreferences.value.backendToken)
const libraryEditable = computed(() => service.connected && !service.busy && !saving.value && library.loaded && library.supported && !library.loading && !connectionChanged.value)
const desktopLibraryHost = isTauri()
const canChooseDirectory = computed(() => desktopLibraryHost && libraryEditable.value && !preferences.endpoint.trim() && !savedPreferences.value.endpoint.trim())
const savebar = ref<HTMLElement>()
const showSavebar = computed(() => settingsDirty.value || saving.value)
const storageFeedback = computed(() => ['外观与配置已保存到本地', '已恢复上次保存的偏好'].includes(storageMessage.value) ? '' : storageMessage.value)
async function revealField(event?: Event) {
  const field = event ? event.target : document.activeElement
  if (!(field instanceof HTMLElement) || !field.matches('input,select,textarea,button') || savebar.value?.contains(field)) return
  if (event?.type === 'focusin' && !field.matches(':focus-visible')) return
  await nextTick()
  const bar = savebar.value?.getBoundingClientRect(), box = field.getBoundingClientRect()
  if (!bar || !box.height) return
  const explanation = field.getAttribute('aria-describedby')?.split(' ').map(id => document.getElementById(id)?.getBoundingClientRect().bottom ?? box.bottom) ?? []
  const bottom = Math.max(box.bottom, ...explanation)
  if (bottom > bar.top - 12 && box.top < window.innerHeight) window.scrollBy(0, bottom - bar.top + 12)
}
watch(showSavebar, visible => { if (visible) void revealField() }, { flush: 'post' })
const connectionError = computed(() => { try { if (!preferences.endpoint.trim()) return ''; const url = new URL(preferences.endpoint); return ['http:', 'https:'].includes(url.protocol) ? '' : '服务地址须采用 http 或 https' } catch { return '请输入完整服务地址，如 http://127.0.0.1:8517' } })
const directoryError = computed(() => outputDirectoryIssue(preferences.outputDirectory))
async function save() {
  if (saving.value || library.selecting) return
  saveError.value = connectionError.value || directoryError.value; if (saveError.value) return
  const previous = {...savedPreferences.value}, next = {...preferences}
  const changed = next.pythonPath !== previous.pythonPath || next.endpoint !== previous.endpoint || next.backendToken !== previous.backendToken
  if (changed && libraryDirty.value) { saveError.value = '请先保存或放弃当前谱线库更改，再切换连接配置。'; return }
  const libraryBefore = {...library}, libraryChanged = libraryDirty.value, libraryDraft = library.draft
  let targetSettings: ServiceSettings | undefined, target: SettingsTarget | undefined
  let rollbackPayload: Record<string, string> | undefined
  let settingsWritten = false
  saving.value = true
  try {
    if (changed || !service.connected) await connectBackend(changed, next.pythonPath, next)
    target = currentTarget()
    targetSettings = await settingsRequest<ServiceSettings>(target, '/settings')
    if (!isCurrentTarget(target)) throw new Error('连接已切换，请重试保存')
    if (libraryChanged && (!supportsLibrary(targetSettings) || libraryBefore.owner !== targetKey(target))) throw new Error('当前服务不支持此谱线库草稿，请重新读取设置')
    const updated = await settingsRequest(target, '/settings', {output_dir: next.outputDirectory, driver: next.driverPath, ...(libraryChanged ? {line_database_override: libraryDraft} : {})})
    settingsWritten = true
    rollbackPayload = updated.settings_rollback ? {settings_rollback: updated.settings_rollback} : rollbackSettings(targetSettings)
    await refreshLocalCapabilities(target)
    if (JSON.stringify(preferences) !== JSON.stringify(next)) throw new Error('保存期间设置已变化，请重试')
    if (!savePreferences()) throw new Error('偏好保存失败')
    librarySettings.accept(updated, target)
  } catch (e) {
    const rollbackErrors: string[] = []
    if (settingsWritten && targetSettings && target) {
      try { await settingsRequest(target, '/settings', rollbackPayload!); if (isCurrentTarget(target)) await refreshLocalCapabilities(target) }
      catch (rollback) { rollbackErrors.push(`后台设置恢复失败：${String(rollback)}`) }
    }
    savedPreferences.value = previous
    if (changed) {
      try { await connectBackend(true, previous.pythonPath, previous) }
      catch (rollback) { rollbackErrors.push(`原连接恢复失败：${String(rollback)}`) }
    }
    librarySettings.restore(libraryBefore)
    saveError.value = [String(e), ...rollbackErrors].join('；')
  } finally { saving.value = false }
}
async function detect() { try { await connectBackend(false, savedPreferences.value.pythonPath); const status = await request('/status'); service.status = status; await librarySettings.load(); const config = await request('/settings'); saveError.value = `Python ${status.python} · ${status.engine_label} · 实际任务存储：${config.output_dir}` } catch (e) { saveError.value = String(e) } }
function discard() { saveError.value = ''; discardPreferences(); librarySettings.discard() }
</script>
<template><div class="settings-page" @focusin="revealField" @input="revealField"><section class="panel appearance-panel"><div class="panel-heading"><div><h2>外观设置</h2><p class="hint">更改可预览，保存后保留。</p></div><AppIcon name="palette" :size="22" /></div><div class="settings-row"><div><h3>明暗模式</h3></div><div class="segmented mode-tabs"><button v-for="mode in [{ id: 'light', label: '日间', icon: 'sun' }, { id: 'dark', label: '夜间', icon: 'moon' }, { id: 'system', label: '跟随系统', icon: 'monitor' }]" :key="mode.id" :class="{ selected: preferences.mode === mode.id }" :aria-pressed="preferences.mode === mode.id" @click="preferences.mode = mode.id as ThemeMode"><AppIcon :name="mode.icon" :size="15" />{{ mode.label }}</button></div></div><div class="settings-section-title"><h3>工作台主题</h3></div><div class="theme-cards"><button v-for="palette in palettes" :key="palette.id" :class="['theme-card', { selected: preferences.palette === palette.id }]" :aria-pressed="preferences.palette === palette.id" :aria-label="`${palette.label}主题预览`" @click="preferences.palette = palette.id"><span class="theme-previews"><span v-for="mode in ['light','dark']" :key="mode" :class="['mini-preview', mode]" :style="{ '--preview-accent': mode === 'dark' ? palette.dark : palette.color, '--preview-accent-text': mode === 'dark' ? palette.dark : palette.text }"><span class="mini-sidebar"><i /><i /><i /></span><span class="mini-workspace"><span class="mini-heading" /><span class="mini-chart"><svg viewBox="0 0 100 38" fill="none" aria-hidden="true"><path d="M0 10H100M0 24H100" stroke="currentColor" opacity=".12" /><path d="M0 34h9l3-12 4 12h13l4-29 4 28h11l4-17 4 17h17l4-23 4 23h15" stroke="var(--preview-accent)" stroke-width="1.5" stroke-linejoin="round" /></svg></span><span class="mini-bottom"><i /><i /></span></span></span></span><span class="theme-card-label">{{ palette.label }}<AppIcon v-if="preferences.palette === palette.id" name="check" :size="15" /></span></button></div><div class="settings-row motion-row"><div><h3>减少动态</h3><p class="hint">减少非必要动画，并遵循系统偏好。</p></div><label class="switch"><span class="sr-only">减少动态</span><input v-model="preferences.reducedMotion" type="checkbox" aria-label="减少动态" /><span class="switch-track" /></label></div></section>
  <div class="settings-grid"><section class="panel settings-section"><div class="panel-heading"><h2>连接配置</h2><span class="badge neutral">{{ service.connected ? '已连接' : '未连接' }}</span></div><p class="hint">留空使用桌面自动管理的本机服务；填写地址连接外部服务。</p><label class="field">服务地址<input v-model="preferences.endpoint" type="text" placeholder="留空：自动本机服务" :aria-invalid="!!connectionError" aria-describedby="settings-connection-message" /></label><p v-if="connectionError" id="settings-connection-message" class="error-text">{{ connectionError }}</p><label class="field">外部服务 session token<input v-model="preferences.backendToken" type="password" autocomplete="off" /></label><div class="connection-status"><span>计算服务</span><b>{{ service.label }}</b></div><p class="hint">{{ service.endpoint }}</p><div class="backend-action"><button class="btn" :disabled="saving || service.busy" @click="detect">连接 / 检测已保存服务</button></div></section><section class="panel settings-section"><div class="panel-heading"><h2>运行环境</h2><span class="badge neutral">未检测</span></div><label class="field">Python 可执行文件路径<input v-model="preferences.pythonPath" type="text" placeholder="尚未配置" /></label><label class="field">浏览器驱动路径<input v-model="preferences.driverPath" type="text" placeholder="尚未配置" /></label><div class="backend-action"><button class="btn" :disabled="saving || service.busy" @click="detect">检测运行环境</button><span class="hint">Python 变更在保存时受控重启；运行任务期间拒绝重启。</span></div></section></div>
  <section class="panel settings-section output-settings" aria-labelledby="local-library-heading"><div class="panel-heading"><h2 id="local-library-heading">本地谱线库</h2><span class="badge neutral">{{ library.loading ? '正在读取' : !library.loaded ? '未读取' : !library.supported ? '服务不支持' : service.capabilities?.ready ? `可用 · ${service.capabilities.elements.length} 个元素` : '不可用' }}</span></div><label for="local-library-path" class="field">服务机器上的谱线库目录<input id="local-library-path" v-model="library.draft" type="text" placeholder="留空：使用内置谱线库" :disabled="!libraryEditable || library.selecting" :aria-invalid="!!library.error" aria-describedby="local-library-description local-library-error" /></label><div class="backend-action"><button v-if="desktopLibraryHost" class="btn" :disabled="!canChooseDirectory || library.selecting" @click="librarySettings.chooseDirectory(() => canChooseDirectory)">{{ library.selecting ? '正在选择…' : '选择目录' }}</button><button class="btn" :disabled="!libraryEditable || library.selecting" @click="library.draft = ''">使用内置谱线库</button><button class="btn" :disabled="saving || library.loading || service.busy || !service.connected" @click="librarySettings.load()">重新读取</button></div><p id="local-library-description" class="hint">包含可用元素的 I/II CSV 与 simlibs-atomic-metadata.json；可使用部分元素库。仅影响普通 local 模式。{{ preferences.endpoint.trim() ? '路径属于外部服务机器，不能从本机代选。' : '桌面自动本机服务可选择目录。' }}{{ connectionChanged ? '请先保存连接配置，再修改对应服务的谱线库。' : '' }}</p><p v-if="library.effective" class="hint">当前有效：{{ library.effective }}</p><p v-if="library.defaultPath" class="hint">内置默认：{{ library.defaultPath }}</p><p id="local-library-error" :class="library.error || service.capabilities?.error ? 'error-text' : 'hint'" role="status">{{ library.error || service.capabilities?.error || (library.supported ? '路径随保存生效；已开始的任务保留原库。' : '连接后读取服务支持情况。') }}</p></section>
  <section class="panel settings-section output-settings"><div class="panel-heading"><h2>输出目录</h2></div><label class="field">任务存储与另存为起点<input v-model="preferences.outputDirectory" type="text" aria-label="输出目录" :aria-invalid="!!directoryError" aria-describedby="output-directory-message" /></label><p id="output-directory-message" :class="directoryError || outputDirectoryError ? 'error-text' : 'hint'" role="status">{{ directoryError || outputDirectoryError || '保存后新任务写入此目录，并作为另存为起点；已有任务保留原路径。' }}</p></section>
  <div v-if="saveError || storageFeedback" class="settings-feedback"><p v-if="saveError" class="error-text" role="alert">{{ saveError }}</p><p v-if="storageFeedback" class="settings-message" role="status">{{ storageFeedback }}</p></div>
  <div v-if="showSavebar" ref="savebar" class="settings-savebar" role="region" aria-label="设置保存操作" :aria-busy="saving"><span class="hint" role="status">{{ saving ? '正在保存设置…' : '有未保存更改' }}</span><div><button class="btn" :disabled="saving || library.selecting || !settingsDirty" @click="discard">放弃更改</button><button class="btn primary" :disabled="saving || library.selecting || !settingsDirty || !!connectionError || !!directoryError" @click="save"><AppIcon name="save" :size="15" />{{ saving ? '保存中…' : '保存设置' }}</button></div></div>
</div></template>
