<script setup lang="ts">
import ChoiceSelect from './ChoiceSelect.vue'
import type { Mode } from '../lib/model'
const model = defineModel<Mode>({ required: true })
defineProps<{ disabled?: boolean }>()
const options: { value: Mode; label: string; description: string }[] = [
  { value: 'local', label: '本地', description: '固定光子通量，可选本地展宽与重粒子温度配置。' },
  { value: 'server', label: '服务器', description: '可选光子或能量通量，提供后台抓取配置。' },
  { value: 'client', label: '客户端', description: '可选强度尺度，配置高斯约定、线中心舍入与选线阈值。' }
]
</script>
<template><ChoiceSelect v-model="model" label="处理方式" :options="options" :disabled="disabled" /></template>