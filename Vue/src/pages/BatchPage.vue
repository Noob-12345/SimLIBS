<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ParameterEditor from '../components/ParameterEditor.vue'
import CompositionEditor from '../components/CompositionEditor.vue'
import TaskActivity from '../components/TaskActivity.vue'
import SpectrumChart from '../components/SpectrumChart.vue'
import WorkbenchLayout from '../components/WorkbenchLayout.vue'
import { parseCsv } from '../lib/demo'
import { apiParams, request, spectrumResult, download } from '../lib/backend'
const templateCsv = 'name,Fe_at%,Al_at%,Te[eV],Ne[cm^-3],R\nFe,100,0,1,1e17,1000\nFe-Al,70,30,1.2,2e17,2000\n'
import { desktopHost, openCsvTemplate, readBrowserCsv, useFileSave, type OpenResult } from '../lib/fileAccess'
import { errorOf, format, numeric, validateComposition, validateParams } from '../lib/model'
import { activeTask, batch, runReal } from '../lib/workbench'
import { batchIssues, issueAttrs, type Issues } from '../lib/issues'
const running = activeTask('batch'), selected = ref(0), tablePage = ref(0), submitError = ref(''), fileError = ref(''), reading = ref(false), fileInput = ref<HTMLInputElement>()
const { pending: saving, feedback: saveFeedback, failed: saveFailed, run: saveOutput } = useFileSave()
const compositionError = ref('')
const issues = computed<Issues>(() => ({ ...batchIssues(batch.generation, batch.count, batch.packageSize, batch.seed, batch.rules, batch.templateText), ...(fileError.value ? { template: fileError.value } : {}) }))
const attrs = (key: string) => issueAttrs(issues.value[key], 'batch-draft-error')
let uploadSequence = 0
const header = computed(() => { try { return parseCsv(batch.templateText)[0] ?? [] } catch { return [] } })
const isTemplate = computed(() => batch.generation === 'template'), isRandom = computed(() => batch.generation === 'random')
const csvHas = (name: string) => isTemplate.value && header.value.includes(name)
const templateInfo = ref<{ rows: number; elements: number; error: string } | null>(null)
const validating=ref(false)
let validationController:AbortController|undefined
function prepare() {
  const params = validateParams(batch.params, { ...(isRandom.value && batch.rules.te ? {te: numeric(batch.rules.teMin, 'Te 下界', .01, 100)} : csvHas('Te[eV]') ? {te: 1} : {}), ...(isRandom.value && batch.rules.ne ? {ne: numeric(batch.rules.neMin, 'Ne 下界', 1e10, 1e23)} : csvHas('Ne[cm^-3]') ? {ne: 1e17} : {}), ...(csvHas('R') ? {resolution: 1000} : {}) })
  const payload: any = { params: apiParams(params), batch_size: numeric(batch.packageSize, '每包数', 1, 5000, true), seed: isRandom.value ? numeric(batch.seed, '种子', 0, 4294967295, true) : 0 }
  if (isTemplate.value) { if (reading.value || !batch.templateText) throw new Error('请选择 CSV 模板并等待读取'); return {...payload, template_csv: batch.templateText, repeats: 1} }
  payload.n_samples = numeric(batch.count, '样本数', 1, 5000, true)
  if (compositionError.value) throw new Error(compositionError.value)
  if (!isRandom.value) validateComposition(batch.composition)
  const concentrations = batch.composition.map(e => { const enabled = isRandom.value && e.random; const min = enabled ? numeric(e.min, `${e.symbol} 下界`, 0, 100) : 0; const max = enabled ? numeric(e.max, `${e.symbol} 上界`, 0, 100) : 0; if (min > max) throw new Error('浓度下界不能大于上界'); return { el: e.symbol, enabled, fixed: enabled ? 0 : numeric(e.pct, `${e.symbol} 固定浓度`, 0, 100), min, max } })
  payload.generation = { kind: batch.generation, te: {enabled: isRandom.value && batch.rules.te, min: isRandom.value && batch.rules.te ? numeric(batch.rules.teMin, 'Te 下界', .01, 100) : params.te, max: isRandom.value && batch.rules.te ? numeric(batch.rules.teMax, 'Te 上界', .01, 100) : params.te},
    ne: {enabled: isRandom.value && batch.rules.ne, min: isRandom.value && batch.rules.ne ? numeric(batch.rules.neMin, 'Ne 下界', 1e10, 1e23) : params.ne, max: isRandom.value && batch.rules.ne ? numeric(batch.rules.neMax, 'Ne 上界', 1e10, 1e23) : params.ne}, concentrations }
  return payload
}
const inputError = computed(() => errorOf(prepare) || Object.values(issues.value)[0] || (isTemplate.value ? validating.value ? '正在校验当前模板…' : templateInfo.value?.error ?? '' : ''))
watch(inputError, value => { if (!value) submitError.value = '' })
let validationRevision = 0
watch(() => JSON.stringify([batch.templateText, batch.params, batch.generation,batch.packageSize]), async () => {
  const revision = ++validationRevision
  validationController?.abort();templateInfo.value=null;validating.value=false
  if (!isTemplate.value || !batch.templateText) { templateInfo.value = null; return }
  validationController=new AbortController();validating.value=true
  try { const data = await request('/templates/validate', prepare(),true,validationController.signal); if (revision === validationRevision) templateInfo.value = { rows: data.sample_count, elements: data.elements.length, error: '' } }
  catch (e) { if (revision === validationRevision) templateInfo.value = { rows: 0, elements: 0, error: String(e) } }
  finally {if(revision===validationRevision)validating.value=false}
}, { immediate: true })
const estimate = computed(() => { const count = isTemplate.value ? templateInfo.value?.rows ?? 0 : Number(batch.count), size = Number(batch.packageSize); return Number.isSafeInteger(count) && count > 0 && size > 0 ? Math.ceil(count / size) : 0 })
const previewRows = computed(() => batch.result?.slice(tablePage.value * 8, tablePage.value * 8 + 8) ?? [])
const preview = ref<import('../lib/model').Spectrum | null>(null)
let previewRevision = 0
const previewLoading=ref(false),previewError=ref(''),displayedName=ref('')
let previewController:AbortController|undefined
const previewCache=new Map<string,import('../lib/model').Spectrum>()
async function loadPreview() {
  const revision=++previewRevision,job=batch.jobId,index=selected.value,name=batch.result?.[index]?.name
  previewController?.abort();previewError.value='';if(!job || !name){preview.value=null;return}
  previewLoading.value=true;previewController=new AbortController();const key=`${job}:${index}`
  try {let result=previewCache.get(key);if(!result)result=spectrumResult(await request(`/jobs/${job}/result?sample=${index}`,undefined,true,previewController.signal),job)
    if(revision!==previewRevision)return
    previewCache.delete(key);previewCache.set(key,result);while(previewCache.size>3)previewCache.delete(previewCache.keys().next().value!)
    preview.value=result;displayedName.value=`${index+1} · ${name}`
  } catch(e){if(revision===previewRevision)previewError.value=String(e)}
  finally {if(revision===previewRevision)previewLoading.value=false}
}
watch(()=>batch.jobId,()=>{selected.value=0;tablePage.value=0;preview.value=null;displayedName.value=''}, {flush:'sync'})
watch(()=>[selected.value,batch.jobId],loadPreview,{immediate:true})
onUnmounted(()=>{previewRevision++;validationRevision++;previewController?.abort();validationController?.abort()})
const temperatureRange = computed(() => { if (!batch.result?.length) return '—'; const values = batch.result.map(s => s.params.te); return `${format(Math.min(...values))}–${format(Math.max(...values))}` })
watch(() => batch.result, () => { selected.value = 0; tablePage.value = 0 })
async function run() { try { const snapshot = prepare(); submitError.value = ''; await runReal('batch', '真实批量任务', snapshot) } catch (e) { submitError.value = String(e) } }
async function chooseTemplate(event?: Event) {
  const file = event ? (event.target as HTMLInputElement).files?.[0] : undefined
  if (!desktopHost && !file || reading.value) return
  const sequence = ++uploadSequence; reading.value = true; fileError.value = ''
  try {
    const result: OpenResult = desktopHost ? await openCsvTemplate() : await readBrowserCsv(file!)
    if (sequence !== uploadSequence) return
    if (result.status === 'opened') { batch.templateName = result.name; batch.templateText = result.text }
    if (result.status === 'failed') fileError.value = result.message + '；原模板已保留'
    // Cancellation keeps the current template and does not become an error.
  } catch (e) { if (sequence === uploadSequence) fileError.value = e instanceof Error ? e.message : 'CSV 读取失败' }
  finally { if (sequence === uploadSequence) reading.value = false; if (fileInput.value) fileInput.value.value = '' }
}
function saveKind(kind: string) { if (batch.jobId) void saveOutput(`SimLIBS-${kind}.${kind === 'training' ? 'zip' : 'csv'}`, () => download(batch.jobId, kind)) }
function saveParameters() { saveKind('parameters') }
function clearTemplate() { uploadSequence++; batch.templateText = ''; batch.templateName = ''; fileError.value = ''; reading.value = false; if (fileInput.value) fileInput.value.value = '' }
</script>
<template><WorkbenchLayout kind="batch" class="batch-grid"><template #controls="{ disabled }">
  <div class="panel-heading"><h2>样本设置</h2><span class="section-number">B</span></div><div class="segmented generator-tabs"><button v-for="option in [{ id: 'fixed', label: '固定' }, { id: 'random', label: '随机' }, { id: 'template', label: 'CSV 模板' }]" :key="option.id" :aria-pressed="batch.generation === option.id" :class="{ selected: batch.generation === option.id }" :disabled="disabled" @click="batch.generation = option.id as typeof batch.generation">{{ option.label }}</button></div>
    <fieldset class="control-fieldset" :disabled="disabled"><div class="row2"><label v-if="!isTemplate" class="field">样本数<input id="batch-count" v-model="batch.count" type="text" inputmode="numeric" v-bind="attrs('count')" /></label><div v-else class="field"><label>CSV 样本数</label><div class="readout mono">{{ templateInfo?.rows || '—' }}</div></div><label class="field">每包样本数<input id="batch-packageSize" v-model="batch.packageSize" type="text" inputmode="numeric" v-bind="attrs('packageSize')" /></label></div><p class="hint">{{ estimate }} 个分包</p>
      <template v-if="isRandom"><label class="field">随机种子<input id="batch-seed" v-model="batch.seed" type="text" inputmode="numeric" v-bind="attrs('seed')" /></label><div class="random-switches"><label class="switch"><input v-model="batch.rules.te" type="checkbox" /><span class="switch-track" />随机 Te</label><label class="switch"><input v-model="batch.rules.ne" type="checkbox" /><span class="switch-track" />随机 Ne</label></div><div v-if="batch.rules.te" class="row2"><label class="field compact">Te 下界<span class="input-with-unit"><input id="batch-teMin" v-model="batch.rules.teMin" type="text" inputmode="decimal" v-bind="attrs('teMin')" /><span>eV</span></span></label><label class="field compact">Te 上界<span class="input-with-unit"><input id="batch-teMax" v-model="batch.rules.teMax" type="text" inputmode="decimal" v-bind="attrs('teMax')" /><span>eV</span></span></label></div><div v-if="batch.rules.ne" class="row2"><label class="field compact">Ne 下界<span class="input-with-unit"><input id="batch-neMin" v-model="batch.rules.neMin" type="text" inputmode="decimal" v-bind="attrs('neMin')" /><span>cm⁻³</span></span></label><label class="field compact">Ne 上界<span class="input-with-unit"><input id="batch-neMax" v-model="batch.rules.neMax" type="text" inputmode="decimal" v-bind="attrs('neMax')" /><span>cm⁻³</span></span></label></div></template>
      <div v-if="isTemplate" class="template-box" v-bind="attrs('template')"><AppIcon name="file" :size="27" /><strong>本地 CSV 模板</strong><p class="hint">元素列如 Fe_at%，每行合计 100%。</p><button v-if="desktopHost" class="btn file-select" :disabled="reading" @click="chooseTemplate()"><AppIcon name="folder" :size="14" />打开 CSV</button><label v-else class="btn file-select"><AppIcon name="plus" :size="14" />选择 CSV<input ref="fileInput" type="file" accept=".csv,text/csv" aria-label="选择本地 CSV 模板" :disabled="reading" @change="chooseTemplate" /></label><p :class="['template-name', { 'success-text': templateInfo && !templateInfo.error && !fileError }]">{{ batch.templateName || '未选择文件' }}</p><div class="template-tools"><button :class="['btn', 'sm', { danger: !!batch.templateName }]" :disabled="!batch.templateName || reading || !!running" @click="clearTemplate">清除</button><button class="btn sm" :disabled="saving" @click="saveOutput('SimLIBS-template.csv', templateCsv, 'text/csv;charset=utf-8')"><AppIcon name="download" :size="13" />保存模板</button></div><p v-if="reading" class="hint" role="status">正在读取 CSV…</p><p v-else-if="templateInfo && !templateInfo.error" class="success-text" role="status">结构与比例有效 · {{ templateInfo.rows }} 行 / {{ templateInfo.elements }} 元素</p></div>
    </fieldset>
    <div class="divider" /><ParameterEditor v-model="batch.params" scope="batch" :disabled="disabled" :hide-te="isRandom && batch.rules.te || csvHas('Te[eV]')" :hide-ne="isRandom && batch.rules.ne || csvHas('Ne[cm^-3]')" :hide-r="csvHas('R')" :te-override="isRandom && batch.rules.te ? Number(batch.rules.teMin) : csvHas('Te[eV]') ? 1 : undefined" :ne-override="isRandom && batch.rules.ne ? Number(batch.rules.neMin) : csvHas('Ne[cm^-3]') ? 1e17 : undefined" :r-override="csvHas('R') ? 1000 : undefined" /><p v-if="isTemplate" class="hint">CSV 同名参数列优先。</p><template v-else><div class="divider" /><CompositionEditor v-model="batch.composition" scope="batch" :disabled="disabled" :random="isRandom" @issue="compositionError = $event" /></template>
    <button class="btn primary full" :disabled="!!running || !!inputError" @click="run"><AppIcon name="play" :size="16" />生成样本</button>
  </template>
  <section v-if="saveFeedback" class="panel activity-panel" style="overflow-wrap:anywhere"><div class="panel-heading"><h2>文件保存</h2></div><p :class="saveFailed ? 'error-text' : 'hint'" role="status">{{ saveFeedback }}</p></section><section class="panel samples-panel"><div class="panel-heading"><div><h2>样本预览 <span class="badge neutral">真实样本</span></h2></div><button class="btn sm" :disabled="!batch.result || saving" @click="saveParameters"><AppIcon name="download" :size="14" />保存参数表</button></div>
    <div v-if="!batch.result" class="empty-state"><div class="empty-icon"><AppIcon name="batch" :size="34" /></div><h3>尚无样本</h3><p>选择生成方式并设置参数。</p></div>
    <template v-else><div class="table-scroll"><table><thead><tr><th>样本</th><th>Te / eV</th><th>Ne / cm⁻³</th><th>请求 R</th><th>组成 / at%</th></tr></thead><tbody><tr v-for="(sample, i) in previewRows" :key="i" :class="{ selected: selected === tablePage * 8 + i }"><td><button class="table-link" @click="selected = tablePage * 8 + i">{{ sample.name }}</button></td><td class="mono">{{ format(sample.params.te) }}</td><td class="mono">{{ format(sample.params.ne) }}</td><td class="mono">{{ sample.params.resolution }}</td><td><span v-for="c in sample.composition" :key="c.symbol" class="comp-chip">{{ c.symbol }} {{ format(c.pct) }}%</span></td></tr></tbody></table></div><div class="pager"><span>{{ tablePage * 8 + 1 }}–{{ Math.min(batch.result.length, tablePage * 8 + 8) }} / {{ batch.result.length }} 真实样本</span><div><button class="icon-btn" aria-label="上一页样本" :disabled="tablePage === 0" @click="tablePage--"><AppIcon name="prev" :size="14" /></button><button class="icon-btn" aria-label="下一页样本" :disabled="(tablePage + 1) * 8 >= batch.result.length" @click="tablePage++"><AppIcon name="next" :size="14" /></button></div></div></template>
  </section><TaskActivity kind="batch" :error="inputError || compositionError || submitError" /><div class="metrics-row"><div class="panel metric"><span>已完成样本</span><strong>{{ batch.result?.length ?? '—' }} <small>样本</small></strong></div><div class="panel metric"><span>Te 范围</span><strong>{{ temperatureRange }} <small>eV</small></strong></div><div class="panel metric"><span>数据类型</span><strong class="metric-text">真实参数表</strong><p>来源与实际参数随训练包保存</p></div></div><p v-if="previewLoading" class="hint" role="status">正在读取样本 {{ selected + 1 }}；已有谱图仍属于 {{ displayedName || '尚未加载' }}。</p><p v-if="previewError" class="error-text" role="alert">样本读取失败：{{ previewError }} <button class="btn sm" @click="loadPreview">重试读取样本</button></p><SpectrumChart v-if="preview" :spectrum="preview" :label="`真实样本 ${displayedName}`" /><section class="panel activity-panel"><div class="panel-heading"><h2>训练数据输出</h2><span class="badge neutral">真实文件</span></div><div class="disabled-actions"><button class="btn" :disabled="!batch.jobId || saving" @click="saveKind('dataset')">训练 CSV</button><button class="btn" :disabled="!batch.jobId || saving" @click="saveKind('training')">训练 ZIP</button><button class="btn" :disabled="!batch.jobId || saving" @click="saveKind('template')">实际模板</button></div><p class="hint">成功任务可导出完整数据集、实际参数及训练包；中断任务在任务记录中续跑。</p></section>
</WorkbenchLayout></template>
