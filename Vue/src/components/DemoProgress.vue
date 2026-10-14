<script setup lang="ts">
import { statusLabels, type DemoTask } from '../lib/model'
import { cancelTask } from '../lib/workbench'
defineProps<{ task?: DemoTask }>()
</script>
<template><Transition name="expand"><div v-if="task" :class="['demo-progress', 'progress-' + task.status]"><div><span role="status">{{ statusLabels[task.status] }}</span><b class="mono">{{ task.progress }}%</b></div><div class="progress-track" role="progressbar" aria-label="真实计算进度" :aria-valuenow="task.progress" :aria-valuemin="0" :aria-valuemax="100"><span :style="{ width: task.progress + '%' }" /></div><div v-if="task.status === 'running'" class="progress-caption"><button class="btn sm danger" @click="cancelTask(task)">取消任务</button></div></div></Transition></template>
