<script setup lang="ts">
import { computed } from 'vue'
import { numeric } from '../lib/model'
const props = defineProps<{ low: string; high: string }>()
const bands = [
  { name: '其他短波', from: 1, to: 10, color: '#64748b' },
  { name: '极紫外', from: 10, to: 100, color: '#a855f7' },
  { name: '深紫外', from: 100, to: 280, color: '#6366f1' },
  { name: '紫外', from: 280, to: 380, color: '#b34ca4' },
  { name: '可见光', from: 380, to: 780, color: '#25876d' },
  { name: '红外', from: 780, to: 100000, color: '#c76236' }
]
const segments = computed(() => {
  try {
    const low = numeric(props.low, '波长下限', 1, 100000), high = numeric(props.high, '波长上限', 1, 100000)
    if (high <= low) return []
    return bands.flatMap(band => {
      const from = Math.max(low, band.from), to = Math.min(high, band.to)
      return to > from ? [{ ...band, from, to, percentage: (to - from) / (high - low) * 100 }] : []
    })
  } catch { return [] }
})
const range = (from: number, to: number) => String(from) + '–' + String(to) + ' nm'
</script>
<template>
  <div class="wavelength-bands" aria-label="波长跨度组成">
    <div class="band-caption"><span>按波长跨度显示</span><details class="band-convention"><summary>分区口径</summary><p>本图互斥分区：其他短波 &lt;10；EUV 10–100；DUV 100–280；其余紫外 280–380；可见光 380–780；红外 ≥780 nm。边界归入后一段，DUV 的 100–280 nm 仅为本图显示约定，非唯一标准。颜色用于界面区分，长度不表示强度或谱线数。</p></details></div>
    <div class="band-track" aria-hidden="true"><span v-for="segment in segments" :key="segment.name" class="band-segment" :style="{ width: segment.percentage + '%', backgroundColor: segment.color }" /></div>
    <ul v-if="segments.length" class="band-legend"><li v-for="segment in segments" :key="segment.name"><i :style="{ backgroundColor: segment.color }" aria-hidden="true" /><span>{{ segment.name }} <span class="band-range">{{ range(segment.from, segment.to) }}</span></span></li></ul>
    <p v-else class="band-neutral">输入有效的波长上下限后显示</p>
  </div>
</template>
<style scoped>
.wavelength-bands{margin:4px 0 14px;min-width:0;font-size:var(--text-aux);color:var(--muted)}
.band-caption{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:4px 10px;margin-bottom:7px}
.band-convention{max-width:100%}
.band-convention>summary{cursor:pointer;color:var(--accent-text)}
.band-convention>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}
.band-convention p{margin:6px 0;line-height:1.65;overflow-wrap:anywhere}
.band-track{display:flex;width:100%;height:7px;border-radius:4px;overflow:hidden;background:var(--border)}
.band-segment{flex:none;height:100%}
.band-legend{display:flex;flex-wrap:wrap;gap:5px 12px;list-style:none;padding:0;margin:8px 0 0}
.band-legend>li{display:flex;align-items:baseline;gap:5px;min-width:0;max-width:100%}
.band-legend i{flex:none;width:7px;height:7px;border-radius:2px}
.band-legend>li>span{min-width:0;overflow-wrap:anywhere;color:var(--text)}
.band-range{color:var(--muted)}
.band-neutral{margin:7px 0 0;color:var(--faint)}
</style>
