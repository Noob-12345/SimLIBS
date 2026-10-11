<script setup lang="ts">
import { computed, onUnmounted } from 'vue'
import AppIcon from './components/AppIcon.vue'
import ThemeMenu from './components/ThemeMenu.vue'
import SinglePage from './pages/SinglePage.vue'
import BatchPage from './pages/BatchPage.vue'
import ScanPage from './pages/ScanPage.vue'
import JobsPage from './pages/JobsPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import { disposeTimers, page, tasks } from './lib/workbench'
import { disposePreferences, preferences, setPalette, setThemeMode } from './lib/preferences'
import type { Page } from './lib/model'
import './styles.css'
const pages: { id: Page; label: string; subtitle: string }[] = [
  { id: 'single', label: '单次模拟', subtitle: '' },
  { id: 'batch', label: '批量模拟', subtitle: '设置生成方式，查看示意样本。' },
  { id: 'scan', label: '参数扫描', subtitle: '设置扫描范围，查看示意光谱。' },
  { id: 'jobs', label: '任务记录', subtitle: '查看本次应用会话的演示任务。' },
  { id: 'settings', label: '设置', subtitle: '调整外观与连接配置。' }
]
const current = computed(() => pages.find(p => p.id === page.value)!)
const runningCount = computed(() => tasks.filter(t => t.status === 'running').length)
onUnmounted(() => { disposeTimers(); disposePreferences() })
</script>
<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M3 26h6l3-12 4 17 5-26 4 21h8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" /></svg><div><strong>SimLIBS</strong><small>光谱工作台</small></div></div>
      <div class="sidebar-caption">SCNU</div>
      <nav aria-label="主导航"><template v-for="(item, index) in pages" :key="item.id"><div v-if="index === 3" class="sidebar-caption nav-group-caption">软件日志</div><button :class="['nav-item', { active: page === item.id }]" :aria-label="item.label" :aria-current="page === item.id ? 'page' : undefined" :title="item.label" @click="page = item.id"><AppIcon :name="item.id" class="nav-symbol" :size="19" /><span class="nav-text">{{ item.label }}</span><AppIcon v-if="page === item.id" name="chevron" class="nav-arrow" :size="14" /></button></template></nav>
      <div class="sidebar-bottom"><h4>运行状态</h4><p>计算引擎未接入</p><small>SimLIBS · SCNU</small></div>
    </aside>
    <main class="main-shell">
      <header class="topbar"><span>工作空间 <b>/</b> {{ current.label }}</span><div><span v-if="runningCount" class="badge neutral">{{ runningCount }} 项演示任务进行中</span><ThemeMenu :mode="preferences.mode" :palette="preferences.palette" @select="setThemeMode" @palette="setPalette" /></div></header>
      <div class="workspace"><div class="page-heading"><div><h1>{{ current.label }}</h1><p v-if="current.subtitle">{{ current.subtitle }}</p></div></div>
        <Transition name="page" mode="out-in"><SinglePage v-if="page === 'single'" /><BatchPage v-else-if="page === 'batch'" /><ScanPage v-else-if="page === 'scan'" /><JobsPage v-else-if="page === 'jobs'" /><SettingsPage v-else /></Transition>
        <footer class="workspace-footer"><span>SimLIBS 光谱工作台</span></footer>
      </div>
    </main>
  </div>
</template>
