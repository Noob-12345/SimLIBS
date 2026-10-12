<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { tasks } from '../lib/workbench'
import type { TaskKind } from '../lib/model'
const props = defineProps<{ kind: TaskKind }>()
const latest = computed(() => tasks.find(task => task.kind === props.kind))
const running = computed(() => tasks.some(task => task.kind === props.kind && task.status === 'running'))
const collapsed = ref(latest.value?.status === 'completed' && latest.value.progress === 100)
const controls = ref<HTMLElement>(), reveal = ref<HTMLButtonElement>()
const workbench = ref<HTMLElement>(), wrap = ref<HTMLElement>(), edgeHover = ref(false)
const edgePosition = ref({ left: 0, top: 0, height: 96, stripTop: 0, stripHeight: 0, visible: false })
let observer: ResizeObserver | undefined, frame = 0
function positionEdge() {
  const area = workbench.value?.getBoundingClientRect(), panel = wrap.value?.getBoundingClientRect()
  if (!area || !panel) return
  const top = Math.max(8, area.top), bottom = Math.min(window.innerHeight - 8, area.bottom)
  const height = Math.min(96, bottom - top)
  if (height < 32) { edgePosition.value.visible = false; return }
  const center = Math.max(top + height / 2, Math.min(window.innerHeight / 2, bottom - height / 2))
  const expandedWidth = controls.value?.getBoundingClientRect().width ?? panel.width
  const fraction = expandedWidth > 22 ? Math.max(0, Math.min(1, (panel.width - 22) / (expandedWidth - 22))) : 0
  const left = panel.right - 22 + 11 * fraction
  edgePosition.value = { left: Math.max(0, Math.min(window.innerWidth - 22, left)), top: center - height / 2, height, stripTop: top, stripHeight: bottom - top, visible: true }
}
function schedulePosition() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; positionEdge() }) }
watch(collapsed, async () => { await nextTick(); schedulePosition() })
onMounted(() => {
  observer = new ResizeObserver(positionEdge)
  if (workbench.value) observer.observe(workbench.value)
  if (wrap.value) observer.observe(wrap.value)
  window.addEventListener('scroll', schedulePosition, true); window.addEventListener('resize', schedulePosition); schedulePosition()
})
onUnmounted(() => { observer?.disconnect(); window.removeEventListener('scroll', schedulePosition, true); window.removeEventListener('resize', schedulePosition); if (frame) cancelAnimationFrame(frame) })
const label = computed(() => ({ single: '单次', batch: '批量', scan: '扫描' })[props.kind])
const disabled = computed(() => collapsed.value || running.value)
async function collapseControls(restoreFocus = false) {
  collapsed.value = true
  await nextTick(); if (restoreFocus) reveal.value?.focus({ preventScroll: true })
}
watch(() => latest.value?.status === 'completed' && latest.value.progress === 100 ? latest.value.id : null, id => {
  if (id) void collapseControls(!!controls.value?.contains(document.activeElement))
})
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
    <div class="result-column"><slot /></div>
    <Teleport to="body">
      <div v-show="edgePosition.visible" class="workbench-edge-zone" :style="{ left: edgePosition.left + 'px', top: edgePosition.stripTop + 'px', height: edgePosition.stripHeight + 'px' }" aria-hidden="true" @pointerenter="edgeHover = true" @pointerleave="edgeHover = false" />
      <button v-show="edgePosition.visible" ref="reveal" type="button" :class="['workbench-edge', { 'edge-hover': edgeHover }, collapsed ? 'single-reveal' : 'single-collapse']" :style="{ left: edgePosition.left + 'px', top: edgePosition.top + 'px', height: edgePosition.height + 'px' }" :aria-label="`${collapsed ? '展开' : '收起'}${label}参数`" :title="`${collapsed ? '展开' : '收起'}参数`" :aria-controls="`${kind}-controls`" :aria-expanded="!collapsed" @click="collapsed ? expandControls() : collapseControls(true)"><AppIcon name="chevron" :size="14" /></button>
    </Teleport>
  </div>
</template>
