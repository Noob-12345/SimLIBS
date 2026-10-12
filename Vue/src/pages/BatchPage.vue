<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ParameterEditor from '../components/ParameterEditor.vue'
import CompositionEditor from '../components/CompositionEditor.vue'
import TaskActivity from '../components/TaskActivity.vue'
import SpectrumChart from '../components/SpectrumChart.vue'
import WorkbenchLayout from '../components/WorkbenchLayout.vue'
import { batchCsv, generateSpectrum, parseCsv, randomSamples, templateCsv, validateTemplate } from '../lib/demo'
import { desktopHost, openCsvTemplate, readBrowserCsv, useFileSave, type OpenResult } from '../lib/fileAccess'
import { errorOf, format, numeric, validateComposition, validateParams, type BatchSample } from '../lib/model'
import { activeTask, batch, runDemo } from '../lib/workbench'
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
function prepare(): BatchSample[] {
  numeric(batch.packageSize, '每包数', 1, 500, true)
  if (batch.generation === 'template') { if (reading.value) throw new Error('正在读取 CSV'); if (fileError.value) throw new Error(fileError.value); if (!batch.templateText) throw new Error('请选择本地 CSV 模板'); return validateTemplate(batch.templateText, batch.params) }
  const count = numeric(batch.count, '演示样本数', 1, 500, true)
  if (batch.generation === 'random') return randomSamples(batch.params, batch.composition, batch.rules, count, numeric(batch.seed, '随机种子', 0, 4294967295, true))
  const params = validateParams(batch.params), composition = validateComposition(batch.composition)
  return Array.from({ length: count }, (_, i) => ({ name: `Fixed-demo-${i + 1}`, params: { ...params }, composition: composition.map(c => ({ ...c })) }))
}
const inputError = computed(() => errorOf(prepare))
watch(inputError, value => { if (!value) submitError.value = '' })
const templateInfo = computed(() => { if (!batch.templateText) return null; try { const samples = validateTemplate(batch.templateText, batch.params); return { rows: samples.length, elements: samples[0]!.composition.length, error: '' } } catch (e) { return { rows: 0, elements: 0, error: e instanceof Error ? e.message : 'CSV 无效' } } })
const estimate = computed(() => { const count = isTemplate.value ? templateInfo.value?.rows ?? 0 : Number(batch.count), size = Number(batch.packageSize); return Number.isSafeInteger(count) && count > 0 && size > 0 ? Math.ceil(count / size) : 0 })
const previewRows = computed(() => batch.result?.slice(tablePage.value * 8, tablePage.value * 8 + 8) ?? [])
const preview = computed(() => { const sample = batch.result?.[selected.value]; return sample ? generateSpectrum(sample.params, sample.composition, `batch-sample-demo-${selected.value}`) : null })
const temperatureRange = computed(() => { if (!batch.result?.length) return '—'; const values = batch.result.map(s => s.params.te); return `${format(Math.min(...values))}–${format(Math.max(...values))}` })
watch(() => batch.result, () => { selected.value = 0; tablePage.value = 0 })
function run() { try { const snapshot = prepare(), kind = batch.generation, size = numeric(batch.packageSize, '每包数', 1, 500, true); submitError.value = ''; runDemo('batch', `${kind === 'fixed' ? '固定' : kind === 'random' ? '随机' : 'CSV'} · ${snapshot.length} 个示意样本 · 每包 ${size}`, () => snapshot) } catch (e) { submitError.value = e instanceof Error ? e.message : '输入无效' } }
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
function saveParameters() { if (batch.result) void saveOutput('SimLIBS-frontend_demo-parameters.csv', batchCsv(batch.result), 'text/csv;charset=utf-8') }
function clearTemplate() { uploadSequence++; batch.templateText = ''; batch.templateName = ''; fileError.value = ''; reading.value = false; if (fileInput.value) fileInput.value.value = '' }
</script>
<template><WorkbenchLayout kind="batch" class="batch-grid"><template #controls="{ disabled }">
  <div class="panel-heading"><h2>样本设置</h2><span class="section-number">B</span></div><div class="segmented generator-tabs"><button v-for="option in [{ id: 'fixed', label: '固定' }, { id: 'random', label: '随机' }, { id: 'template', label: 'CSV 模板' }]" :key="option.id" :aria-pressed="batch.generation === option.id" :class="{ selected: batch.generation === option.id }" :disabled="disabled" @click="batch.generation = option.id as typeof batch.generation">{{ option.label }}</button></div>
    <fieldset class="control-fieldset" :disabled="disabled"><div class="row2"><label v-if="!isTemplate" class="field">演示样本数<input id="batch-count" v-model="batch.count" type="text" inputmode="numeric" v-bind="attrs('count')" /></label><div v-else class="field"><label>CSV 样本数</label><div class="readout mono">{{ templateInfo?.rows || '—' }}</div></div><label class="field">每包样本数<input id="batch-packageSize" v-model="batch.packageSize" type="text" inputmode="numeric" v-bind="attrs('packageSize')" /></label></div><p class="hint">{{ estimate }} 个分包</p>
      <template v-if="isRandom"><label class="field">随机种子<input id="batch-seed" v-model="batch.seed" type="text" inputmode="numeric" v-bind="attrs('seed')" /></label><div class="random-switches"><label class="switch"><input v-model="batch.rules.te" type="checkbox" /><span class="switch-track" />随机 Te</label><label class="switch"><input v-model="batch.rules.ne" type="checkbox" /><span class="switch-track" />随机 Ne</label></div><div v-if="batch.rules.te" class="row2"><label class="field compact">Te 下界<span class="input-with-unit"><input id="batch-teMin" v-model="batch.rules.teMin" type="text" inputmode="decimal" v-bind="attrs('teMin')" /><span>eV</span></span></label><label class="field compact">Te 上界<span class="input-with-unit"><input id="batch-teMax" v-model="batch.rules.teMax" type="text" inputmode="decimal" v-bind="attrs('teMax')" /><span>eV</span></span></label></div><div v-if="batch.rules.ne" class="row2"><label class="field compact">Ne 下界<span class="input-with-unit"><input id="batch-neMin" v-model="batch.rules.neMin" type="text" inputmode="decimal" v-bind="attrs('neMin')" /><span>cm⁻³</span></span></label><label class="field compact">Ne 上界<span class="input-with-unit"><input id="batch-neMax" v-model="batch.rules.neMax" type="text" inputmode="decimal" v-bind="attrs('neMax')" /><span>cm⁻³</span></span></label></div></template>
      <div v-if="isTemplate" class="template-box" v-bind="attrs('template')"><AppIcon name="file" :size="27" /><strong>本地 CSV 模板</strong><p class="hint">元素列如 Fe_at%，每行合计 100%。</p><button v-if="desktopHost" class="btn file-select" :disabled="reading" @click="chooseTemplate()"><AppIcon name="folder" :size="14" />打开 CSV</button><label v-else class="btn file-select"><AppIcon name="plus" :size="14" />选择 CSV<input ref="fileInput" type="file" accept=".csv,text/csv" aria-label="选择本地 CSV 模板" :disabled="reading" @change="chooseTemplate" /></label><p :class="['template-name', { 'success-text': templateInfo && !templateInfo.error && !fileError }]">{{ batch.templateName || '未选择文件' }}</p><div class="template-tools"><button :class="['btn', 'sm', { danger: !!batch.templateName }]" :disabled="!batch.templateName || reading || !!running" @click="clearTemplate">清除</button><button class="btn sm" :disabled="saving" @click="saveOutput('SimLIBS-frontend_demo-template.csv', templateCsv, 'text/csv;charset=utf-8')"><AppIcon name="download" :size="13" />保存模板</button></div><p v-if="reading" class="hint" role="status">正在读取 CSV…</p><p v-else-if="templateInfo && !templateInfo.error" class="success-text" role="status">结构与比例有效 · {{ templateInfo.rows }} 行 / {{ templateInfo.elements }} 元素</p></div>
    </fieldset>
    <div class="divider" /><ParameterEditor v-model="batch.params" scope="batch" :disabled="disabled" :hide-te="isRandom && batch.rules.te || csvHas('Te[eV]')" :hide-ne="isRandom && batch.rules.ne || csvHas('Ne[cm^-3]')" :hide-r="csvHas('R')" :te-override="isRandom && batch.rules.te ? Number(batch.rules.teMin) : csvHas('Te[eV]') ? 1 : undefined" :ne-override="isRandom && batch.rules.ne ? Number(batch.rules.neMin) : csvHas('Ne[cm^-3]') ? 1e17 : undefined" :r-override="csvHas('R') ? 1000 : undefined" /><p v-if="isTemplate" class="hint">CSV 同名参数列优先。</p><template v-else><div class="divider" /><CompositionEditor v-model="batch.composition" scope="batch" :disabled="disabled" :random="isRandom" @issue="compositionError = $event" /></template>
    <button class="btn primary full" :disabled="!!running || !!inputError" @click="run"><AppIcon name="play" :size="16" />生成样本</button>
  </template>
  <section v-if="saveFeedback" class="panel activity-panel" style="overflow-wrap:anywhere"><div class="panel-heading"><h2>文件保存</h2></div><p :class="saveFailed ? 'error-text' : 'hint'" role="status">{{ saveFeedback }}</p></section><section class="panel samples-panel"><div class="panel-heading"><div><h2>样本预览 <span class="badge neutral">示意样本</span></h2></div><button class="btn sm" :disabled="!batch.result || saving" @click="saveParameters"><AppIcon name="download" :size="14" />保存参数表</button></div>
    <div v-if="!batch.result" class="empty-state"><div class="empty-icon"><AppIcon name="batch" :size="34" /></div><h3>尚无样本</h3><p>选择生成方式并设置参数。</p></div>
    <template v-else><div class="table-scroll"><table><thead><tr><th>样本</th><th>Te / eV</th><th>Ne / cm⁻³</th><th>R</th><th>组成 / at%</th></tr></thead><tbody><tr v-for="(sample, i) in previewRows" :key="i" :class="{ selected: selected === tablePage * 8 + i }"><td><button class="table-link" @click="selected = tablePage * 8 + i">{{ sample.name }}</button></td><td class="mono">{{ format(sample.params.te) }}</td><td class="mono">{{ format(sample.params.ne) }}</td><td class="mono">{{ sample.params.resolution }}</td><td><span v-for="c in sample.composition" :key="c.symbol" class="comp-chip">{{ c.symbol }} {{ format(c.pct) }}%</span></td></tr></tbody></table></div><div class="pager"><span>{{ tablePage * 8 + 1 }}–{{ Math.min(batch.result.length, tablePage * 8 + 8) }} / {{ batch.result.length }} 示意样本</span><div><button class="icon-btn" aria-label="上一页样本" :disabled="tablePage === 0" @click="tablePage--"><AppIcon name="prev" :size="14" /></button><button class="icon-btn" aria-label="下一页样本" :disabled="(tablePage + 1) * 8 >= batch.result.length" @click="tablePage++"><AppIcon name="next" :size="14" /></button></div></div></template>
  </section><TaskActivity kind="batch" :error="inputError || compositionError || submitError" /><div class="metrics-row"><div class="panel metric"><span>已完成样本</span><strong>{{ batch.result?.length ?? '—' }} <small>样本</small></strong></div><div class="panel metric"><span>Te 范围</span><strong>{{ temperatureRange }} <small>eV</small></strong></div><div class="panel metric"><span>数据类型</span><strong class="metric-text">示意参数表</strong><p>真实训练包未接入</p></div></div><SpectrumChart v-if="preview" :spectrum="preview" :label="`示意样本 ${selected + 1}`" /><section class="panel activity-panel"><div class="panel-heading"><h2>训练数据输出</h2><span class="badge neutral">待连接引擎</span></div><div class="disabled-actions"><button class="btn" disabled>训练 CSV</button><button class="btn" disabled>数据集 ZIP</button><button class="btn" disabled>续跑任务</button></div><p class="hint">引擎未接入，可保存示意参数表。</p></section>
</WorkbenchLayout></template>
