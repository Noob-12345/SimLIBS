<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { balance, canonical, elementColor, elementDraft, errorOf, symbols, validateComposition, type ElementDraft } from '../lib/model'
const model = defineModel<ElementDraft[]>({ required: true })
const props = defineProps<{ scope: string; random?: boolean; disabled?: boolean }>()
const adding = ref(''), addError = ref('')
const total = computed(() => model.value.reduce((sum, e) => sum + (e.pct.trim() ? Number(e.pct) : NaN), 0))
const error = computed(() => props.random ? '' : errorOf(() => validateComposition(model.value)))
watch(() => [props.random, ...model.value.slice(0, -1).map(e => e.pct), model.value.length], () => { if (!props.random) balance(model.value) })
function add() {
  const symbol = canonical(adding.value)
  if (!symbol) { addError.value = '请输入有效元素符号，例如 Fe、Al、Cu'; return }
  if (model.value.some(e => canonical(e.symbol) === symbol)) { addError.value = `${symbol} 已在组成中`; return }
  if (model.value.length >= 32) { addError.value = '最多支持 32 个元素'; return }
  model.value.push(elementDraft(symbol, '0')); if (!props.random) balance(model.value)
  adding.value = ''; addError.value = ''
}
function remove(id: number) { if (model.value.length <= 1) return; model.value.splice(model.value.findIndex(e => e.id === id), 1); if (!props.random) balance(model.value) }
</script>
<template>
  <fieldset class="control-fieldset composition-editor" :disabled="disabled">
    <div class="panel-heading"><h2>元素组成</h2><span class="section-number">02</span></div><p v-if="random" class="hint">设置浓度或随机范围</p>
    <div v-if="!random" class="composition-bar"><span v-for="e in model" :key="e.id" :style="{ width: `${Math.max(0, Math.min(100, Number(e.pct) || 0))}%`, background: elementColor(e.symbol) }" /></div>
    <TransitionGroup name="element" tag="div" class="composition-rows">
      <div v-for="(e, i) in model" :key="e.id" class="composition-entry">
        <div class="composition-row"><span class="element-tile" :style="{ '--el-color': elementColor(e.symbol) }">{{ e.symbol }}</span><label class="pct-field"><span class="sr-only">{{ e.symbol }} 占比（%）</span><input v-model="e.pct" type="text" inputmode="decimal" :readonly="!random && i === model.length - 1" :disabled="random && e.random" :aria-label="`${e.symbol} 占比（%）`" /><span>%</span></label><button class="icon-btn remove-btn" type="button" :disabled="model.length === 1" :aria-label="`删除元素 ${e.symbol}`" @click="remove(e.id)"><AppIcon name="close" :size="14" /></button></div>
        <label v-if="random" class="switch small-switch"><input v-model="e.random" type="checkbox" /><span class="switch-track" />{{ e.symbol }} 浓度随机</label>
        <div v-if="random && e.random" class="row2"><label class="field compact">下界 / %<input v-model="e.min" type="text" inputmode="decimal" /></label><label class="field compact">上界 / %<input v-model="e.max" type="text" inputmode="decimal" /></label></div>
      </div>
    </TransitionGroup>
    <div v-if="!random" :class="['sum-row', { invalid: !!error }]"><span>总占比</span><b class="mono">{{ Number.isFinite(total) ? `${Number(total.toFixed(5))}%` : '无效' }} {{ error ? '!' : '✓' }}</b></div>
    <div class="add-element"><label class="sr-only" :for="`${scope}-add-element`">添加元素符号</label><input :id="`${scope}-add-element`" v-model="adding" type="text" :list="`${scope}-element-symbols`" placeholder="元素符号，如 Al" autocomplete="off" :disabled="model.length >= 32" @keydown.enter.prevent="add" @keydown.esc="adding = ''; addError = ''" /><datalist :id="`${scope}-element-symbols`"><option v-for="symbol in symbols.filter(s => !model.some(e => e.symbol === s))" :key="symbol" :value="symbol" /></datalist><button type="button" class="btn sm" :disabled="model.length >= 32" @click="add"><AppIcon name="plus" :size="13" />添加</button></div>
    <p v-if="addError || error" class="error-text" role="alert">{{ addError || error }}</p><p class="hint">{{ model.length }} / 32 个元素 · 原子百分比</p>
  </fieldset>
</template>
