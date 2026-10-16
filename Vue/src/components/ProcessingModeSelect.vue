<script setup lang="ts">
import ChoiceSelect from './ChoiceSelect.vue'
import type { Mode } from '../lib/model'
const model = defineModel<Mode>({ required: true })
defineProps<{ disabled?: boolean }>()
const options: { value: Mode; label: string; description: string }[] = [
  { value: 'local', label: '本地', description: '通过本地谱线库模拟' },
  { value: 'server', label: '服务器', description: '由 NIST LIBS 在线服务生成光谱并进行展宽' },
  { value: 'client', label: '客户端', description: '在线获取 NIST 谱线跃迁与强度，由本地引擎进行线型展宽' }
]
</script>
<template><ChoiceSelect v-model="model" label="处理方式" :options="options" :disabled="disabled" /></template>
