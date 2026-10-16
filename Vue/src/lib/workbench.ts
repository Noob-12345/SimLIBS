import { computed, reactive, ref } from 'vue'
import { defaults, elementDraft, type BatchSample, type DemoTask, type Page, type ScanResult, type Spectrum, type TaskKind } from './model'
import type { RandomRules } from './demo'
import { request, spectrumResult, fromParameters } from './backend'
export const page = ref<Page>('single')
export const single = reactive({ params: defaults(), composition: [elementDraft()], result: null as Spectrum | null })
export const advanced = reactive({ params: {...defaults(),low:'284.5',high:'286',step:'.005',charge:'2',broaden:true}, composition:[elementDraft('Mg')], result:null as Spectrum|null, selfAbsorption:true,instrumentBroadening:true,matrix:true,column:'1e16',pathLength:'.01',teFactor:'1',neFactor:'1',gaussian:'.01',lorentz:'.002',temperature:'10000',responses:{} as Record<string,string> })
export const batch = reactive({ params: defaults(), composition: [elementDraft()], generation: 'fixed' as 'fixed' | 'random' | 'template', count: '24', packageSize: '8', seed: '42', rules: { te: true, teMin: '0.8', teMax: '1.5', ne: true, neMin: '5e16', neMax: '2e17' } as RandomRules, templateText: '', templateName: '', result: null as BatchSample[] | null, jobId: '', manifest: null as any })
export const scan = reactive({ params: defaults(), composition: [elementDraft()], axis: 'te' as ScanResult['axis'], from: '0.6', to: '1.8', count: '12', result: null as ScanResult | null, frame: 0, spectrum: null as Spectrum | null, loading: false, error: '' })
export const tasks = reactive<DemoTask[]>([])
export const activeTask = (kind: TaskKind) => computed(() => tasks.find(t => t.kind === kind && t.status === 'running'))
const timers = new Map<string, ReturnType<typeof setTimeout>>()
const starting = new Set<TaskKind>()
const polling = new Map<string,Promise<void>>()
const failures = new Map<string,number>()
const resultRevision: Record<TaskKind,number> = {single:0,batch:0,scan:0,advanced:0}
let disposed=false
export async function runReal(kind: TaskKind, summary: string, payload: unknown) {
  if (starting.has(kind) || tasks.some(t => t.kind === kind && t.status === 'running')) return
  const snapshot = JSON.parse(JSON.stringify(payload)); starting.add(kind);resultRevision[kind]++
  try { const data = await request(`/simulate/${kind}`, snapshot); const task: DemoTask = reactive({ id: data.job_id, kind, status: 'running', progress: 0, startedAt: Date.now(), summary, detail: '已提交计算引擎' }); tasks.unshift(task); void poll(task) }
  finally { starting.delete(kind) }
}
function update(task: DemoTask, data: any) {
  task.status = data.status === 'queued' ? 'running' : data.status; task.progress = data.progress ?? 0; task.summary = data.summary; task.resumable = data.resumable; task.duration = data.duration; if (data.created_at) task.startedAt = new Date(data.created_at).getTime()
  task.events = (data.events ?? []).map((e: any) => `${e.ts} ${e.message}`); task.detail = data.error || task.events?.[task.events.length - 1] || ''
  if (task.status !== 'running') task.endedAt ??= Date.now()
}
function schedule(task:DemoTask,delay:number) {
  if(disposed)return
  clearTimeout(timers.get(task.id));timers.set(task.id,setTimeout(()=>{timers.delete(task.id);void poll(task)},delay))
}
function poll(task: DemoTask):Promise<void> {
  const existing=polling.get(task.id);if(existing)return existing
  clearTimeout(timers.get(task.id));timers.delete(task.id)
  const promise=(async()=>{
    try {
      update(task,await request(`/jobs/${task.id}`));failures.delete(task.id);task.resultError=''
      if(disposed)return
      if(task.status==='completed') {
        try {await loadResult(task)} catch(e){task.resultError=`计算已完成，结果读取失败：${String(e)}`}
      } else if(task.status==='running')schedule(task,350)
    } catch(e) {
      const count=(failures.get(task.id)??0)+1;failures.set(task.id,count)
      task.resultError=`服务通信失败：${String(e)}；${count<=3?'正在重试':'请重试读取'}，已有结果保留`
      if(count<=3)schedule(task,500*count)
    }
  })().finally(()=>polling.delete(task.id))
  polling.set(task.id,promise);return promise
}
export async function retryTask(task:DemoTask) {failures.delete(task.id);task.resultError='';await poll(task)}
export async function refreshTasks() {
  const data = await request('/jobs'); const kinds: Record<string, TaskKind> = { '单次模拟': 'single', '批量模拟': 'batch', '参数扫描': 'scan', '扫描动画': 'scan', '高级模拟':'advanced' }
  for (const item of data.jobs) { let task = tasks.find(t => t.id === item.job_id); if (!task) { task = reactive({ id: item.job_id, kind: kinds[item.kind] ?? 'single', status: 'running' as const, progress: 0, startedAt: Date.now(), summary: '', detail: '' }); tasks.push(task) }; update(task, item); if (task.status === 'running' && !timers.has(task.id)) void poll(task) }
  tasks.sort((a,b)=>b.startedAt-a.startedAt)
}
async function loadResult(task: DemoTask) {
  const revision=++resultRevision[task.kind]
  const data = await request(`/jobs/${task.id}/result`)
  if(disposed || revision!==resultRevision[task.kind])return
  if (task.kind === 'single' || task.kind==='advanced') { task.result = spectrumResult(data, task.id); (task.kind==='single'?single:advanced).result = task.result }
  if (task.kind === 'batch') { task.result = data.samples.map((s: any) => ({ name: s.name, params: fromParameters(s.parameters), composition: s.composition.map((c: any) => ({ symbol: c.el, pct: c.pct })) })); batch.result = task.result as BatchSample[]; batch.jobId = task.id; batch.manifest = data.manifest }
  if (task.kind === 'scan') { invalidateFrame();scan.spectrum=null;scan.error='';task.result = { axis: data.axis === 'r' ? 'resolution' : data.axis, jobId: task.id, frames: data.frames.map((_: any, i: number) => ({ value: data.manifest.completed_values[i] })) }; scan.result = task.result as ScanResult; scan.frame = 0; await loadFrame(0) }
}
export async function cancelTask(task?: DemoTask) {
  if (!task || task.status !== 'running') return
  try { await request(`/jobs/${task.id}/cancel`, {}); task.detail = '正在取消任务；保留上一成功图谱'; if (!timers.has(task.id)) void poll(task) }
  catch (e) { task.detail = String(e) }
}
export async function resumeTask(task: DemoTask) { const data = await request(`/jobs/${task.id}/resume`, {}); await refreshTasks(); if(tasks.some(t=>t.id===data.job_id))page.value='batch' }
export function disposeTimers() { disposed=true;timers.forEach(clearTimeout); timers.clear(); invalidateFrame() }
export async function openTaskResult(task: DemoTask) { if (task.status !== 'completed') return; await loadResult(task); page.value = task.kind }
let frameRevision = 0
const cache = new Map<string, Spectrum>()
let frameRequest: {key:string;controller:AbortController;promise:Promise<Spectrum>}|undefined
export function invalidateFrame() {frameRevision++;frameRequest?.controller.abort();frameRequest=undefined;scan.loading=false}
export async function loadFrame(index: number):Promise<boolean> {
  const result = scan.result, job = result?.jobId; if (!job || !Number.isInteger(index) || index<0 || index>=result.frames.length) return false
  const revision = ++frameRevision; scan.loading = true; scan.error = ''
  const key=`${job}:${index}`
  if(frameRequest && frameRequest.key!==key){frameRequest.controller.abort();frameRequest=undefined}
  try {
    let spectrum=cache.get(key)
    if(spectrum){cache.delete(key);cache.set(key,spectrum)}
    else {if(!frameRequest){const controller=new AbortController();frameRequest={key,controller,promise:request(`/jobs/${job}/result?frame=${index}`,undefined,true,controller.signal).then(data=>spectrumResult(data,job))}};spectrum=await frameRequest.promise}
    if(revision!==frameRevision || scan.result?.jobId!==job)return false
    cache.set(key,spectrum);while(cache.size>3)cache.delete(cache.keys().next().value!)
    scan.spectrum=spectrum;scan.frame=index;return true
  } catch(e) {if(revision!==frameRevision || scan.result?.jobId!==job)return false;scan.error=String(e);return false}
  finally {if(revision===frameRevision){scan.loading=false;frameRequest=undefined}}
}
