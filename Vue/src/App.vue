<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { openUrl } from '@tauri-apps/plugin-opener'
import AppIcon from './components/AppIcon.vue'
import ThemeMenu from './components/ThemeMenu.vue'
import SinglePage from './pages/SinglePage.vue'
import BatchPage from './pages/BatchPage.vue'
import ScanPage from './pages/ScanPage.vue'
import JobsPage from './pages/JobsPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import AdvancedPage from './pages/AdvancedPage.vue'
import { disposeTimers, page, tasks, refreshTasks } from './lib/workbench'
import { appearancePhase, disposePreferences, nativeThemeError, preferences, setPalette, setThemeMode } from './lib/preferences'
import { connectBackend, service } from './lib/backend'
import { savedPreferences } from './lib/preferences'
import type { Page } from './lib/model'
import './styles.css'
const pages: { id: Page; label: string; subtitle: string }[] = [
  { id: 'single', label: '单次模拟', subtitle: '' },
  { id: 'batch', label: '批量模拟', subtitle: '' },
  { id: 'scan', label: '参数扫描', subtitle: '' },
  { id: 'advanced', label: '高级模拟', subtitle: '' },
  { id: 'jobs', label: '任务记录', subtitle: '' },
  { id: 'settings', label: '设置', subtitle: '' }
]
const current = computed(() => pages.find(p => p.id === page.value)!)
const runningCount = computed(() => tasks.filter(t => t.status === 'running').length)
const repositoryUrl = 'https://github.com/Noob-12345/SimLIBS'
const repositoryOpening = ref(false), repositoryError = ref('')
async function openRepository() {
  if (repositoryOpening.value) return
  repositoryOpening.value = true; repositoryError.value = ''
  try { await openUrl(repositoryUrl) }
  catch { repositoryError.value = '无法打开系统浏览器，请重试' }
  finally { repositoryOpening.value = false }
}
onMounted(async () => { try { await connectBackend(false, savedPreferences.value.pythonPath); await refreshTasks() } catch { /* concrete connection error is visible below */ } })
onUnmounted(() => { disposeTimers(); disposePreferences() })
</script>
<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M3 26h6l3-12 4 17 5-26 4 21h8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" /></svg><div><strong>SimLIBS</strong><small>光谱工作台</small></div></div>
      <div class="sidebar-caption">SCNU</div>
      <nav aria-label="主导航"><template v-for="item in pages" :key="item.id"><div v-if="item.id === 'jobs'" class="sidebar-caption nav-group-caption">软件日志</div><button :class="['nav-item', { active: page === item.id }]" :aria-label="item.label" :aria-current="page === item.id ? 'page' : undefined" :title="item.label" @click="page = item.id"><AppIcon :name="item.id" class="nav-symbol" :size="19" /><span class="nav-text">{{ item.label }}</span><AppIcon v-if="page === item.id" name="chevron" class="nav-arrow" :size="14" /></button></template></nav>
      <div class="sidebar-bottom"><h4>运行状态</h4><p>{{ service.label }}</p><small>SimLIBS · SCNU</small></div>
    </aside>
    <main class="main-shell">
      <header class="topbar"><span>工作空间 <b>/</b> {{ current.label }}</span><div><span v-if="runningCount" class="badge neutral">{{ runningCount }} 项任务进行中</span><div class="topbar-actions"><ThemeMenu :mode="preferences.mode" :palette="preferences.palette" @select="setThemeMode" @palette="setPalette" /><div class="repository-control"><button type="button" class="icon-btn theme-trigger" aria-label="打开 GitHub 项目" title="GitHub 项目" :disabled="repositoryOpening" @click="openRepository"><AppIcon name="github" :size="18" /></button><p v-if="repositoryError" class="repository-feedback" role="status">{{ repositoryError }}</p></div></div></div></header>
      <div class="workspace"><p v-if="service.error" class="error-text" role="alert">{{ service.error }}</p><p v-if="nativeThemeError" class="error-text" role="alert">{{ nativeThemeError }}</p><div class="page-heading"><div><h1>{{ current.label }}</h1><p v-if="current.subtitle">{{ current.subtitle }}</p></div></div>
        <Transition name="page" mode="out-in"><SinglePage v-if="page === 'single'" /><BatchPage v-else-if="page === 'batch'" /><ScanPage v-else-if="page === 'scan'" /><AdvancedPage v-else-if="page === 'advanced'" /><JobsPage v-else-if="page === 'jobs'" /><SettingsPage v-else /></Transition>
      </div>
    </main>
  </div>
  <Teleport to="body"><div :class="['theme-veil', { 'is-blurring': appearancePhase === 'blurring' }]" :data-phase="appearancePhase" aria-hidden="true" /></Teleport>
</template>
