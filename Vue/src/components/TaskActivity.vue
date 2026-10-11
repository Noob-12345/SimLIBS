<script setup lang="ts">
import { computed } from 'vue'
import DemoProgress from './DemoProgress.vue'
import { kindLabels, statusLabels, type TaskKind } from '../lib/model'
import { tasks } from '../lib/workbench'
const props = defineProps<{ kind: TaskKind; idleTitle?: string }>()
const latest = computed(() => tasks.find(task => task.kind === props.kind))
</script>
<template><section class="panel activity-panel"><div class="panel-heading"><h2>工作台活动</h2><span :class="['badge', latest ? 'task-' + latest.status : 'neutral']">{{ latest ? statusLabels[latest.status] : '准备就绪' }}</span></div><DemoProgress :task="latest" /><div class="activity-line"><i /><div><strong>{{ latest ? latest.summary : idleTitle || `${kindLabels[kind]}未生成` }}</strong><p>{{ latest ? latest.detail : '生成后显示任务记录。' }}</p></div><span class="mono muted">示意</span></div><slot /></section></template>
