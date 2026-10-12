<script setup lang="ts" generic="T extends string">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
const model = defineModel<T>({ required: true })
const props = defineProps<{ label: string; options: readonly { value: T; label: string; description?: string }[]; disabled?: boolean; issue?: string; issueId?: string }>()
const selected = computed(() => props.options.find(option => option.value === model.value) ?? props.options[0]!)
const open = ref(false), above = ref(false), activeIndex = ref(0), helpIndex = ref<number | null>(null)
const root = ref<HTMLElement>(), trigger = ref<HTMLButtonElement>(), items = ref<HTMLButtonElement[]>([])
const helpButtons = ref<HTMLButtonElement[]>([]), hoveredHelp = ref<number | null>(null)
const id = `choice-${useId()}`
function setItem(element: unknown, index: number) { items.value[index] = element as HTMLButtonElement }
function setHelp(element: unknown, index: number) { helpButtons.value[index] = element as HTMLButtonElement }
async function show(index = props.options.findIndex(option => option.value === model.value)) {
  if (props.disabled || !props.options.length) return
  const rect = trigger.value?.getBoundingClientRect()
  above.value = !!rect && window.innerHeight - rect.bottom < props.options.length * 34 + 17 + (props.options.some(option => option.description) ? 80 : 0) && rect.top > window.innerHeight - rect.bottom
  activeIndex.value = Math.max(0, index); open.value = true; await nextTick(); items.value[activeIndex.value]?.focus()
}
async function close(restoreFocus = false) {
  open.value = false; helpIndex.value = null; hoveredHelp.value = null
  if (restoreFocus) { await nextTick(); trigger.value?.focus() }
}
function toggle() { if (open.value) void close(); else void show() }
function choose(index: number) { if (props.disabled || !props.options.length) return; model.value = props.options[index]!.value; void close(true) }
function enterHelp(index: number) { if (!props.disabled) { hoveredHelp.value = index; helpIndex.value = index } }
function leaveHelp(index: number) {
  hoveredHelp.value = null
  if (document.activeElement !== helpButtons.value[index]) helpIndex.value = null
}
function blurHelp() { helpIndex.value = hoveredHelp.value }
function triggerKey(event: KeyboardEvent) {
  if (props.disabled || !props.options.length) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); void show(event.key === 'ArrowUp' ? props.options.length - 1 : 0) }
  else if (event.key === 'Escape') { event.preventDefault(); void close(true) }
}
function menuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); void close(true); return }
  if (props.disabled || !open.value) return
  // Enter/Space on the separate information button must never select a mode.
  if (event.key === 'Enter' || event.key === ' ') {
    if (event.target === items.value[activeIndex.value]) { event.preventDefault(); choose(activeIndex.value) }
    return
  }
  let next = activeIndex.value
  if (event.key === 'ArrowDown') next = (next + 1) % props.options.length
  else if (event.key === 'ArrowUp') next = (next + props.options.length - 1) % props.options.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = props.options.length - 1
  else return
  event.preventDefault(); activeIndex.value = next; void nextTick(() => items.value[next]?.focus())
}
function outside(event: PointerEvent) { if (open.value && !root.value?.contains(event.target as Node)) void close() }
function focusOut(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) void close() }
watch(() => props.disabled, value => { if (value) void close() })
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
</script>
<template>
  <div ref="root" class="mode-select field" @focusout="focusOut">
    <label :id="`${id}-label`" :for="`${id}-trigger`">{{ label }}</label>
    <button :id="`${id}-trigger`" ref="trigger" class="mode-select-trigger" type="button" :disabled="disabled" :aria-invalid="!!issue" :aria-describedby="issue ? issueId : undefined" :data-issue="issue || undefined" aria-haspopup="menu" :aria-expanded="open" :aria-controls="`${id}-menu`" :aria-labelledby="`${id}-label ${id}-value`" @click="toggle" @keydown="triggerKey"><span :id="`${id}-value`">{{ selected.label }}</span><AppIcon name="chevron" :size="14" /></button>
    <Transition name="popover">
      <div v-if="open" :id="`${id}-menu`" :class="['mode-select-menu', { above }]" role="menu" :aria-label="label" @keydown="menuKey">
        <div v-for="(option, index) in props.options" :key="option.value" :class="['mode-choice-row', { 'plain-choice-row': !option.description }]" role="none">
          <button :ref="element => setItem(element, index)" class="mode-choice" type="button" role="menuitemradio" :disabled="disabled" :aria-checked="model === option.value" :tabindex="activeIndex === index ? 0 : -1" :class="{ selected: model === option.value }" @focus="activeIndex = index" @click="choose(index)"><span>{{ option.label }}</span><AppIcon v-if="model === option.value" name="check" :size="14" /></button>
          <button v-if="option.description" :ref="element => setHelp(element, index)" class="mode-help" type="button" role="menuitem" :disabled="disabled" :aria-label="`${option.label}配置说明`" :aria-describedby="helpIndex === index ? `${id}-help-${index}` : undefined" @pointerenter="enterHelp(index)" @pointerleave="leaveHelp(index)" @focus="helpIndex = index; activeIndex = index" @blur="blurHelp" @click.stop="helpIndex = index"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 17h.01" /></svg></button>
          <p v-if="helpIndex === index" :id="`${id}-help-${index}`" class="mode-help-text" role="tooltip">{{ option.description }}</p>
        </div>
      </div>
    </Transition>
  </div>
</template>
