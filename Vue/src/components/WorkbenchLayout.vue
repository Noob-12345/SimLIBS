<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { tasks } from '../lib/workbench'
import type { TaskKind } from '../lib/model'
const props = defineProps<{ kind: TaskKind }>()
const latest = computed(() => tasks.find(task => task.kind === props.kind))
const running = computed(() => tasks.some(task => task.kind === props.kind && task.status === 'running'))
const collapsed = ref(latest.value?.status === 'completed' && latest.value.progress === 100)
const controls = ref<HTMLElement>(), reveal = ref<HTMLButtonElement>()
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
  const first = controls.value?.querySelector<HTMLElement>('input[type=text]:not(:disabled)') ?? controls.value?.querySelector<HTMLElement>('button:not(:disabled)')
  first?.focus({ preventScroll: true })
}
</script>
<template>
  <div :class="['workbench-grid', 'single-workbench', { 'controls-collapsed': collapsed }]" :data-workbench="kind">
    <div class="single-controls-wrap">
      <section :id="`${kind}-controls`" ref="controls" class="panel parameter-panel single-parameter-panel" :inert="collapsed" :aria-hidden="collapsed">
        <div class="single-controls-toolbar"><button type="button" class="btn sm single-collapse" :aria-label="`收起${label}参数`" title="收起参数" :aria-controls="`${kind}-controls`" :aria-expanded="!collapsed" @click="collapseControls(true)"><AppIcon name="chevron" :size="12" />收起参数</button></div>
        <fieldset class="control-fieldset workbench-controls-fields" :disabled="disabled"><slot name="controls" :disabled="disabled" /></fieldset>
      </section>
      <button v-if="collapsed" ref="reveal" class="single-reveal" type="button" :aria-label="`展开${label}参数`" title="展开参数" :aria-controls="`${kind}-controls`" :aria-expanded="!collapsed" @click="expandControls"><AppIcon name="chevron" :size="14" /></button>
    </div>
    <div class="result-column"><slot /></div>
  </div>
</template>
