<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { statusLabels, type DemoTask } from '../lib/model'
import { cancelTask } from '../lib/workbench'
const props = defineProps<{ task?: DemoTask }>()
const pulsing = ref(false), celebrated = new Set<string>()
let timer: ReturnType<typeof setTimeout> | undefined
const statusText = computed(() => {
  if (!props.task) return ''
  if (props.task.status === 'running') {
    return props.task.stage || '运行中'
  }
  return statusLabels[props.task.status]
})
watch(() => [props.task?.id, props.task?.status] as const, ([id, status], previous) => {
  clearTimeout(timer); pulsing.value = false
  if (id && status === 'completed' && previous?.[0] === id && previous[1] === 'running' && !celebrated.has(id)) {
    celebrated.add(id); pulsing.value = true; timer = setTimeout(() => { pulsing.value = false }, 360)
  }
})
onUnmounted(() => clearTimeout(timer))
</script>
<template><Transition name="expand"><div v-if="task" :class="['demo-progress', 'progress-' + task.status, { 'progress-celebrate': pulsing }]"><div><span role="status">{{ statusText }}</span><b class="mono">{{ task.progress }}%</b></div><div class="progress-track" role="progressbar" aria-label="计算进度" :aria-valuenow="task.progress" :aria-valuemin="0" :aria-valuemax="100"><span :style="{ width: task.progress + '%' }" /></div><div v-if="task.status === 'running'" class="progress-caption"><button class="btn sm danger" @click="cancelTask(task)">取消任务</button></div></div></Transition></template>
