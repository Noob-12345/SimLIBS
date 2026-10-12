<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ParameterEditor from '../components/ParameterEditor.vue'
import CompositionEditor from '../components/CompositionEditor.vue'
import SpectrumChart from '../components/SpectrumChart.vue'
import TaskActivity from '../components/TaskActivity.vue'
import WorkbenchLayout from '../components/WorkbenchLayout.vue'
import { activeTask, initialSpectrum, runDemo, single } from '../lib/workbench'
import { elementColor, errorOf, format, validateComposition, validateParams } from '../lib/model'
import { generateSpectrum } from '../lib/demo'
const running = activeTask('single'), submitError = ref(''), compositionError = ref('')
const spectrum = computed(() => single.result ?? initialSpectrum)
const inputError = computed(() => errorOf(() => { validateParams(single.params); validateComposition(single.composition) }))
watch(inputError, value => { if (!value) submitError.value = '' })
const dirty = computed(() => { try { return JSON.stringify(validateParams(single.params)) !== JSON.stringify(spectrum.value.params) || JSON.stringify(validateComposition(single.composition)) !== JSON.stringify(spectrum.value.composition) } catch { return true } })
function run() {
  try { const params = validateParams(single.params), comp = validateComposition(single.composition); submitError.value = ''; runDemo('single', `${comp.map(e => e.symbol).join(' / ')} · Te ${format(params.te)} eV · R ${params.resolution}`, () => generateSpectrum(params, comp, `single-demo-${Date.now()}`)) }
  catch (e) { submitError.value = e instanceof Error ? e.message : '输入无效' }
}
</script>
<template><WorkbenchLayout kind="single">
  <template #controls="{ disabled }"><ParameterEditor v-model="single.params" scope="single" cards :disabled="disabled" /><div class="divider" /><CompositionEditor v-model="single.composition" scope="single" :disabled="disabled" @issue="compositionError = $event" /><button class="btn primary full" :disabled="!!running || !!inputError" @click="run"><AppIcon name="play" :size="16" />{{ single.result ? '重新生成' : '生成示意图' }}</button></template>
  <div v-if="dirty" class="draft-notice"><span>草稿已更改</span>运行后更新图谱。</div><SpectrumChart :spectrum="spectrum" :label="single.result ? '示意结果' : '初始示意图'" /><div class="metrics-row spectrum-metrics"><div class="panel metric"><span>实验参数</span><dl class="summary-parameters"><div><dt>Te / eV</dt><dd>{{ format(spectrum.params.te) }}</dd></div><div><dt>Ne / cm⁻³</dt><dd>{{ format(spectrum.params.ne) }}</dd></div><div><dt>R</dt><dd>{{ spectrum.params.resolution }}</dd></div></dl></div><div class="panel metric"><span>波长窗口</span><strong>{{ format(spectrum.params.low) }}–{{ format(spectrum.params.high) }} <small>nm</small></strong></div><div class="panel metric"><span>组成元素</span><div class="summary-elements"><span v-for="element in spectrum.composition" :key="element.symbol" class="element-tile" :title="`${element.symbol} ${format(element.pct)}%`" :style="{ '--el-color': elementColor(element.symbol) }">{{ element.symbol }}</span></div></div></div>
    <TaskActivity kind="single" idle-title="初始示意图" :error="inputError || compositionError || submitError"><div class="backend-action"><button class="btn sm" disabled>打开真实结果目录</button><span class="hint">连接引擎后可用</span></div></TaskActivity>
</WorkbenchLayout></template>
