<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
const model = defineModel<boolean>({ required: true })
const props = defineProps<{ label: string; description: string; disabled?: boolean }>()
const root = ref<HTMLElement>(), button = ref<HTMLButtonElement>(), tip = ref<HTMLElement>()
const open = ref(false), pinned = ref(false), hovered = ref(false)
const position = ref({ left: 12, top: 12 }), id = `switch-hint-${useId()}`
function place() {
  if (!open.value) return
  const anchor = button.value?.getBoundingClientRect(), box = tip.value?.getBoundingClientRect()
  if (!anchor || !box) return
  position.value = { left: Math.max(12, Math.min(window.innerWidth - box.width - 12, anchor.right - box.width)), top: Math.max(12, Math.min(window.innerHeight - box.height - 12, anchor.bottom + box.height + 6 <= window.innerHeight - 12 ? anchor.bottom + 6 : anchor.top - box.height - 6)) }
}
async function show() { if (props.disabled) return; open.value = true; await nextTick(); place() }
function leave() { hovered.value = false; if (!pinned.value && document.activeElement !== button.value) open.value = false }
function blur() { if (!hovered.value && !pinned.value) open.value = false }
function toggle() { if (props.disabled) return; pinned.value = !pinned.value; if (pinned.value) void show(); else open.value = hovered.value || document.activeElement === button.value }
function close() { pinned.value = false; hovered.value = false; open.value = false }
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) close() }
watch(() => props.disabled, value => { if (value) close() })
onMounted(() => { document.addEventListener('pointerdown', outside); window.addEventListener('scroll', place, true); window.addEventListener('resize', place) })
onUnmounted(() => { document.removeEventListener('pointerdown', outside); window.removeEventListener('scroll', place, true); window.removeEventListener('resize', place) })
</script>
<template>
  <div ref="root" class="switch-with-hint">
    <label class="switch"><input v-model="model" type="checkbox" :disabled="disabled" /><span class="switch-track" />{{ label }}</label>
    <button ref="button" type="button" class="switch-help" :disabled="disabled" :aria-label="`${label}配置说明`" :aria-describedby="open ? id : undefined" :aria-expanded="open" @pointerenter="hovered = true; show()" @pointerleave="leave" @focus="show" @blur="blur" @click.stop="toggle" @keydown.esc.prevent="close"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 17h.01" /></svg></button>
    <Teleport to="body"><p v-if="open" :id="id" ref="tip" class="switch-hint-tooltip" role="tooltip" :style="{ left: position.left + 'px', top: position.top + 'px' }">{{ description }}</p></Teleport>
  </div>
</template>
