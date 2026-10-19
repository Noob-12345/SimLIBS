<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import SpectrumStage from './SpectrumStage.vue'
import { starting, tasks } from '../lib/workbench'
import type { TaskKind } from '../lib/model'
const props = defineProps<{ kind: TaskKind }>()
const running = computed(() => tasks.some(task => task.kind === props.kind && task.status === 'running'))
const collapsed = ref(false)
const controls = ref<HTMLElement>(), reveal = ref<HTMLButtonElement>()
const workbench = ref<HTMLElement>(), wrap = ref<HTMLElement>(), pointerActive = ref(false), edgeHovered = ref(false)
const edgePosition = ref({ left: 0, top: 0, height: 220, visible: false })
let observer: ResizeObserver | undefined, frame = 0, activityTimer: ReturnType<typeof setTimeout> | undefined
function showEdge() {
  pointerActive.value = true; clearTimeout(activityTimer)
  activityTimer = setTimeout(() => { pointerActive.value = false }, 600)
}
function touchActivity(event: PointerEvent) { if (event.pointerType === 'touch') showEdge() }
function enterEdge(event: PointerEvent) { edgeHovered.value = event.pointerType !== 'touch'; showEdge() }
function leaveEdge() { edgeHovered.value = false; showEdge() }
function positionEdge() {
  const area = workbench.value?.getBoundingClientRect(), panel = wrap.value?.getBoundingClientRect()
  if (!area || !panel) return
  const top = Math.max(8, area.top), bottom = Math.min(window.innerHeight - 8, area.bottom)
  const height = Math.min(220, bottom - top)
  if (height < 32) { edgePosition.value.visible = false; return }
  const center = Math.max(top + height / 2, Math.min(window.innerHeight / 2, bottom - height / 2))
  const gap = parseFloat(getComputedStyle(workbench.value!).columnGap) || 0
  const left = collapsed.value ? area.left - 22 : panel.right + Math.max(0, (gap - 22) / 2)
  const workspaceLeft = workbench.value?.closest('.workspace')?.getBoundingClientRect().left ?? 0
  edgePosition.value = { left: Math.max(4, workspaceLeft, Math.min(document.documentElement.clientWidth - 26, left)), top: center - height / 2, height, visible: true }
}
function schedulePosition() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; positionEdge() }) }
watch(collapsed, async () => { await nextTick(); schedulePosition() })
onMounted(() => {
  observer = new ResizeObserver(positionEdge)
  if (workbench.value) observer.observe(workbench.value)
  if (wrap.value) observer.observe(wrap.value)
  window.addEventListener('scroll', schedulePosition, true); window.addEventListener('resize', schedulePosition)
  window.addEventListener('pointermove', showEdge, { passive: true, capture: true }); window.addEventListener('pointerdown', touchActivity, { passive: true, capture: true }); schedulePosition()
})
onUnmounted(() => { observer?.disconnect(); window.removeEventListener('scroll', schedulePosition, true); window.removeEventListener('resize', schedulePosition); window.removeEventListener('pointermove', showEdge, true); window.removeEventListener('pointerdown', touchActivity, true); clearTimeout(activityTimer); if (frame) cancelAnimationFrame(frame) })
const label = computed(() => ({ single: '单次', batch: '批量', scan: '扫描', advanced:'高级' })[props.kind])
const disabled = computed(() => collapsed.value || starting.has(props.kind) || running.value)
async function collapseControls(restoreFocus = false) {
  collapsed.value = true
  await nextTick(); if (restoreFocus) reveal.value?.focus({ preventScroll: true })
}
watch(() => starting.has(props.kind), submitting => {
  if (submitting) void collapseControls(!!controls.value?.contains(document.activeElement))
}, { flush: 'sync' })
async function expandControls() {
  collapsed.value = false; await nextTick()
  const fields = Array.from(controls.value?.querySelectorAll<HTMLElement>('input[type=text]:not(:disabled)') ?? [])
  const first = fields.find(field => { const rect = field.getBoundingClientRect(); return rect.top >= 0 && rect.bottom <= window.innerHeight }) ?? fields[0] ?? controls.value?.querySelector<HTMLElement>('button:not(:disabled)')
  first?.focus({ preventScroll: true })
}
</script>
<template>
  <div ref="workbench" :class="['workbench-grid', 'single-workbench', { 'controls-collapsed': collapsed }]" :data-workbench="kind">
    <div ref="wrap" class="single-controls-wrap">
      <section :id="`${kind}-controls`" ref="controls" class="panel parameter-panel single-parameter-panel" :inert="collapsed" :aria-hidden="collapsed">
        <fieldset class="control-fieldset workbench-controls-fields" :disabled="disabled"><slot name="controls" :disabled="disabled" /></fieldset>
      </section>
    </div>
    <SpectrumStage><div class="result-column"><slot name="spectrum" /><slot /></div></SpectrumStage>
    <Teleport to="body">
      <button v-show="edgePosition.visible" ref="reveal" type="button" :class="['workbench-edge', { 'edge-active': pointerActive, 'edge-hover': edgeHovered }, collapsed ? 'single-reveal' : 'single-collapse']" :style="{ left: edgePosition.left + 'px', top: edgePosition.top + 'px', height: edgePosition.height + 'px' }" :aria-label="`${collapsed ? '展开' : '收起'}${label}参数`" :title="`${collapsed ? '展开' : '收起'}参数`" :aria-controls="`${kind}-controls`" :aria-expanded="!collapsed" @pointerenter="enterEdge" @pointerleave="leaveEdge" @click="collapsed ? expandControls() : collapseControls(true)"><AppIcon name="chevron" :size="18" /></button>
    </Teleport>
  </div>
</template>
