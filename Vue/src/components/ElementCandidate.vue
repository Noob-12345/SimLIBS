<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
const model = defineModel<string>({ required: true })
const props = defineProps<{ id: string; symbols: readonly string[]; disabled?: boolean }>()
const root = ref<HTMLElement>(), input = ref<HTMLInputElement>(), items = ref<HTMLButtonElement[]>([])
const open = ref(false), above = ref(false), active = ref(-1), menuHeight = ref(180)
const candidates = computed(() => props.symbols.filter(symbol => symbol.toLowerCase().startsWith(model.value.trim().toLowerCase())))
function close() { open.value = false; active.value = -1 }
function show() {
  if (props.disabled || !candidates.value.length) return
  const rect = input.value?.getBoundingClientRect(), height = Math.min(180, candidates.value.length * 30 + 8)
  const clip = root.value?.closest('.single-controls-wrap')?.getBoundingClientRect()
  if (rect) {
    const below = Math.min(window.innerHeight, clip?.bottom ?? window.innerHeight) - rect.bottom
    const upper = rect.top - Math.max(0, clip?.top ?? 0)
    above.value = below < height + 5 && upper > below
    menuHeight.value = Math.max(30, Math.min(180, (above.value ? upper : below) - 5))
  }
  open.value = true
}
function choose(symbol: string) { if (props.disabled) return; model.value = symbol; input.value?.focus({ preventScroll: true }); close() }
async function typed() { active.value = -1; await nextTick(); if (candidates.value.length) show(); else close() }
async function key(event: KeyboardEvent) {
  if (props.disabled || event.isComposing) return
  if (event.key === 'Escape') { event.preventDefault(); close(); return }
  if (event.key === 'Enter') { event.preventDefault(); if (open.value && active.value >= 0) choose(candidates.value[active.value]!); return }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
  event.preventDefault(); show(); if (!open.value) return
  active.value = event.key === 'ArrowDown' ? (active.value + 1) % candidates.value.length : (active.value < 0 ? candidates.value.length : active.value) - 1
  await nextTick(); items.value[active.value]?.scrollIntoView({ block: 'nearest' })
}
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) close() }
function focusOut(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) close() }
watch(() => props.disabled, value => { if (value) close() })
watch(candidates, value => { if (!value.length) close(); else if (active.value >= value.length) active.value = value.length - 1 })
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
</script>
<template>
  <div ref="root" class="element-candidate" @focusout="focusOut">
    <label class="sr-only" :for="id">添加元素符号</label>
    <input :id="id" ref="input" v-model="model" type="text" role="combobox" aria-autocomplete="list" :aria-expanded="open" :aria-controls="`${id}-candidates`" :aria-activedescendant="open && active >= 0 ? `${id}-candidate-${candidates[active]}` : undefined" placeholder="元素符号，如 Al" autocomplete="off" :disabled="disabled" @input="typed" @focus="show" @keydown="key" />
    <div v-if="open" :id="`${id}-candidates`" :class="['element-candidates', { above }]" :style="{ maxHeight: menuHeight + 'px' }" role="listbox" aria-label="可添加元素">
      <button v-for="(symbol, index) in candidates" :id="`${id}-candidate-${symbol}`" :key="symbol" :ref="element => items[index] = element as HTMLButtonElement" type="button" role="option" :aria-selected="index === active" :class="{ selected: index === active }" tabindex="-1" @mousedown.prevent @click="choose(symbol)">{{ symbol }}</button>
    </div>
  </div>
</template>
