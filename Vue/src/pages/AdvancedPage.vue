<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import CompositionEditor from '../components/CompositionEditor.vue'
import WorkbenchLayout from '../components/WorkbenchLayout.vue'
import TaskActivity from '../components/TaskActivity.vue'
import ChoiceSelect from '../components/ChoiceSelect.vue'
import SwitchHint from '../components/SwitchHint.vue'
import AdvancedResults from '../components/AdvancedResults.vue'
import { advanced, activeTask, runReal, tasks } from '../lib/workbench'
import { errorOf, symbols } from '../lib/model'
import { issueAttrs, parameterIssues } from '../lib/issues'
import { advancedModels, applyAdvancedStark, changeAdvancedModel, clearAdvancedStark, densityChoices, prepareAdvanced, setAdvancedAbsorption, setAdvancedStark } from '../lib/advanced'
import { download } from '../lib/backend'
import { desktopHost, openCsvTemplate, readBrowserCsv, useFileSave } from '../lib/fileAccess'
const running = activeTask('advanced'), submitError = ref(''), compositionError = ref(''), fileError = ref(''), reading = ref(false)
const fileInput = ref<HTMLInputElement>(), importRevision = ref(0)
const { pending: saving, feedback, failed: saveFailed, run: saveOutput } = useFileSave()
const nist = computed(() => advanced.model === 'nist')
const cards = [{ key: 'te', label: 'Te', unit: 'eV' }, { key: 'ne', label: 'Ne', unit: 'cm⁻³' }, { key: 'resolution', label: 'R', unit: '(λ/Δλ)' }] as const
const chargeChoices = [0, 1, 2].map(value => ({ value: String(value), label: `${value}+` }))
const issues = computed(() => parameterIssues({ ...advanced.params, mode: 'local', broaden: false, resample: false }))
const attrs = (key: string) => issueAttrs(issues.value[key], 'advanced-draft-error')
const starkSwitch = computed({ get: () => nist.value ? advanced.starkBroadening : true, set: setAdvancedStark })
const absorptionSwitch = computed({ get: () => advanced.selfAbsorption, set: setAdvancedAbsorption })
function densityBlur() { const value = Number(advanced.params.ne); if (Number.isFinite(value) && value > 0) advanced.params.ne = value.toExponential() }
const inputError = computed(() => errorOf(() => prepareAdvanced(compositionError.value)))
const latest = computed(() => tasks.find(task => task.kind === 'advanced'))
const missingTask = computed(() => latest.value?.status === 'failed' && latest.value.starkMissing?.available ? latest.value : null)
watch(inputError, value => { if (!value) submitError.value = '' })
async function run() {
  try { submitError.value = ''; await runReal('advanced', nist.value ? '高级 NIST 模拟' : '高级离线论文模型', prepareAdvanced(compositionError.value)) }
  catch (error) { submitError.value = error instanceof Error ? error.message : String(error) }
}
async function chooseStark(event?: Event) {
  const file = event ? (event.target as HTMLInputElement).files?.[0] : undefined
  if (reading.value || !desktopHost && !file) return
  const revision = ++importRevision.value; reading.value = true; fileError.value = ''
  try {
    const result = desktopHost ? await openCsvTemplate() : await readBrowserCsv(file!)
    if (revision !== importRevision.value) return
    fileError.value = applyAdvancedStark(result)
    if (result.status === 'opened') submitError.value = ''
  } finally { if (revision === importRevision.value) reading.value = false; if (fileInput.value) fileInput.value.value = '' }
}
function clearStark() { importRevision.value++; clearAdvancedStark(); fileError.value = ''; reading.value = false; if (fileInput.value) fileInput.value.value = '' }
function saveMissing() { const job = missingTask.value?.id; if (job) void saveOutput(`SimLIBS-${job}-missing-stark.csv`, () => download(job, 'stark-missing')) }
</script>
<template>
  <WorkbenchLayout kind="advanced">
    <template #controls="{ disabled }">
      <fieldset class="control-fieldset advanced-parameters" :disabled="disabled">
        <section class="parameter-section">
          <div class="panel-heading"><h2>实验参数</h2><span class="section-number">01</span></div>
          <div class="parameter-cards"><div v-for="field in cards" :key="field.key" class="field precise-field parameter-card" :data-parameter="field.key"><label :for="`advanced-${field.key}`">{{ field.label }}<span class="card-title-unit">{{ field.key === 'resolution' ? '' : ' ' }}{{ field.unit }}</span></label><div class="card-value"><input :id="`advanced-${field.key}`" v-model="advanced.params[field.key]" type="text" :inputmode="field.key === 'resolution' ? 'numeric' : 'decimal'" :aria-label="`${field.label} ${field.unit}`" v-bind="attrs(field.key)" @blur="field.key === 'ne' && densityBlur()" /></div></div></div>
          <p class="hint">Te、Ne 为名义参数；R 仅在启用仪器展宽时控制线宽。</p>
          <div class="row2">
            <label for="advanced-low" class="field compact">波长下限 / nm<input id="advanced-low" v-model="advanced.params.low" type="text" inputmode="decimal" aria-label="波长下限 / nm" v-bind="attrs('low')" /></label>
            <label for="advanced-high" class="field compact">波长上限 / nm<input id="advanced-high" v-model="advanced.params.high" type="text" inputmode="decimal" aria-label="波长上限 / nm" v-bind="attrs('high')" /></label>
          </div>
          <div class="row2"><label class="field compact">输出步长 / nm<input id="advanced-step" v-model="advanced.params.step" type="text" inputmode="decimal" v-bind="attrs('step')" /></label><ChoiceSelect v-model="advanced.params.charge" label="最大发射电荷" :options="chargeChoices" :disabled="disabled" :issue="issues.charge" issue-id="advanced-draft-error" /></div>
        </section>
        <section class="parameter-section">
          <div class="panel-heading"><h2>模型与展宽</h2><span class="section-number">02</span></div>
          <ChoiceSelect :model-value="advanced.model" label="高级模型" :options="advancedModels" :disabled="disabled" @update:model-value="changeAdvancedModel" />
          <div class="advanced-switches" role="group" aria-label="展宽机制">
            <SwitchHint v-model="starkSwitch" label="Stark 展宽" :description="nist ? '逐线内禀 Lorentz 展宽，需要完整 Stark 系数。关闭时同时关闭自吸收；开启时不改变自吸收或仪器展宽。' : '离线论文模型使用固有 Stark 宽度，固定开启。'" :disabled="disabled || !nist" />
            <SwitchHint v-model="absorptionSwitch" label="逐线自吸收" description="按布居与光程计算逐线吸收及展宽。NIST 模型开启自吸收会自动开启 Stark；关闭自吸收保留 Stark 与仪器展宽。" :disabled="disabled" />
            <SwitchHint v-model="advanced.instrumentBroadening" label="仪器展宽（Gaussian）" description="仪器响应独立开关，不改变 Stark 或自吸收。启用后由 R 控制高斯线宽；先计算内禀谱，再应用仪器响应。" :disabled="disabled" />
          </div>
          <details class="advanced-help"><summary>模型与线宽约定</summary>
            <template v-if="nist"><p class="hint">在线取得 NIST 线强；Stark 需要跃迁和完整逐线系数，自吸收还需要全阶段能级与布居。默认 Mg 100%、真空 285.27–285.33 nm；发射电荷范围为 0–2。</p><p class="hint">仪器 w=λ/R 为高斯 1/e 半宽，FWHM=2√ln2·λ/R，R 不进入 τ。仅 Stark 为 Lorentz，叠加仪器为 Voigt；两者都关闭时为守恒面积/重心的网格投影，高度依赖步长，不代表物理线宽。</p></template>
            <template v-else><p class="hint">离线论文 Table 1 的 Mg、Ca、Zn 共31条谱线与 NIST I/II/III 能级快照；仅此模型保留 5% 窄带限制。</p><p class="hint">离线约定：仪器 FWHM=λ/R；Stark/自吸收逐线计算在仪器响应之前，R 不进入 τ。</p></template>
          </details>
          <Transition name="expand"><div v-if="nist && advanced.starkBroadening" class="advanced-subpanel" data-advanced-section="stark-data">
            <h3>Stark 系数</h3>
            <button v-if="desktopHost" type="button" class="btn" :disabled="disabled || reading" @click="chooseStark()">导入 Stark CSV</button>
            <label v-else class="btn file-select">导入 Stark CSV<input ref="fileInput" type="file" accept=".csv,text/csv" aria-label="导入 Stark CSV" :disabled="disabled || reading" @change="chooseStark" /></label>
            <div class="backend-action"><span :class="advanced.starkName ? 'success-text' : 'hint'" role="status">{{ reading ? '正在读取…' : advanced.starkName || '未导入：内置系数不足时自动查询 STARK-B' }}</span><button type="button" class="btn sm danger" :disabled="disabled || !advanced.starkName || reading" @click="clearStark">清除系数</button></div>
            <p v-if="fileError" class="error-text" role="alert">{{ fileError }}</p>
            <details class="advanced-help"><summary>CSV 格式、单位与来源</summary><p class="hint">优先序：用户 CSV → 内置 JSON → STARK-B。自动匹配受量子态和温度、密度覆盖限制；CSV 最大 2 MB。W = stark_width_nm，FWHM = 2W·Ne/Ne_ref；不是直接输入 FWHM。系数应有可追溯出处。</p><p class="hint">列：element、charge、stark_width_nm；真空 wavelength_nm 或成对 lower_eV/upper_eV；可选 stark_reference_ne_cm3、source。缺失清单填写 W 后可直接导入，勿按界面精度截断标识。</p></details>
          </div></Transition>
          <Transition name="expand"><div v-if="!nist || advanced.selfAbsorption" class="advanced-subpanel" data-advanced-section="medium">
            <h3>{{ nist ? '自吸收介质' : '介质与离线密度' }}</h3>
            <label class="field">光程 L / m<input id="advanced-path-length" v-model="advanced.pathLength" type="text" inputmode="decimal" /></label>
            <template v-if="nist"><ChoiceSelect v-model="advanced.densityMode" label="总数密度方式" :options="densityChoices" :disabled="disabled" /><label v-if="advanced.densityMode === 'specified'" class="field">总原子/离子数密度 / cm⁻³<input id="advanced-number-density" v-model="advanced.numberDensity" type="text" inputmode="decimal" /></label><p class="hint">默认由 Ne 与全阶段平均电荷反推密度；L=0 为同线形薄谱极限。基体产额作用于有效密度。</p></template>
            <template v-else><label class="field">总原子/离子柱密度 / cm⁻²<input id="advanced-column" v-model="advanced.column" type="text" inputmode="decimal" /></label><p class="hint">N = 柱密度 / (100 × L)，单位 cm⁻³；L 必须大于0。基体产额倍率再作用于 N。</p></template>
          </div></Transition>
        </section>
        <section class="parameter-section">
          <CompositionEditor v-model="advanced.composition" scope="advanced" section-number="03" mode-override="client" :candidate-symbols="nist ? symbols : ['Mg','Ca','Zn']" :disabled="disabled" @issue="compositionError = $event" />
          <div class="advanced-subpanel">
            <h3>可选基体</h3>
            <SwitchHint v-model="advanced.matrix" label="参数化基体效应" description="未标定响应模型：修正有效 Te、Ne 与各元素产额。不能代表普适材料预测；关闭时保留草稿。" :disabled="disabled" />
            <Transition name="expand"><div v-if="advanced.matrix" data-advanced-section="matrix">
              <div class="row2"><label class="field">Te 修正倍率<input v-model="advanced.teFactor" type="text" inputmode="decimal" /></label><label class="field">Ne 修正倍率<input v-model="advanced.neFactor" type="text" inputmode="decimal" /></label></div>
              <label v-for="row in advanced.composition" :key="row.id" class="field">{{ row.symbol }} 元素响应（默认1）<input :value="advanced.responses[row.symbol] ?? '1'" type="text" inputmode="decimal" @input="advanced.responses[row.symbol] = ($event.target as HTMLInputElement).value" /></label>
              <p class="hint">未标定：NIST 名义与有效条件分别取数，产额倍率作用于有效线强与吸收粒子密度。</p>
            </div></Transition>
          </div>
        </section>
      </fieldset>
      <button class="btn primary full" :disabled="!!running || !!inputError || reading" @click="run">运行高级模拟</button>
    </template>
    <AdvancedResults :spectrum="advanced.result" />
    <section class="panel activity-panel"><h2>高级物理模拟 (LTE Slab)</h2><p class="hint">名义薄谱、基体薄谱和修正谱使用共同尺度。逐线独立模型，不预测连续谱、自反转、时空梯度或重叠谱线耦合传输。新草稿不会改写已完成结果。</p></section>
    <section v-if="missingTask" class="panel activity-panel"><h2>Stark 系数待补充</h2><p>任务 {{ missingTask.id }} 缺少 {{ missingTask.starkMissing?.count }} 条逐线系数；未生成不完整谱。</p><button class="btn" :disabled="saving" @click="saveMissing">下载完整缺失清单</button><p class="hint">填写 W 和系数出处后导入上方 Stark CSV，再运行高级模拟。上一成功结果及其导出仍保留。</p></section>
    <p v-if="feedback" :class="saveFailed ? 'error-text' : 'hint'" role="status">{{ feedback }}</p>
    <TaskActivity kind="advanced" :error="inputError || submitError" />
  </WorkbenchLayout>
</template>
