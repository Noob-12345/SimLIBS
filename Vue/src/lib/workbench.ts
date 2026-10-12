import { computed, reactive, ref } from 'vue'
import { defaults, elementDraft, type BatchSample, type DemoTask, type Page, type ScanResult, type Spectrum, type TaskKind } from './model'
import { generateSpectrum, type RandomRules } from './demo'
export const page = ref<Page>('single')
export const single = reactive({ params: defaults(), composition: [elementDraft()], result: null as Spectrum | null })
export const batch = reactive({ params: defaults(), composition: [elementDraft()], generation: 'fixed' as 'fixed' | 'random' | 'template', count: '24', packageSize: '8', seed: '42', rules: { te: true, teMin: '0.8', teMax: '1.5', ne: true, neMin: '5e16', neMax: '2e17' } as RandomRules, templateText: '', templateName: '', result: null as BatchSample[] | null })
export const scan = reactive({ params: defaults(), composition: [elementDraft()], axis: 'te' as ScanResult['axis'], from: '0.6', to: '1.8', count: '12', result: null as ScanResult | null, frame: 0 })
export const tasks = reactive<DemoTask[]>([])
export const activeTask = (kind: TaskKind) => computed(() => tasks.find(t => t.kind === kind && t.status === 'running'))
const timers = new Map<string, ReturnType<typeof setInterval>>()
let sequence = 0
export function runDemo(kind: TaskKind, summary: string, complete: () => DemoTask['result']) {
  if (tasks.some(t => t.kind === kind && t.status === 'running')) return
  const task: DemoTask = reactive({ id: `demo-${Date.now().toString(36)}-${++sequence}`, kind, status: 'running', progress: 0, startedAt: Date.now(), summary, detail: '界面演示计时；未调用任何真实计算引擎。' })
  tasks.unshift(task)
  const duration = kind === 'single' ? 2100 : kind === 'batch' ? 3200 : 2600
  const timer = setInterval(() => {
    task.progress = Math.min(99, Math.floor((Date.now() - task.startedAt) / duration * 100))
    if (Date.now() - task.startedAt < duration) return
    clearInterval(timer); timers.delete(task.id)
    try {
      task.result = complete()
      if (kind === 'single') single.result = task.result as Spectrum
      if (kind === 'batch') batch.result = task.result as BatchSample[]
      if (kind === 'scan') { scan.result = task.result as ScanResult; scan.frame = 0 }
      task.status = 'completed'; task.progress = 100; task.detail = ''
    } catch (e) { task.status = 'failed'; task.detail = e instanceof Error ? e.message : '演示生成失败' }
    task.endedAt = Date.now()
  }, 120)
  timers.set(task.id, timer)
}
export function cancelTask(task?: DemoTask) {
  if (!task || task.status !== 'running') return
  clearInterval(timers.get(task.id)); timers.delete(task.id)
  task.status = 'cancelled'; task.endedAt = Date.now(); task.detail = '界面演示已取消；已完成的上一份示意结果被保留。'
}
export function disposeTimers() { tasks.filter(t => t.status === 'running').forEach(cancelTask); timers.forEach(clearInterval); timers.clear() }
export const initialSpectrum = generateSpectrum({ te: 1, ne: 1e17, resolution: 1000, low: 200, high: 500, step: .05, charge: 2, mode: 'local', flux: 'photon', broaden: false, gaussian: 0, lorentz: 0, temperature: 0, convention: 'physics', center: null, threshold: 0, resample: false, resampleStep: null, headless: false }, [{ symbol: 'Fe', pct: 100 }])
export function openTaskResult(task: DemoTask) {
  if (!task.result || task.status !== 'completed') return
  if (task.kind === 'single') single.result = task.result as Spectrum
  if (task.kind === 'batch') batch.result = task.result as BatchSample[]
  if (task.kind === 'scan') { scan.result = task.result as ScanResult; scan.frame = 0 }
  page.value = task.kind
}
