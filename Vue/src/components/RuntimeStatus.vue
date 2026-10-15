<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { checkRuntime, disposeRuntime, recheckRuntime, runtime, safeRuntimeText, service, type RuntimeState } from '../lib/backend'
import { page, tasks } from '../lib/workbench'
import { savedPreferences } from '../lib/preferences'

const dialog = ref<HTMLDialogElement>(), trigger = ref<HTMLButtonElement>()
const opened = ref(false)
const stateText: Record<RuntimeState, string> = { ok: '正常', warning: '部分可用', error: '异常', unknown: '未检测', checking: '检查中' }
const busy = computed(() => service.busy || runtime.checking)
const running = computed(() => tasks.some(task => task.status === 'running'))
const connection = computed<RuntimeState>(() => service.busy ? 'checking' : service.connected ? runtime.heartbeat : service.error ? 'error' : 'unknown')
function interpreterPath(path: string) { const value = path.replace(/\\/g, '/'); return /^[a-z]:/i.test(value) ? value.toLowerCase() : value }
const workerVerified = computed(() => { const p = runtime.report?.interpreter; return !!p?.worker_executable && interpreterPath(p.executable) === interpreterPath(p.worker_executable) })
const dependencies = computed<RuntimeState>(() => {
  if (runtime.report) return runtime.report.dependencies.state === 'ok' && !workerVerified.value ? 'warning' : runtime.report.dependencies.state
  return busy.value ? 'checking' : /ModuleNotFoundError|ImportError|DLL/.test(service.error) ? 'error' : 'unknown'
})
const local = computed(() => service.connected ? service.status.local as { ready?: boolean; elements?: string[]; issues?: Record<string, unknown>; error?: string; root?: string; csv_count?: number } | undefined : undefined)
const library = computed<RuntimeState>(() => {
  if (!local.value) return service.busy ? 'checking' : 'unknown'
  return local.value.ready && local.value.elements?.length ? local.value.error || Object.keys(local.value.issues ?? {}).length ? 'warning' : 'ok' : 'error'
})
const lights = computed(() => [{ id: 'connection', label: '后端连接', state: connection.value }, { id: 'dependencies', label: 'Python 依赖', state: dependencies.value }, { id: 'library', label: '本地谱库', state: library.value }])
const overall = computed(() => (['error', 'checking', 'warning', 'unknown', 'ok'] as RuntimeState[]).find(state => lights.value.some(light => light.state === state))!)
const accessibleLabel = computed(() => '运行状态，打开诊断详情：' + lights.value.map(light => light.label + stateText[light.state]).join('，'))
const checkedTime = (time: number) => time ? new Date(time).toLocaleString('zh-CN') : '尚未检查'
const selectedPython = computed(() => runtime.report?.interpreter.executable || service.python || savedPreferences.value.pythonPath || '由桌面启动器选择；启动失败时见下方证据')
const connectionGuidance = computed(() => {
  if (/解释器不存在|Python 启动失败/.test(service.error)) return '进入设置，填写已有环境的 Python 可执行文件完整路径并保存。'
  if (/缺少 backend|FileNotFoundError|启动模块缺失/.test(service.error)) return '请恢复与 EXE 同目录的完整 backend 文件夹，再重新检查。'
  if (/ModuleNotFoundError|ImportError|DLL/.test(service.error)) return '请在错误中指定的 Python 环境手动修复所列分发包或二进制依赖，再重新检查。'
  return '外部服务请核对服务是否运行，以及已保存的地址与凭证；自动本机服务可重新检查并重试启动。'
})
async function show() { opened.value = true; await nextTick(); if (!dialog.value?.open) dialog.value?.showModal(); if (service.connected && !runtime.checkedAt) void checkRuntime(true) }
function close() { dialog.value?.close() }
function closed() { opened.value = false; trigger.value?.focus({ preventScroll: true }) }
function settings() { close(); page.value = 'settings' }
function trapTab(event: KeyboardEvent) {
  if (event.key !== 'Tab') return
  const buttons = Array.from(dialog.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []).filter(button => button.getClientRects().length)
  const first = buttons[0], last = buttons[buttons.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
let timer: ReturnType<typeof setTimeout> | undefined, disposed = false
function schedule() {
  timer = setTimeout(async () => {
    try { if (service.connected && !document.hidden) await checkRuntime(false) }
    finally { if (!disposed) schedule() }
  }, 15000)
}
function focusCheck() { if (service.connected) void checkRuntime(false) }
watch(() => service.connected, connected => { if (connected) void checkRuntime(true) })
onMounted(() => { if (service.connected) void checkRuntime(true); schedule(); window.addEventListener('focus', focusCheck) })
onUnmounted(() => { disposed = true; clearTimeout(timer); window.removeEventListener('focus', focusCheck); dialog.value?.close(); disposeRuntime() })
</script>

<template>
  <div class="runtime-status">
    <button ref="trigger" type="button" class="runtime-trigger" :aria-label="accessibleLabel" aria-haspopup="dialog" :aria-expanded="opened" @click="show">
      <span class="runtime-full runtime-heading">运行状态 <AppIcon name="chevron" :size="12" /></span>
      <span v-for="light in lights" :key="light.id" class="runtime-full runtime-light" :data-runtime="light.id" :data-state="light.state"><i aria-hidden="true" /><span>{{ light.label }}</span><b>{{ stateText[light.state] }}</b></span>
      <span class="runtime-compact" :data-state="overall"><AppIcon name="monitor" :size="21" /><i aria-hidden="true" /><span class="sr-only">{{ accessibleLabel }}</span></span>
    </button>
    <Teleport to="body">
      <dialog ref="dialog" class="runtime-dialog" aria-labelledby="runtime-title" aria-describedby="runtime-scope" @close="closed" @keydown="trapTab">
        <header class="runtime-dialog-heading"><h2 id="runtime-title">运行诊断</h2><button class="icon-btn" type="button" aria-label="关闭运行诊断" autofocus @click="close"><AppIcon name="close" :size="18" /></button></header>
        <div class="runtime-details">
          <p id="runtime-scope" class="hint">只读检查服务、依赖导入与本地资源。导入通过不代表模拟正确性；在线条件单独列为未检测。</p>
          <p class="runtime-time" role="status" aria-live="polite">连接检查：{{ checkedTime(runtime.pingAt) }}<br />依赖检查：{{ checkedTime(runtime.checkedAt) }}{{ busy ? ' · 检查中' : '' }}</p>
          <section class="runtime-detail"><h3 :data-state="connection"><i aria-hidden="true" />后端连接 · {{ stateText[connection] }}</h3><p>{{ service.connected ? '当前服务已响应鉴权存活检查。' : safeRuntimeText(service.error) || '尚未取得服务连接证据。' }}</p><p v-if="!service.connected" class="hint">{{ connectionGuidance }}</p><p class="hint">所选 / 实际服务 Python：<span class="runtime-path">{{ selectedPython }}</span></p></section>
          <section class="runtime-detail"><h3 :data-state="dependencies"><i aria-hidden="true" />Python 依赖 · {{ stateText[dependencies] }}</h3>
            <template v-if="runtime.report"><p class="hint">服务解释器 {{ runtime.report.interpreter.version }}；任务解释器：<span class="runtime-path">{{ runtime.report.interpreter.worker_executable || '未提供' }}</span></p><p v-if="!workerVerified" class="runtime-warning">任务解释器与服务解释器不同或未提供。本次只验证服务解释器导入，未验证任务解释器依赖。</p>
              <ul class="runtime-imports"><li v-for="check in runtime.report.dependencies.checks" :key="check.module"><span :data-state="check.state"><i aria-hidden="true" /><b>{{ check.module }} · {{ stateText[check.state] }}</b></span><p>{{ check.summary }}</p><small>影响：{{ check.affected }}</small><p v-if="check.state === 'error'" class="runtime-repair">在上述服务 Python 环境中手动检查 / 安装分发包 <b>{{ check.distribution }}</b>（导入名 {{ check.module }}）；若任务解释器不同，也需分别检查。</p></li></ul><p class="hint">{{ runtime.report.dependencies.summary }}</p>
            </template><p v-else>{{ runtime.note || (busy ? '正在读取实际服务解释器的导入证据…' : '未取得依赖导入证据；HTTP 连接成功不表示依赖齐全。') }}</p>
            <p class="hint">手动修复后：存活服务请在任务结束后完全退出并重新打开，或在设置中更换解释器并保存后受控重启，再重新检查。仅重新检查不会重启存活服务。</p>
          </section>
          <section class="runtime-detail"><h3 :data-state="library"><i aria-hidden="true" />本地谱库 · {{ stateText[library] }}</h3><template v-if="local"><p>{{ local.elements?.length || 0 }} 个可用元素 · {{ local.csv_count ?? '未知' }} 个 CSV</p><p class="runtime-path hint">{{ local.root }}</p><p v-if="local.error">{{ safeRuntimeText(local.error) }}</p><ul v-if="local.issues && Object.keys(local.issues).length" class="runtime-issues"><li v-for="(issue, symbol) in local.issues" :key="symbol">{{ symbol }}：{{ safeRuntimeText(Array.isArray(issue) ? issue.join('；') : issue) }}</li></ul><p class="hint">{{ library === 'ok' ? '仅验证现有谱线与静态元数据；可用元素 / 离子以任务预检为准。' : '影响本地模式：请恢复完整 backend/Linedatabase 谱线与静态元数据，再重新检查。' }}</p></template><p v-else>尚未取得本地资源证据；连接恢复后重新检查。</p></section>
          <section class="runtime-detail"><h3 data-state="unknown"><i aria-hidden="true" />在线条件 · 未检测</h3><p>{{ runtime.report?.online.summary || '未访问 NIST、未启动 Chrome、未验证驱动兼容性；本地模式无需这些在线条件。' }}</p><p class="hint">{{ runtime.report?.online.guidance || '在线模式需要可用网络与匹配的浏览器驱动，可在设置中配置；本次不会下载或安装。' }}</p></section>
        </div>
        <footer class="runtime-actions"><p class="hint">{{ running ? '任务运行中：可只读重查；请待任务结束再更换 Python。' : '重新检查保持当前任务与设置；启动失败时可重试连接本机服务。' }}</p><div><button type="button" class="btn" :disabled="busy" @click="recheckRuntime">{{ busy ? '检查中…' : '重新检查' }}</button><button type="button" class="btn primary" @click="settings">前往设置<AppIcon name="arrow" :size="14" /></button></div></footer>
      </dialog>
    </Teleport>
  </div>
</template>

<style scoped>
:global(.sidebar){min-height:0}
:global(.sidebar>nav){min-height:0;overflow-y:auto;overflow-x:hidden;flex-shrink:1}
.runtime-status,.runtime-dialog{--runtime-warning:#94600d}
:global(:root[data-theme=dark] .runtime-status),:global(:root[data-theme=dark] .runtime-dialog){--runtime-warning:#efbe66}
.runtime-status{margin-top:auto;padding-top:14px;flex:none;min-width:0}
.runtime-trigger{width:100%;padding:9px 10px;border:1px solid var(--border);border-radius:8px;background:var(--sidebar-hover);color:var(--sidebar-muted);text-align:left}
.runtime-trigger:hover{background:var(--sidebar-active)}
.runtime-heading{display:flex;align-items:center;justify-content:space-between;color:var(--text);font-size:12px;font-weight:600;margin-bottom:5px}
.runtime-light{display:flex;align-items:center;gap:6px;font-size:11px;line-height:22px}
.runtime-light b{margin-left:auto;font-size:10px;font-weight:500;white-space:nowrap}
[data-state]{--runtime-color:var(--faint)}
[data-state=ok]{--runtime-color:var(--good)}
[data-state=warning],[data-state=checking]{--runtime-color:var(--runtime-warning)}
[data-state=error]{--runtime-color:var(--bad)}
[data-state]>i{display:inline-block;width:7px;height:7px;flex:none;border-radius:50%;background:var(--runtime-color);border:1px solid color-mix(in srgb,var(--runtime-color) 65%,var(--text))}
.runtime-compact{display:none;position:relative;justify-content:center}
.runtime-compact>i{position:absolute;right:-3px;bottom:-3px;width:8px;height:8px}
.runtime-dialog{width:min(650px,calc(100vw - 32px));max-height:calc(100dvh - 32px);padding:0;border:1px solid var(--border);border-radius:13px;background:var(--panel);color:var(--text);box-shadow:0 12px 60px #0004}
.runtime-dialog[open]{display:flex;flex-direction:column}
.runtime-dialog::backdrop{background:#0b111966}
.runtime-dialog-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid var(--border);flex:none}
.runtime-dialog-heading h2{font-size:16px}
.runtime-details{padding:16px 18px;overflow-y:auto;min-height:0;overscroll-behavior:contain}
.runtime-time{font-size:11px;color:var(--muted);margin:10px 0}
.runtime-detail{padding:14px 0;border-top:1px solid var(--border);overflow-wrap:anywhere}
.runtime-detail h3{display:flex;align-items:center;gap:7px;margin-bottom:7px;font-size:13px}
.runtime-detail p+p{margin-top:7px}
.runtime-path{overflow-wrap:anywhere}
.runtime-warning,.runtime-repair{color:var(--runtime-warning);font-size:12px}
.runtime-imports{list-style:none;padding:0;margin:12px 0}
.runtime-imports li{padding:8px 10px;margin:5px 0;border:1px solid var(--border);border-radius:7px;background:var(--panel-soft)}
.runtime-imports li>span{display:flex;align-items:center;gap:7px;font-size:12px}
.runtime-imports li p,.runtime-imports li small{font-size:11px;margin-top:4px}
.runtime-imports li small{color:var(--muted)}
.runtime-issues{padding-left:18px;font-size:12px}
.runtime-actions{padding:12px 18px;border-top:1px solid var(--border);background:var(--panel);flex:none}
.runtime-actions>div{display:flex;gap:8px;justify-content:flex-end;margin-top:9px;flex-wrap:wrap}
@media(max-width:900px){.runtime-trigger{padding:10px 7px}.runtime-full{display:none}.runtime-compact{display:flex}}
@media(max-height:700px){.runtime-heading{margin-bottom:2px}.runtime-light{line-height:19px}.runtime-status{padding-top:8px}}
</style>
