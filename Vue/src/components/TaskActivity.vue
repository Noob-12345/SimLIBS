<script setup lang="ts">
import { computed } from 'vue'
import DemoProgress from './DemoProgress.vue'
import { kindLabels, statusLabels, type TaskKind } from '../lib/model'
import { tasks, retryTask } from '../lib/workbench'
const props = defineProps<{ kind: TaskKind; idleTitle?: string; error?: string }>()
const latest = computed(() => tasks.find(task => task.kind === props.kind))
const detail = computed(() => latest.value ? latest.value.detail : '生成后显示任务记录。')
const badgeText = computed(() => {
  if (!latest.value) return '准备就绪'
  if (latest.value.status === 'running') {
    return latest.value.stage || '运行中'
  }
  return statusLabels[latest.value.status]
})
</script>
<template><section class="panel activity-panel"><div class="panel-heading"><h2>工作台活动</h2><span :class="['badge', latest ? 'task-' + latest.status : 'neutral']">{{ badgeText }}</span></div><p v-if="error" :id="`${kind}-draft-error`" class="error-text draft-error" role="alert">{{ error }}</p><p v-if="latest?.resultError" class="error-text" role="alert">{{ latest.resultError }} <button class="btn sm" @click="retryTask(latest)">重试读取任务</button></p><DemoProgress :task="latest" /><div class="activity-line"><i /><div><strong>{{ latest ? latest.summary : idleTitle || `${kindLabels[kind]}未生成` }}</strong><p v-if="detail">{{ detail }}</p></div><span class="mono muted">任务记录</span></div><slot /></section></template>
