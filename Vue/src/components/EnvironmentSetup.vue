<script setup lang="ts">
import { computed, ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { openUrl } from '@tauri-apps/plugin-opener'
import AppIcon from './AppIcon.vue'
import { envSetup, retryBootstrap, useManualInterpreter } from '../lib/environment'
const visible = computed(() => isTauri() && envSetup.active)
const phaseLabels: Record<string, string> = {
  conda: '检测 / 使用 conda', winget: '获取 Python（winget）', venv: '创建托管虚拟环境',
  pip: '安装后端依赖', verify: '验证依赖导入', done: '环境就绪', failed: '配置失败', 'no-toolchain': '需要手动安装 Python'
}
const badge = computed(() => envSetup.running ? '配置中' : envSetup.failed ? '失败' : envSetup.noToolchain ? '需手动配置' : '进行中')
const selecting = ref(false), downloadError = ref('')
async function choosePython() {
  if (selecting.value) return
  selecting.value = true
  try {
    const path = await open({ multiple: false, directory: false, title: '选择 Python 解释器', filters: [{ name: 'Python 解释器', extensions: ['exe'] }] })
    if (typeof path === 'string') useManualInterpreter(path)
  } finally { selecting.value = false }
}
async function openDownload() {
  downloadError.value = ''
  try { await openUrl('https://www.python.org/downloads/') }
  catch { downloadError.value = '无法打开系统浏览器；请手动访问 python.org/downloads 安装 Python 3.11 后重试。' }
}
</script>
<template>
  <section v-if="visible" class="panel activity-panel environment-setup" role="region" aria-label="Python 环境配置">
    <div class="panel-heading"><h2>Python 环境配置</h2><span :class="['badge', envSetup.failed ? 'task-failed' : 'neutral']">{{ badge }}</span></div>
    <p class="hint">首次使用需要 Python 3.11 与后端依赖。程序可自动创建独立托管环境：优先使用本机 conda，其次尝试 winget 安装 Python；不会修改你显式指定的解释器或全局环境。</p>
    <ol class="env-steps">
      <li v-for="(event, index) in envSetup.events" :key="index" :data-state="event.state"><i aria-hidden="true" /><div><b>{{ phaseLabels[event.phase] || event.phase }}</b><span>{{ event.detail }}</span></div></li>
    </ol>
    <p v-if="envSetup.finalError" class="error-text" role="alert">{{ envSetup.finalError }}</p>
    <div v-if="envSetup.noToolchain || envSetup.failed" class="env-manual">
      <p class="hint">手动方案：从 python.org 安装 Python 3.11，然后在下面选择它的 python.exe。程序只用它创建独立托管环境并安装依赖，不改动所选解释器本身。</p>
      <div class="env-actions">
        <button type="button" class="btn" @click="openDownload">打开 Python 下载页<AppIcon name="arrow" :size="14" /></button>
        <button type="button" class="btn primary" :disabled="selecting || envSetup.running" @click="choosePython">{{ selecting ? '正在选择…' : '选择已有解释器' }}</button>
        <button type="button" class="btn" :disabled="envSetup.running" @click="retryBootstrap">重试自动配置</button>
      </div>
      <p v-if="downloadError" class="error-text" role="alert">{{ downloadError }}</p>
    </div>
    <p v-else-if="envSetup.running" class="hint" role="status">正在自动配置环境；完成后将自动重新连接。</p>
  </section>
</template>
<style scoped>
.environment-setup{min-width:0}
.env-steps{list-style:none;padding:0;margin:10px 0;display:flex;flex-direction:column;gap:8px}
.env-steps>li{display:flex;gap:9px;align-items:flex-start;font-size:12px;line-height:1.55;min-width:0}
.env-steps i{width:8px;height:8px;flex:none;border-radius:50%;margin-top:5px;background:var(--faint);border:1px solid color-mix(in srgb,var(--faint) 60%,var(--text))}
.env-steps [data-state=running] i{background:var(--accent);border-color:var(--accent);animation:env-pulse 1.2s ease-in-out infinite}
.env-steps [data-state=done] i{background:var(--good);border-color:var(--good)}
.env-steps [data-state=failed] i{background:var(--bad);border-color:var(--bad)}
.env-steps [data-state=waiting] i{background:var(--accent-text);border-color:var(--accent-text)}
.env-steps b{display:block;font-weight:600;color:var(--text)}
.env-steps span{display:block;color:var(--muted);overflow-wrap:anywhere}
@keyframes env-pulse{50%{opacity:.35}}
.env-manual{border-top:1px solid var(--border);padding-top:10px;display:flex;flex-direction:column;gap:8px}
.env-actions{display:flex;gap:8px;flex-wrap:wrap}
:root[data-reduced-motion=true] .env-steps [data-state=running] i{animation:none}
</style>
