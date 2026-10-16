<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ParameterEditor from '../components/ParameterEditor.vue'
import CompositionEditor from '../components/CompositionEditor.vue'
import SpectrumChart from '../components/SpectrumChart.vue'
import EmptyStateArt from '../components/EmptyStateArt.vue'
import TaskActivity from '../components/TaskActivity.vue'
import WorkbenchLayout from '../components/WorkbenchLayout.vue'
import { activeTask, runReal, single } from '../lib/workbench'
import { elementColor, errorOf, format, validateComposition, validateParams } from '../lib/model'
import { apiParams, apiComposition } from '../lib/backend'
const running = activeTask('single'), submitError = ref(''), compositionError = ref('')
const spectrum = computed(() => single.result)
const inputError = computed(() => errorOf(() => { if (compositionError.value) throw new Error(compositionError.value); validateParams(single.params); validateComposition(single.composition) }))
watch(inputError, value => { if (!value) submitError.value = '' })
const dirty = computed(() => { try { return JSON.stringify(validateParams(single.params)) !== JSON.stringify(spectrum.value?.params) || JSON.stringify(validateComposition(single.composition)) !== JSON.stringify(spectrum.value?.composition) } catch { return true } })
async function run() {
  try { if (inputError.value) throw new Error(inputError.value); const params = validateParams(single.params), comp = validateComposition(single.composition); submitError.value = ''; await runReal('single', `${comp.map(e => e.symbol).join(' / ')} · Te / eV ${format(params.te)} · R (λ/Δλ) ${params.resolution}`, { params: apiParams(params), composition: apiComposition(comp) }) }
  catch (e) { submitError.value = e instanceof Error ? e.message : '输入无效' }
}
</script>
<template><WorkbenchLayout kind="single">
  <template #controls="{ disabled }"><ParameterEditor v-model="single.params" scope="single" cards :disabled="disabled" /><div class="divider" /><CompositionEditor v-model="single.composition" scope="single" :disabled="disabled" @issue="compositionError = $event" /><button class="btn primary full" :disabled="!!running || !!inputError" @click="run"><AppIcon name="play" :size="16" />{{ single.result ? '重新生成' : '生成光谱' }}</button></template>
  <div v-if="dirty" class="draft-notice"><span>草稿已更改</span>运行后更新图谱。</div><SpectrumChart v-if="spectrum" :spectrum="spectrum" label="计算结果" /><section v-else class="panel empty-state"><EmptyStateArt /><h3>尚未生成光谱</h3><p>配置左侧实验参数与元素后点击“生成光谱”。</p></section>
  <div v-if="spectrum" class="metrics-row spectrum-metrics">
    <div class="panel metric"><span>实验参数</span><dl class="summary-parameters"><div><dt>Te / eV</dt><dd>{{ format(spectrum.params.te) }}</dd></div><div><dt>Ne / cm⁻³</dt><dd>{{ format(spectrum.params.ne) }}</dd></div><div><dt>R (λ/Δλ)</dt><dd>{{ spectrum.params.resolution }}</dd></div></dl></div>
    <div class="panel metric"><span>λ / nm</span><strong class="summary-wavelength"><span>{{ format(spectrum.params.low) }}</span><span>–{{ format(spectrum.params.high) }}</span></strong></div>
    <div class="panel metric"><span>组成元素</span><div class="summary-elements"><span v-for="element in spectrum.composition" :key="element.symbol" class="element-tile" :title="`${element.symbol} ${format(element.pct)}%`" :style="{ '--el-color': elementColor(element.symbol) }">{{ element.symbol }}</span></div></div>
  </div>
    <TaskActivity kind="single" idle-title="待计算" :error="inputError || compositionError || submitError"></TaskActivity>
</WorkbenchLayout></template>
