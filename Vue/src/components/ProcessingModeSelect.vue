<script setup lang="ts">
import ChoiceSelect from './ChoiceSelect.vue'
import type { Mode } from '../lib/model'
const model = defineModel<Mode>({ required: true })
defineProps<{ disabled?: boolean }>()
const options: { value: Mode; label: string; description: string }[] = [
  { value: 'local', label: '本地', description: '通过本地谱线库模拟' },
  { value: 'server', label: '服务器', description: '从NIST服务器获取谱线、展宽和强度数据' },
  { value: 'client', label: '客户端', description: 'NIST计算谱线强度（dataSticksArray），由Python在本地展宽' }
]
</script>
<template><ChoiceSelect v-model="model" label="处理方式" :options="options" :disabled="disabled" /></template>
