<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import ElementCandidate from './ElementCandidate.vue'
import { service } from '../lib/backend'
import { single, batch, scan } from '../lib/workbench'
import { compositionIssues, issueAttrs } from '../lib/issues'
import { balance, canonical, elementColor, elementDraft, errorOf, symbols, validateComposition, type ElementDraft } from '../lib/model'
const model = defineModel<ElementDraft[]>({ required: true })
const props = defineProps<{ scope: string; random?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ issue: [message: string] }>()
const adding = ref(''), addError = ref('')
const mode = computed(() => (props.scope === 'single' ? single : props.scope === 'batch' ? batch : scan).params.mode)
const supportedSymbols = computed(() => mode.value === 'local' ? service.capabilities?.elements ?? [] : symbols)
const localError = computed(() => {
  if (mode.value !== 'local') return ''
  if (!service.capabilities?.ready) return service.capabilities?.error || '本地谱线能力尚未就绪'
  const missing = model.value.filter(e => (props.random && e.random ? Number(e.max) > 0 : Number(e.pct) > 0) && !supportedSymbols.value.includes(canonical(e.symbol)))
  return missing.length ? `本地库不支持：${missing.map(e => e.symbol).join('、')}` : ''
})
const availableSymbols = computed(() => supportedSymbols.value.filter(symbol => !model.value.some(element => canonical(element.symbol) === symbol)))
const total = computed(() => model.value.reduce((sum, e) => sum + (e.pct.trim() ? Number(e.pct) : NaN), 0))
const error = computed(() => props.random ? '' : errorOf(() => validateComposition(model.value)))
const issues = computed(() => compositionIssues(model.value, props.random))
const attrs = (key: string) => issueAttrs(issues.value[key], `${props.scope}-draft-error`)
watch([addError, error, issues, localError], () => emit('issue', addError.value || localError.value || error.value || Object.values(issues.value)[0] || ''), { immediate: true })
watch(mode, () => { addError.value = '' })
watch(adding, value => { const symbol = canonical(value); if (symbol && !model.value.some(row => canonical(row.symbol) === symbol) && model.value.length < 32) addError.value = '' })
watch(() => [props.random, ...model.value.slice(0, -1).map(e => e.pct), model.value.length], () => { if (!props.random) balance(model.value) })
function add() {
  const symbol = canonical(adding.value)
  if (!symbol) { addError.value = '请输入有效元素符号，例如 Fe、Al、Cu'; return }
  if (!supportedSymbols.value.includes(symbol)) { addError.value = mode.value === 'local' ? `本地库不支持 ${symbol}` : '无效元素'; return }
  if (model.value.some(e => canonical(e.symbol) === symbol)) { addError.value = `${symbol} 已在组成中`; return }
  if (model.value.length >= 32) { addError.value = '最多支持 32 个元素'; return }
  model.value.push(elementDraft(symbol, '0')); if (!props.random) balance(model.value)
  adding.value = ''; addError.value = ''
}
function remove(id: number) { if (model.value.length <= 1) return; model.value.splice(model.value.findIndex(e => e.id === id), 1); if (!props.random) balance(model.value) }
</script>
<template>
  <fieldset class="control-fieldset composition-editor" :disabled="disabled">
    <div class="panel-heading"><h2>元素组成</h2><span class="section-number">02</span></div>
    <div v-if="!random" class="composition-bar"><span v-for="e in model" :key="e.id" :style="{ width: `${Math.max(0, Math.min(100, Number(e.pct) || 0))}%`, background: elementColor(e.symbol) }" /></div>
    <TransitionGroup name="element" tag="div" class="composition-rows">
      <div v-for="(e, i) in model" :key="e.id" class="composition-entry">
        <div class="composition-row"><span class="element-tile" :style="{ '--el-color': elementColor(e.symbol) }">{{ e.symbol }}</span><label class="pct-field"><span class="sr-only">{{ e.symbol }} 占比（%）</span><input :id="`${scope}-pct-${e.id}`" v-model="e.pct" type="text" inputmode="decimal" :readonly="!random && i === model.length - 1" :disabled="random && e.random" :aria-label="`${e.symbol} 占比（%）`" v-bind="attrs(`${e.id}.pct`)" /><span>%</span></label><button class="icon-btn remove-btn" type="button" :disabled="model.length === 1" :aria-label="`删除元素 ${e.symbol}`" @click="remove(e.id)"><AppIcon name="close" :size="14" /></button></div>
        <label v-if="random" class="switch small-switch"><input v-model="e.random" type="checkbox" /><span class="switch-track" />{{ e.symbol }} 浓度随机</label>
        <div v-if="random && e.random" class="row2"><label class="field compact">下界 / %<input :id="`${scope}-min-${e.id}`" v-model="e.min" type="text" inputmode="decimal" v-bind="attrs(`${e.id}.min`)" /></label><label class="field compact">上界 / %<input :id="`${scope}-max-${e.id}`" v-model="e.max" type="text" inputmode="decimal" v-bind="attrs(`${e.id}.max`)" /></label></div>
      </div>
    </TransitionGroup>
    <div v-if="!random" :class="['sum-row', { invalid: !!error }]"><span>总占比</span><b class="mono">{{ Number.isFinite(total) ? `${Number(total.toFixed(5))}%` : '无效' }} {{ error ? '!' : '✓' }}</b></div>
    <div class="add-element"><ElementCandidate :id="`${scope}-add-element`" v-model="adding" :symbols="availableSymbols" :disabled="disabled || model.length >= 32" :issue="addError" :issue-id="`${scope}-draft-error`" /><button type="button" class="btn sm" :disabled="model.length >= 32" @click="add"><AppIcon name="plus" :size="13" />添加</button></div>
  </fieldset>
</template>
