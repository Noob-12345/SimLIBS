<script setup lang="ts">
import { computed } from 'vue'
import ProcessingModeSelect from './ProcessingModeSelect.vue'
import ChoiceSelect from './ChoiceSelect.vue'
import { errorOf, format, validateParams, type ParameterDraft } from '../lib/model'
const model = defineModel<ParameterDraft>({ required: true })
const props = defineProps<{ scope: string; disabled?: boolean; hideTe?: boolean; hideNe?: boolean; hideR?: boolean; teOverride?: number; neOverride?: number; rOverride?: number }>()
const errors = computed(() => errorOf(() => validateParams(model.value, { te: props.teOverride, ne: props.neOverride, resolution: props.rOverride })))
const controls = computed(() => [
  { key: 'te' as const, name: '电子温度', unit: 'Te / eV', hidden: props.hideTe },
  { key: 'ne' as const, name: '电子密度', unit: 'Ne / cm⁻³', hidden: props.hideNe },
  { key: 'resolution' as const, name: '光谱分辨率', unit: 'R', hidden: props.hideR }
])
const fluxChoices = [{ value: 'photon', label: '光子通量' }, { value: 'energy', label: '能量通量' }] as const
const conventionChoices = [{ value: 'physics', label: 'FWHM = λ / R' }, { value: 'nist', label: 'NIST 约定' }] as const
const temperatureChoices = [{ value: 'linked', label: '随 Te' }, { value: 'manual', label: '独立设置' }] as const
const chargeChoices = [0, 1, 2].map(value => ({ value: String(value), label: `${value}+` }))
function densityBlur() { const n = Number(model.value.ne); if (Number.isFinite(n) && n > 0) model.value.ne = n.toExponential() }
</script>
<template>
  <fieldset class="control-fieldset" :disabled="disabled">
    <section class="parameter-section"><div class="panel-heading"><h2>实验参数</h2><span class="section-number">01</span></div>
    <template v-for="control in controls" :key="control.key">
      <div v-if="!control.hidden" class="field precise-field">
        <div class="precise-row"><label :for="`${scope}-${control.key}`">{{ control.key === 'resolution' ? '分辨率' : control.name }}<span>{{ control.unit }}</span></label>
        <input :id="`${scope}-${control.key}`" v-model="model[control.key]" type="text" :inputmode="control.key === 'resolution' ? 'numeric' : 'decimal'" :aria-label="control.name" :aria-invalid="!!errorOf(() => validateParams({ ...model, low: '200', high: '500' }, { te: props.teOverride, ne: props.neOverride, resolution: props.rOverride }))" :aria-describedby="`${scope}-param-error`" @blur="control.key === 'ne' && densityBlur()" /></div>
      </div>
    </template>
    <div class="field"><label>波长窗口 <span>nm</span></label><div class="row2"><label class="sr-only" :for="`${scope}-low`">波长下界</label><input :id="`${scope}-low`" v-model="model.low" type="text" inputmode="decimal" aria-label="波长下界 nm" /><label class="sr-only" :for="`${scope}-high`">波长上界</label><input :id="`${scope}-high`" v-model="model.high" type="text" inputmode="decimal" aria-label="波长上界 nm" /></div></div>
    <div class="row2"><label class="field compact">采样步长 / nm<input v-model="model.step" type="text" inputmode="decimal" /></label><ChoiceSelect v-model="model.charge" label="最大离子电荷" :options="chargeChoices" :disabled="disabled" /></div>
    </section>
    <section class="parameter-section"><h2>计算模式</h2>
      <ProcessingModeSelect v-model="model.mode" :disabled="disabled" />
      <ChoiceSelect v-if="model.mode !== 'local'" v-model="model.flux" label="强度尺度" :options="fluxChoices" :disabled="disabled" /><div v-else class="local-flux"><span>强度尺度</span><b>光子通量</b></div>
    </section>
    <section class="parameter-section"><h2>高级选项</h2>
      <label v-if="model.mode === 'local'" class="switch"><input v-model="model.broaden" type="checkbox" /><span class="switch-track" />启用本地展宽</label>
      <Transition name="expand"><div v-if="model.mode === 'local' && model.broaden" class="optional-box">
        <div class="row2"><label class="field compact">高斯 FWHM / nm<input v-model="model.gaussian" type="text" inputmode="decimal" /></label><label class="field compact">洛伦兹 FWHM / nm<input v-model="model.lorentz" type="text" inputmode="decimal" /></label></div>
        <ChoiceSelect v-model="model.temperatureMode" label="重粒子温度" :options="temperatureChoices" :disabled="disabled" />
        <label v-if="model.temperatureMode === 'manual'" class="field">重粒子温度 / K<input v-model="model.temperature" type="text" inputmode="decimal" /></label><p v-else class="hint mono">{{ format(Number(model.te) * 11604.518) }} K · 随 Te 换算</p>
      </div></Transition>
      <div v-if="model.mode === 'client'" class="optional-box"><ChoiceSelect v-model="model.convention" label="高斯约定" :options="conventionChoices" :disabled="disabled" /><div class="row2"><label class="field compact">线中心舍入位<input v-model="model.center" type="text" placeholder="不舍入" inputmode="numeric" /></label><label class="field compact">选线阈值 / 0–1<input v-model="model.threshold" type="text" inputmode="decimal" /></label></div></div>
      <label v-if="model.mode === 'server'" class="switch"><input v-model="model.headless" type="checkbox" /><span class="switch-track" />后台抓取</label>
      <label class="switch"><input v-model="model.resample" type="checkbox" /><span class="switch-track" />插值 / 统一网格</label>
      <Transition name="expand"><label v-if="model.resample" class="field">目标网格步长 / nm<input v-model="model.resampleStep" type="text" inputmode="decimal" /></label></Transition>
    </section>
    <p v-if="errors" :id="`${scope}-param-error`" class="error-text" role="alert">{{ errors }}</p>
  </fieldset>
</template>
