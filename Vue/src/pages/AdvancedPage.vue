<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import CompositionEditor from '../components/CompositionEditor.vue'
import WorkbenchLayout from '../components/WorkbenchLayout.vue'
import TaskActivity from '../components/TaskActivity.vue'
import ChoiceSelect from '../components/ChoiceSelect.vue'
import SwitchHint from '../components/SwitchHint.vue'
import AdvancedResults from '../components/AdvancedResults.vue'
import WavelengthBandBar from '../components/WavelengthBandBar.vue'
import { advanced, activeTask, runReal, tasks } from '../lib/workbench'
import { errorOf, symbols } from '../lib/model'
import { issueAttrs, parameterIssues } from '../lib/issues'
import { advancedFlags, advancedModels, changeAdvancedModel, densityChoices, prepareAdvanced, setAdvancedAbsorption, setAdvancedStark } from '../lib/advanced'
import { download } from '../lib/backend'
import { useFileSave } from '../lib/fileAccess'
const running = activeTask('advanced'), submitError = ref(''), compositionError = ref('')
const { pending: saving, feedback, failed: saveFailed, run: saveOutput } = useFileSave()
const cards = [{ key: 'te', label: 'Te', unit: 'eV' }, { key: 'ne', label: 'Ne', unit: 'cm⁻³' }, { key: 'resolution', label: 'R', unit: '(λ/Δλ)' }] as const
const chargeChoices = [0, 1, 2, 3].map(value => ({ value: String(value), label: `${value}+` }))
const issues = computed(() => parameterIssues({ ...advanced.params, mode: 'local', broaden: false, resample: false }))
const attrs = (key: string) => issueAttrs(issues.value[key], 'advanced-draft-error')
const starkSwitch = computed({ get: () => advanced.starkBroadening, set: setAdvancedStark })
const absorptionSwitch = computed({ get: () => advanced.selfAbsorption, set: setAdvancedAbsorption })
function densityBlur() { const value = Number(advanced.params.ne); if (Number.isFinite(value) && value > 0) advanced.params.ne = value.toExponential() }
const inputError = computed(() => errorOf(() => prepareAdvanced(compositionError.value)))
const latest = computed(() => tasks.find(task => task.kind === 'advanced'))
const missingTask = computed(() => latest.value?.status === 'failed' && latest.value.starkMissing?.available ? latest.value : null)
const partialResult = computed(() => {
  const result = advanced.result
  const coverage = result?.source.origin?.stark_coverage as { status?: string; missing_line_count?: number; matched_condition_count?: number } | undefined
  if (!result?.jobId || !coverage || !['partial', 'unavailable'].includes(coverage.status || '') || !Number.isInteger(coverage.missing_line_count) || !(coverage.missing_line_count! > 0)) return null
  return { jobId: result.jobId, missing: coverage.missing_line_count!, matched: coverage.matched_condition_count ?? 0, ...advancedFlags(result.source.origin) }
})
watch(inputError, value => { if (!value) submitError.value = '' })
async function run() {
  try { submitError.value = ''; await runReal('advanced', '高级客户端模拟', prepareAdvanced(compositionError.value)) }
  catch (error) { submitError.value = error instanceof Error ? error.message : String(error) }
}
function saveStark(job: string, kind: 'missing' | 'matched') { void saveOutput(`SimLIBS-${job}-${kind}-stark.csv`, () => download(job, `stark-${kind}`)) }
</script>
<<<<<<< Updated upstream
<template><WorkbenchLayout kind="advanced"><template #controls="{disabled}"><fieldset class="control-fieldset" :disabled="disabled"><div class="panel-heading"><h2>高级单次参数</h2><span class="badge neutral">本地 LTE slab</span></div><div class="row2"><label v-for="field in fields" :key="field.key" class="field">{{ field.label }}<input :id="`advanced-${field.key}`" v-model="advanced.params[field.key]" type="text" inputmode="decimal" /></label></div><label class="field">总原子/离子柱密度 / cm⁻²<input id="advanced-column" v-model="advanced.column" type="text" /></label><p class="hint">柱密度并非电子密度；两者是指定的模型条件。</p><div class="divider" /><label class="switch"><input v-model="advanced.selfAbsorption" type="checkbox" aria-label="高级自吸收" /><span class="switch-track" />自吸收</label><div class="row2"><label class="field">内禀 Gaussian FWHM / nm<input id="advanced-gaussian" v-model="advanced.gaussian" type="text" /></label><label class="field">内禀 Lorentz FWHM / nm<input id="advanced-lorentz" v-model="advanced.lorentz" type="text" /></label></div><label class="field">重粒子温度 / K<input id="advanced-temperature" v-model="advanced.temperature" type="text" /></label><p class="hint">热 Doppler 与内禀线宽决定吸收；仪器 R 仅用于传输后的卷积。</p><div class="divider" /><label class="switch"><input v-model="advanced.matrix" type="checkbox" aria-label="参数化基体效应" /><span class="switch-track" />参数化基体效应</label><div class="row2"><label class="field">Te 修正倍率<input v-model="advanced.teFactor" :disabled="!advanced.matrix" type="text" /></label><label class="field">Ne 修正倍率<input v-model="advanced.neFactor" :disabled="!advanced.matrix" type="text" /></label></div></fieldset><div class="divider" /><CompositionEditor v-model="advanced.composition" scope="advanced" :disabled="disabled" @issue="compositionError=$event" /><fieldset class="control-fieldset" :disabled="disabled || !advanced.matrix"><label v-for="row in advanced.composition" :key="row.id" class="field">{{ row.symbol }} 元素响应（默认1）<input :value="advanced.responses[row.symbol]??'1'" type="text" @input="advanced.responses[row.symbol]=($event.target as HTMLInputElement).value" /></label></fieldset><p class="hint">未标定参数模型，可后续用实验校准；不是普适材料预测。</p><button class="btn primary full" :disabled="!!running || !!inputError" @click="run">运行高级模拟</button></template><section class="panel activity-panel"><h2>均匀 LTE slab · 有限 I/II 能级</h2><p class="hint">真实本地原子数据与参数化条件。不含时空梯度、散射、连续吸收或完整 Stark 数据；不预测自反转，不是 NIST 在线结果。相对波段限5%，超出数值资源上限会明确拒绝。</p></section><SpectrumChart v-if="advanced.result" :spectrum="advanced.result" label="高级三谱对照" /><section v-else class="panel empty-state"><h3>尚无高级结果</h3><p>运行后显示名义薄谱、基体薄谱及自吸收修正谱。</p></section><section v-if="diagnostics" class="panel activity-panel"><h2>已完成结果诊断</h2><p>最大 τ {{ format(diagnostics.tau_max!) }} · 最小 β {{ format(diagnostics.beta_min!) }} · 谱线 {{ diagnostics.line_count }}</p><p v-if="matrixResult">有效 Te {{ format(matrixResult.effective_Te_eV!) }} eV · Ne {{ format(matrixResult.effective_Ne_cm3!) }} cm⁻³ · 产额倍率 {{ format(matrixResult.yield_scale!) }}</p><p class="hint">三个谱共用归一化尺度；薄谱参考与修正谱都经过同一仪器响应。CSV/JSON携带对照，PNG保留颜色图例。</p></section><TaskActivity kind="advanced" :error="inputError || submitError" /></WorkbenchLayout></template>
=======
<template>
  <WorkbenchLayout kind="advanced">
    <template #controls="{ disabled }">
      <fieldset class="control-fieldset advanced-parameters" :disabled="disabled">
        <section class="parameter-section">
          <div class="panel-heading"><h2>实验参数</h2><span class="section-number">01</span></div>
          <div class="parameter-cards"><div v-for="field in cards" :key="field.key" class="field precise-field parameter-card" :data-parameter="field.key"><label :for="`advanced-${field.key}`">{{ field.label }}<span class="card-title-unit">{{ field.key === 'resolution' ? '' : ' ' }}{{ field.unit }}</span></label><div class="card-value"><input :id="`advanced-${field.key}`" v-model="advanced.params[field.key]" type="text" :inputmode="field.key === 'resolution' ? 'numeric' : 'decimal'" :aria-label="`${field.label} ${field.unit}`" v-bind="attrs(field.key)" @blur="field.key === 'ne' && densityBlur()" /></div></div></div>
          <div class="row2">
            <label for="advanced-low" class="field compact">波长下限 / nm<input id="advanced-low" v-model="advanced.params.low" type="text" inputmode="decimal" aria-label="波长下限 / nm" v-bind="attrs('low')" /></label>
            <label for="advanced-high" class="field compact">波长上限 / nm<input id="advanced-high" v-model="advanced.params.high" type="text" inputmode="decimal" aria-label="波长上限 / nm" v-bind="attrs('high')" /></label>
          </div>
          <WavelengthBandBar :low="advanced.params.low" :high="advanced.params.high" />
          <div class="row2"><label class="field compact">输出步长 / nm<input id="advanced-step" v-model="advanced.params.step" type="text" inputmode="decimal" v-bind="attrs('step')" /></label><ChoiceSelect v-model="advanced.params.charge" label="最大发射电荷" :options="chargeChoices" :disabled="disabled" :issue="issues.charge" issue-id="advanced-draft-error" /></div>
        </section>
        <section class="parameter-section">
          <div class="panel-heading"><h2>模型与展宽</h2><span class="section-number">02</span></div>
          <ChoiceSelect :model-value="advanced.model" label="模拟方式" :options="advancedModels" :disabled="disabled" @update:model-value="changeAdvancedModel" />
          <div class="advanced-switches" role="group" aria-label="展宽机制">
            <SwitchHint v-model="starkSwitch" label="Stark 展宽" description="逐线内禀 Lorentz 展宽；缺失系数时自动继续并保留清单。关闭时同时关闭自吸收；开启时不改变自吸收或仪器展宽。" :disabled="disabled" />
            <SwitchHint v-model="absorptionSwitch" label="逐线自吸收" description="按布居与光程计算逐线吸收及展宽。客户端模拟开启自吸收会自动开启 Stark；关闭自吸收保留 Stark 与仪器展宽。" :disabled="disabled" />
            <SwitchHint v-model="advanced.instrumentBroadening" label="仪器展宽（Gaussian）" description="仪器响应独立开关，不改变 Stark 或自吸收。启用后由 R 控制高斯线宽；先计算内禀谱，再应用仪器响应。" :disabled="disabled" />
          </div>
          <details class="advanced-help"><summary>模型与线宽约定</summary>
            <p class="hint">在线取得 NIST 谱线与线强，由本地引擎计算展宽及逐线自吸收；Stark 需要跃迁和逐线系数；缺失系数时自动继续并标记覆盖不足：保留 NIST 面积，缺失线跳过 Stark 和自吸收，仪器展宽仍按开关应用。自吸收还需要全阶段能级与布居。默认 Mg 100%、真空 285.27–285.33 nm；发射电荷范围为 0–2。</p><p class="hint">仪器 w=λ/R 为高斯 1/e 半宽，FWHM=2√ln2·λ/R，R 不进入 τ。仅 Stark 为 Lorentz，叠加仪器为 Voigt；两者都关闭时为守恒面积/重心的网格投影，高度依赖步长，不代表物理线宽。</p>
          </details>
          <Transition name="expand"><div v-if="advanced.starkBroadening" class="advanced-subpanel" data-advanced-section="stark-data">
            <h3>Stark 数据与计算</h3>
            <p class="hint">自动优先序：本地 JSON → 在线 STARK-B → NIST 原子数据＋DK1980 修正半经验 → 明确缺失。按真实跃迁身份及温度、密度条件逐层匹配，工作台活动显示当前元素与阶段。</p>
            <p class="hint">DK1980 仅适用于实际电荷 q=2／3（光谱标号 III／IV），并要求完整能级、E1 跃迁 Aki、统计权重和电离阈值。数据不足不补造系数，逐线诊断保留各层原因及来源。</p>
          </div></Transition>
          <Transition name="expand"><div v-if="advanced.selfAbsorption" class="advanced-subpanel" data-advanced-section="medium">
            <h3>自吸收介质</h3>
            <label class="field">光程 L / m<input id="advanced-path-length" v-model="advanced.pathLength" type="text" inputmode="decimal" /></label>
            <ChoiceSelect v-model="advanced.densityMode" label="总数密度方式" :options="densityChoices" :disabled="disabled" /><label v-if="advanced.densityMode === 'specified'" class="field">总原子/离子数密度 / cm⁻³<input id="advanced-number-density" v-model="advanced.numberDensity" type="text" inputmode="decimal" /></label><p class="hint">默认由 Ne 与全阶段平均电荷反推密度；L=0 为同线形薄谱极限。基体产额作用于有效密度。</p>
          </div></Transition>
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
        <section class="parameter-section">
          <CompositionEditor v-model="advanced.composition" scope="advanced" section-number="03" mode-override="client" :candidate-symbols="symbols" :disabled="disabled" @issue="compositionError = $event" />
        </section>
      </fieldset>
      <button class="btn primary full" :disabled="!!running || !!inputError" @click="run">运行高级模拟</button>
    </template>
    <AdvancedResults :spectrum="advanced.result">
      <template #after-spectrum><TaskActivity kind="advanced" :error="inputError || submitError" /></template>
    </AdvancedResults>
    <section v-if="partialResult" class="panel activity-panel" role="status" data-stark-coverage="partial">
      <h2>Stark 覆盖不足 · 已继续生成</h2>
      <p>当前结果 {{ partialResult.jobId }} 有 {{ partialResult.missing }} 条跃迁缺少 Stark 系数。缺失线保留 NIST 线面积，{{ partialResult.instrument ? '仅应用仪器展宽' : '按保面积与质心的网格投影显示' }}；未计算这些线的 Stark 展宽{{ partialResult.absorption ? '或自吸收' : '' }}。</p>
      <p class="hint">已匹配线按对应来源计算；缺失清单用于核对各层原因，不作为 CSV 导入入口。当前结果和清单绑定原任务，不随草稿改变。</p>
      <div class="row2"><button class="btn" :disabled="saving" @click="saveStark(partialResult.jobId, 'missing')">下载缺失系数清单</button><button v-if="partialResult.matched > 0" class="btn" :disabled="saving" @click="saveStark(partialResult.jobId, 'matched')">下载已匹配清单</button></div>
    </section>
    <section class="panel activity-panel"><h2>高级物理模拟 (LTE Slab)</h2><p class="hint">名义薄谱、基体薄谱和修正谱使用共同尺度。逐线独立模型，不预测连续谱、自反转、时空梯度或重叠谱线耦合传输。新草稿不会改写已完成结果。</p></section>
    <section v-if="missingTask" class="panel activity-panel"><h2>Stark 数据待补充</h2><p>任务 {{ missingTask.id }} 有 {{ missingTask.starkMissing?.count }} 条跃迁在 JSON、在线 STARK-B 和 NIST＋DK1980 级联后仍无适用宽度。</p><div class="row2"><button class="btn" :disabled="saving" @click="saveStark(missingTask.id, 'missing')">下载完整缺失清单</button><button class="btn primary" :disabled="!!running" @click="run">缺失线未展宽合成 (保留面积)</button></div><p class="hint">清单保留各层原因和实际适用限制；重试时缺失线自动保留面积并继续生成。</p></section>
    <p v-if="feedback" :class="saveFailed ? 'error-text' : 'hint'" role="status">{{ feedback }}</p>
  </WorkbenchLayout>
</template>
>>>>>>> Stashed changes
