<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
const stage = ref<HTMLElement>(), availableHeight = ref(0)
let observer: ResizeObserver | undefined, workspace: HTMLElement | null = null, frame = 0, active = false
function measure() {
  if (!stage.value) return
  const owner = stage.value.closest<HTMLElement>('.workspace') ?? stage.value.parentElement
  const bottom = owner ? parseFloat(getComputedStyle(owner).paddingBottom) || 0 : 0
  const documentTop = stage.value.getBoundingClientRect().top + window.scrollY
  const viewportHeight = window.visualViewport?.height ?? window.innerHeight
  availableHeight.value = Math.max(0, Math.floor(viewportHeight - documentTop - bottom))
}
function scheduleMeasure() {
  if (active && !frame) frame = requestAnimationFrame(() => { frame = 0; measure() })
}
onMounted(() => {
  active = true
  workspace = stage.value?.closest<HTMLElement>('.workspace') ?? null
  observer = new ResizeObserver(scheduleMeasure)
  for (const element of new Set([stage.value, workspace, stage.value?.closest<HTMLElement>('.workbench-grid')])) if (element) observer.observe(element)
  window.addEventListener('resize', scheduleMeasure)
  window.visualViewport?.addEventListener('resize', scheduleMeasure)
  workspace?.addEventListener('transitionend', scheduleMeasure)
  void document.fonts?.ready.then(scheduleMeasure)
  scheduleMeasure()
})
onUnmounted(() => {
  active = false; observer?.disconnect()
  window.removeEventListener('resize', scheduleMeasure)
  window.visualViewport?.removeEventListener('resize', scheduleMeasure)
  workspace?.removeEventListener('transitionend', scheduleMeasure)
  if (frame) cancelAnimationFrame(frame)
})
</script>
<template><div ref="stage" class="spectrum-stage" :style="{ '--spectrum-available-height': `${availableHeight}px` }"><div class="spectrum-stage-content"><slot /></div></div></template>
