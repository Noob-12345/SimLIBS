<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SpectrumChart from './SpectrumChart.vue'
import EmptyStateArt from './EmptyStateArt.vue'
import { advancedFlags, advancedResultLabel, isNistAdvanced } from '../lib/advanced'
import { download } from '../lib/backend'
import { format, type Spectrum } from '../lib/model'
import { useFileSave } from '../lib/fileAccess'
const props = defineProps<{ spectrum: Spectrum | null }>()
const origin = computed(() => props.spectrum?.source.origin)
const nist = computed(() => isNistAdvanced(origin.value?.model_version))
const flags = computed(() => advancedFlags(origin.value))
const viewMode = ref<'elements'|'comparison'>('elements')
const rows = computed(() => Array.isArray(origin.value?.line_diagnostics) ? origin.value.line_diagnostics as Record<string, unknown>[] : [])
const page = ref(0), pageSize = 10
watch(() => props.spectrum?.id, () => { page.value = 0; viewMode.value = 'elements' })
const visible = computed(() => rows.value.slice(page.value*pageSize, (page.value+1)*pageSize))
const { pending: saving, feedback, failed, run: saveOutput } = useFileSave()
const cell = (row: Record<string, unknown>, key: string) => typeof row[key] === 'number' ? format(row[key] as number) : row[key] == null ? '—' : String(row[key])
function saveDiagnostics() { const job = props.spectrum?.jobId; if (job) void saveOutput(`SimLIBS-${job}-line-diagnostics.csv`, () => download(job, 'diagnostics')) }
</script>
<template>
    <SpectrumChart v-if="spectrum" :spectrum="spectrum" :view-mode="viewMode" :label="viewMode === 'elements' ? '元素组分' : '三谱对照'" />
    <section v-else class="panel empty-state"><EmptyStateArt /><h3>尚未生成高级光谱</h3><p>配置左侧参数与元素后点击“运行高级模拟”，查看共同尺度三谱及逐线诊断。</p></section>
  <template v-if="spectrum">
    <section class="panel activity-panel"><h2>已完成结果 · {{ advancedResultLabel(origin?.model_version, origin) }}</h2><p class="hint">结果任务：{{ spectrum.jobId || spectrum.id }}。图谱、CSV/JSON/PNG 与下方诊断均绑定此结果，不随最新失败任务改变。</p><p class="hint">{{ nist ? 'NIST 相对光子强度。' : origin?.model_version === 'paper-eq7-stark-sa-1' ? '离线论文 photon 强度（未标定）。' : '旧模型结果按原来源、参数与单位保留，不解释为新 NIST 模型。' }}<template v-if="flags.known"> 自吸收{{ flags.absorption ? '开启' : '关闭' }} · Stark{{ flags.stark ? '开启' : '关闭' }} · 仪器{{ flags.instrument ? '开启' : '关闭（R不应用）' }}。<span v-if="flags.instrument">{{ nist ? '仪器1/e半宽w=λ/R，FWHM=2√ln2·λ/R。' : '仪器FWHM=λ/R。' }}</span></template></p><p v-if="spectrum.source.style === 'sticks'" class="hint">这是未展宽线面积的网格投影，高度依赖步长；真实线位与面积保存在来源JSON中，不表示物理线宽。</p></section>
    <div class="segmented" aria-label="高级光谱视图"><button :class="{selected:viewMode === 'elements'}" :aria-pressed="viewMode === 'elements'" @click="viewMode='elements'">元素组分</button><button :class="{selected:viewMode === 'comparison'}" :aria-pressed="viewMode === 'comparison'" :disabled="!spectrum.comparison" @click="viewMode='comparison'">三谱对照</button></div>
    <p v-if="!spectrum.elements.length" class="hint">此历史结果未保存元素贡献，仅显示已有总谱；不补造组分曲线。</p>
    <p class="hint">切换只影响显示，CSV/JSON保留完整三谱与元素数据；前端PNG按所选视图，后端PNG为固定元素视图。</p>
    <section class="panel activity-panel">
      <div class="panel-heading"><h2>逐线诊断</h2><button class="btn sm" :disabled="!rows.length || !spectrum.jobId || saving" @click="saveDiagnostics">导出完整诊断 CSV</button></div>
      <p v-if="!rows.length" class="hint">{{ flags.known && !flags.stark ? '未启用Stark：不生成τ、SA或Stark系数诊断，真实NIST线位/面积随来源JSON保留。' : '此历史结果未保存逐线诊断，已有图谱及来源仍可查看。' }}</p>
      <template v-else><p class="hint">共 {{ rows.length }} 条；τ 为逐线中心光学厚度，SA 为峰高衰减因子。界面读数为简写，CSV 保留完整精度；诊断不是连续总光学厚度场。</p><div class="table-scroll"><table><thead><tr><th>λ / nm</th><th>离子</th><th>τ</th><th>SA</th><th>薄谱 FWHM / nm</th><th>吸收 FWHM / nm</th><th>薄谱面积</th><th>吸收面积</th><th>系数出处</th></tr></thead><tbody><tr v-for="(row,index) in visible" :key="index"><td class="mono">{{ cell(row,'wavelength_nm') }}</td><td>{{ row.ion || `${row.element || ''} ${row.charge ?? ''}+` }}</td><td>{{ cell(row,'tau_center') }}</td><td>{{ cell(row,'SA') }}</td><td>{{ cell(row,'thin_fwhm_nm') }}</td><td>{{ cell(row,'absorbed_fwhm_nm') }}</td><td>{{ cell(row,'thin_area') }}</td><td>{{ cell(row,'absorbed_area') }}</td><td>{{ row.stark_source || row.source || '原始论文记录' }}</td></tr></tbody></table></div><div class="pager"><span>{{ page*pageSize+1 }}–{{ Math.min(rows.length,(page+1)*pageSize) }} / {{ rows.length }}</span><div><button class="btn sm" :disabled="page === 0" @click="page--">上一页</button><button class="btn sm" :disabled="(page+1)*pageSize >= rows.length" @click="page++">下一页</button></div></div></template>
      <p v-if="feedback" :class="failed ? 'error-text' : 'hint'" role="status">{{ feedback }}</p>
    </section>
  </template>
</template>
