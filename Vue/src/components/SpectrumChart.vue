<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import FileFormatIcon from './FileFormatIcon.vue'
import { elementColor, format, type Spectrum } from '../lib/model'
import { realSpectrumCsv } from '../lib/backend'
import { useFileSave } from '../lib/fileAccess'
import { localPeakIndices, nearestNode, selectHoverNode } from '../lib/spectrumInteraction'
import { advancedFlags, isNistAdvanced } from '../lib/advanced'
const props = defineProps<{ spectrum: Spectrum; label?: string; viewMode?: 'elements' | 'comparison' }>()
const spec = computed(() => props.spectrum)
const showComparison = computed(() => props.viewMode !== 'elements' && !!spec.value.comparison)
const showElements = computed(() => props.viewMode !== 'comparison')
const resolutionLabel = computed(() => {
  const origin = spec.value.source.origin as { actual_resolution?: number | null; parameters?: { webscraping?: string; local_broadening_enabled?: boolean } } | undefined
  if (origin?.parameters?.webscraping === 'local' && !origin.parameters.local_broadening_enabled) return '未展宽（R 不应用）'
  const flags = advancedFlags(spec.value.source.origin)
  if (flags.known && !flags.instrument) return '仪器响应未启用（R 不应用）'
  return typeof origin?.actual_resolution === 'number' && Number.isFinite(origin.actual_resolution) ? `实际 R (λ/Δλ) ${origin.actual_resolution}` : '实际 R (λ/Δλ) 未知'
})
const canvas = ref<HTMLCanvasElement>()
const { pending: saving, feedback: saveFeedback, failed: saveFailed, run: saveOutput } = useFileSave()
const hidden = ref<string[]>([]), normalized = ref(true), hover = ref<number | null>(null)
const hoverSeries = ref('total'), snapped = ref(false), tooltip = ref<HTMLElement>()
const tooltipPosition = ref({ left: 8, top: 8 })
let pointer: { x: number; y: number } | null = null
const view = ref<[number, number]>([spec.value.params.low, spec.value.params.high])
const drag = ref<{ start: number; now: number; pan: boolean; initial: [number, number]; pointerId: number } | null>(null)
let resize: ResizeObserver | undefined, themeObserver: MutationObserver | undefined
const max = computed(() => [spec.value.total, ...(showElements.value ? spec.value.elements.map(e => e.ys) : []), ...(showComparison.value ? [spec.value.comparison!.thin,spec.value.comparison!.nominal] : [])].reduce((peak, values) => values.reduce((m, v) => Math.max(m,v),peak), 1e-30))
const nistAdvanced = computed(() => isNistAdvanced(spec.value.source.origin?.model_version))
const unit = computed(() => normalized.value ? '共同归一化强度' : nistAdvanced.value ? 'NIST 相对光子强度 / a.u.' : spec.value.comparison ? '模型光子辐亮度（未标定）/ photons·s⁻¹·m⁻²·sr⁻¹·nm⁻¹' : '实际强度 / a.u.')
const valueUnit = computed(()=>nistAdvanced.value ? 'a.u. · NIST 相对光子强度' : spec.value.comparison ? '(s·m²·sr·nm)⁻¹ · 未标定' : 'a.u.')
const zoomed = computed(() => Math.abs(view.value[0] - spec.value.params.low) > .00001 || Math.abs(view.value[1] - spec.value.params.high) > .00001)
const visibleCurves = computed(() => [
  ...(!hidden.value.includes('total') ? [{ id: 'total', label: '总谱', ys: spec.value.total, color: '' }] : []),
  ...(showComparison.value ? [{ id: '$nominal', label: '名义薄谱', ys: spec.value.comparison!.nominal, color: '#8d8d8d' }, { id: '$thin', label: '基体薄谱', ys: spec.value.comparison!.thin, color: '#d078ad' }] : []),
  ...(showElements.value ? spec.value.elements.filter(e => !hidden.value.includes(e.symbol)).map(e => ({ id: e.symbol, label: e.symbol, ys: e.ys, color: elementColor(e.symbol) })) : [])
])
const peakCurves = computed(() => visibleCurves.value.map(curve => ({ ...curve, peaks: localPeakIndices(curve.ys) })))
const hoverValues = computed(() => hover.value === null ? null : { x: spec.value.xs[hover.value]!, rows: visibleCurves.value.map(curve => ({ ...curve, value: curve.ys[hover.value!]! })) })
function geometry() { const cv = canvas.value; if (!cv) return null; const rect = cv.getBoundingClientRect(); return { rect, left: 76, right: 28, top: showComparison.value || props.viewMode === 'elements' ? 62 : 38, bottom: 58, w: rect.width, h: rect.height } }
function positionTooltip() {
  const g = geometry(), box = tooltip.value
  if (!g || !box || hover.value === null) return
  const width = box.offsetWidth, height = box.offsetHeight
  const anchor = pointer ?? { x: g.left + (spec.value.xs[hover.value]! - view.value[0]) / (view.value[1] - view.value[0]) * (g.w - g.left - g.right), y: g.top + 24 }
  const left = anchor.x + 16 + width <= g.w - 8 ? anchor.x + 16 : anchor.x - width - 16
  const top = anchor.y + 16 + height <= g.h - 8 ? anchor.y + 16 : anchor.y - height - 16
  tooltipPosition.value = { left: Math.max(8, Math.min(g.w - width - 8, left)), top: Math.max(8, Math.min(g.h - height - 8, top)) }
}
function leaveChart(event: PointerEvent) { if (!drag.value && !tooltip.value?.contains(event.relatedTarget as Node | null) && !tooltip.value?.contains(document.activeElement)) hover.value = null }
function draw() {
  const cv = canvas.value, g = geometry(); if (!cv || !g || g.w < 20 || g.h < 20) return
  const dpr = window.devicePixelRatio || 1; cv.width = Math.round(g.w * dpr); cv.height = Math.round(g.h * dpr)
  const ctx = cv.getContext('2d'); if (!ctx) return; ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const css = getComputedStyle(document.documentElement), color = (key: string) => css.getPropertyValue(key).trim()
  const fontFamily = css.fontFamily || '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif'
  const numericFamily = css.getPropertyValue('--font-code').trim() || 'Consolas, monospace'
  const auxiliarySize = css.getPropertyValue('--text-aux').trim() || '12px'
  const metadataSize = css.getPropertyValue('--text-meta').trim() || '11px'
  ctx.fillStyle = color('--panel'); ctx.fillRect(0, 0, g.w, g.h)
  const pw = g.w - g.left - g.right, ph = g.h - g.top - g.bottom, base = g.h - g.bottom
  const factor = normalized.value ? max.value : 1, ymax = max.value / factor * 1.12
  const xPos = (x: number) => g.left + (x - view.value[0]) / (view.value[1] - view.value[0]) * pw
  const yPos = (v: number) => base - v / factor / ymax * ph
  ctx.font = `${auxiliarySize} ${numericFamily}`; ctx.fillStyle = color('--muted'); ctx.strokeStyle = color('--muted'); ctx.lineWidth = 1
  ctx.lineCap = 'round'; ctx.setLineDash([1, 5])
  for (let i = 0; i <= 4; i++) { const y = base - i / 4 * ph; ctx.globalAlpha = .2; ctx.beginPath(); ctx.moveTo(g.left, y); ctx.lineTo(g.w - g.right, y); ctx.stroke(); ctx.globalAlpha = 1; ctx.textAlign = 'right'; ctx.fillText(format(i / 4 * ymax), g.left - 9, y + 3) }
  const ticks = Math.max(1, Math.min(6, Math.floor(pw / 90)))
  for (let i = 0; i <= ticks; i++) { const x = g.left + i / ticks * pw; ctx.globalAlpha = .2; ctx.beginPath(); ctx.moveTo(x, g.top); ctx.lineTo(x, base); ctx.stroke(); ctx.globalAlpha = 1; ctx.textAlign = i === 0 ? 'left' : i === ticks ? 'right' : 'center'; ctx.fillText(format(view.value[0] + (view.value[1] - view.value[0]) * i / ticks), x, base + 20) }
  ctx.setLineDash([]); ctx.font = `${auxiliarySize} ${fontFamily}`
  ctx.textAlign = 'left'; ctx.fillText(normalized.value ? '共同归一化强度' : '原始强度', g.left, 17)
  if(showComparison.value) {
    ctx.font=`${metadataSize} ${fontFamily}`
    for(const [i,label,stroke] of [[0,'名义薄谱','#8d8d8d'],[1,'基体薄谱','#d078ad'],[2,'修正谱',color('--chart')]] as const){ctx.fillStyle=stroke;ctx.fillText(label,g.left+i*(g.w-g.left-g.right)/3,40)}
    ctx.fillStyle=color('--muted')
  } else if (props.viewMode === 'elements') {
    const entries = visibleCurves.value
    ctx.font=`${metadataSize} ${fontFamily}`
    entries.forEach((entry, i) => { const slot=(g.w-g.left-g.right)/Math.max(1,entries.length); ctx.fillStyle=entry.color || color('--chart'); ctx.fillText(entry.label,g.left+i*slot,40,Math.max(1,slot-4)) })
    ctx.fillStyle=color('--muted')
  }
  ctx.textAlign = 'right'; ctx.fillText('λ / nm', g.w - g.right, base + 37)
  ctx.save(); ctx.beginPath(); ctx.rect(g.left, g.top, pw, ph); ctx.clip()
  // Every source node is rendered. Canvas size never determines data density.
  const curve = (ys: number[], stroke: string, total = false, comparison = false) => {
    let started = false, complete = true
    ctx.beginPath(); spec.value.xs.forEach((x, i) => { const value = ys[i]; if (!Number.isFinite(x) || value === undefined || !Number.isFinite(value)) { started = false; complete = false; return }; const px = xPos(x), py = yPos(value); if (spec.value.source.style === 'sticks') { ctx.moveTo(px, base); ctx.lineTo(px, py) } else { started ? ctx.lineTo(px, py) : ctx.moveTo(px, py); started = true } })
    ctx.strokeStyle = stroke; ctx.lineWidth = total ? 2 : comparison ? 1.2 : 1; ctx.setLineDash([]); ctx.stroke()
    if (total && complete && spec.value.xs.length > 1 && spec.value.source.style !== 'sticks') { ctx.lineTo(xPos(spec.value.xs[spec.value.xs.length - 1]!), base); ctx.lineTo(xPos(spec.value.xs[0]!), base); ctx.closePath(); const gradient = ctx.createLinearGradient(0, g.top, 0, base); gradient.addColorStop(0, stroke); gradient.addColorStop(1, 'transparent'); ctx.globalAlpha = .07; ctx.fillStyle = gradient; ctx.fill(); ctx.globalAlpha = 1 }
  }
  if (showElements.value) spec.value.elements.filter(e => !hidden.value.includes(e.symbol)).forEach(e => curve(e.ys, elementColor(e.symbol)))
  if (showComparison.value) { curve(spec.value.comparison!.nominal, '#8d8d8d', false, true); curve(spec.value.comparison!.thin, '#d078ad', false, true) }
  if (!hidden.value.includes('total')) curve(spec.value.total, color('--chart'), true)
  if (hover.value !== null) { const active = visibleCurves.value.find(item => item.id === hoverSeries.value), value = active?.ys[hover.value]; if (active && value !== undefined && Number.isFinite(value)) { const x = xPos(spec.value.xs[hover.value]!), y = yPos(value); ctx.strokeStyle = color('--chart'); ctx.globalAlpha = .55; ctx.lineWidth = 1; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x, g.top); ctx.lineTo(x, base); ctx.moveTo(g.left, y); ctx.lineTo(g.w - g.right, y); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1; ctx.fillStyle = active.color || color('--chart'); ctx.strokeStyle = color('--panel'); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, y, snapped.value ? 4 : 3, 0, Math.PI * 2); ctx.fill(); ctx.stroke() } }
  if (drag.value && !drag.value.pan) { ctx.globalAlpha = .14; ctx.fillStyle = color('--accent'); const a = xPos(drag.value.start), b = xPos(drag.value.now); ctx.fillRect(Math.min(a,b), g.top, Math.abs(b - a), ph); ctx.globalAlpha = 1 }
  ctx.restore(); ctx.font = `${metadataSize} ${fontFamily}`; ctx.fillStyle = color('--muted'); ctx.textAlign = 'left'; ctx.fillText(spec.value.source.description, g.left, g.h - 3)
}
function clampView(a: number, b: number) {
  const { low, high } = spec.value.params, span = Math.min(high - low, Math.max((high - low) / 1000, b - a))
  const start = Math.max(low, Math.min(high - span, a)); view.value = [start, start + span]
}
function releaseDrag() { const id = drag.value?.pointerId; drag.value = null; if (id !== undefined && canvas.value?.hasPointerCapture(id)) canvas.value.releasePointerCapture(id) }
function cancelDrag() { releaseDrag(); draw() }
function reset() { releaseDrag(); view.value = [spec.value.params.low, spec.value.params.high]; hover.value = null }
function zoom(factor: number, center = (view.value[0] + view.value[1]) / 2) { const a = center + (view.value[0] - center) * factor, b = center + (view.value[1] - center) * factor; clampView(a,b) }
function xAt(e: PointerEvent | WheelEvent) { const g = geometry(); if (!g) return view.value[0]; return view.value[0] + Math.max(0, Math.min(1, (e.clientX - g.rect.left - g.left) / (g.w - g.left - g.right))) * (view.value[1] - view.value[0]) }
function move(e: PointerEvent) {
  if (drag.value) {
    const x = xAt(e)
    if (drag.value.pan) { const g = geometry()!; const delta = (e.clientX - g.rect.left - g.left) / (g.w - g.left - g.right) * (drag.value.initial[1] - drag.value.initial[0]); const shift = drag.value.start - (drag.value.initial[0] + delta); clampView(drag.value.initial[0] + shift, drag.value.initial[1] + shift) }
    else drag.value.now = x
    draw()
  } else {
    const g = geometry(); if (!g) return
    pointer = { x: e.clientX - g.rect.left, y: e.clientY - g.rect.top }
    const selection = selectHoverNode(spec.value.xs, peakCurves.value, { low: view.value[0], high: view.value[1], left: g.left, top: g.top, width: g.w - g.left - g.right, height: g.h - g.top - g.bottom, yMaximum: max.value * 1.12 }, pointer.x, pointer.y)
    hover.value = selection?.index ?? null; hoverSeries.value = selection?.curveId ?? ''; snapped.value = selection?.snapped ?? false
    positionTooltip()
  }
}
function preventMiddleDefault(e: MouseEvent) { if (e.button === 1) e.preventDefault() }
function down(e: PointerEvent) {
  if (e.button === 2) { e.preventDefault(); reset(); return }
  if (e.button !== 0 && e.button !== 1) return
  if (e.button === 1) { e.preventDefault(); canvas.value?.focus({ preventScroll: true }) }
  releaseDrag(); hover.value = null
  drag.value = { start: xAt(e), now: xAt(e), pan: e.button === 1 || e.altKey, initial: [...view.value], pointerId: e.pointerId }
  canvas.value?.setPointerCapture(e.pointerId)
}
function up(e: PointerEvent) { if (!drag.value || e.pointerId !== drag.value.pointerId) return; if (!drag.value.pan && Math.abs(drag.value.now - drag.value.start) > (view.value[1] - view.value[0]) * .012) clampView(Math.min(drag.value.start, drag.value.now), Math.max(drag.value.start, drag.value.now)); releaseDrag(); draw() }
function key(e: KeyboardEvent) { if (e.key === '+' || e.key === '=') zoom(.65); else if (e.key === '-') zoom(1.5); else if (e.key === 'Home' || e.key === 'Escape') reset(); else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { const index = nearestNode(spec.value.xs, (view.value[0] + view.value[1]) / 2); hover.value = index === null || !visibleCurves.value.length ? null : Math.max(0, Math.min(spec.value.xs.length - 1, (hover.value ?? index) + (e.key === 'ArrowRight' ? 1 : -1))); hoverSeries.value = visibleCurves.value[0]?.id ?? ''; snapped.value = false; pointer = null } else return; e.preventDefault() }
function toggle(id: string) { hidden.value = hidden.value.includes(id) ? hidden.value.filter(x => x !== id) : [...hidden.value, id] }
function pngBlob(): Promise<Blob> {
  const cv = canvas.value
  if (!cv) return Promise.reject(new Error('图谱画布尚未就绪'))
  const previous = hover.value; hover.value = null
  try { draw(); return new Promise((resolve, reject) => cv.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG 编码失败，未保存文件')), 'image/png')) }
  finally { hover.value = previous; draw() }
}
function exportFile(kind: 'csv' | 'json' | 'png') {
  const snapshot = spec.value
  if (kind === 'csv') void saveOutput('SimLIBS-spectrum.csv', realSpectrumCsv(snapshot), 'text/csv;charset=utf-8')
  if (kind === 'json') void saveOutput('SimLIBS-source.json', JSON.stringify(snapshot, null, 2), 'application/json')
  if (kind === 'png') void saveOutput('SimLIBS-spectrum.png', pngBlob, 'image/png')
}
watch([view, hidden, normalized, hover, hoverSeries, snapped], () => { draw(); void nextTick(positionTooltip) })
watch(() => props.viewMode, () => { hover.value = null; snapped.value = false; void nextTick(draw) })
watch(visibleCurves, curves => { if (!curves.some(curve => curve.id === hoverSeries.value)) hover.value = null })
watch(() => spec.value, (next, old) => { hover.value = null; if (next.params.low !== old.params.low || next.params.high !== old.params.high) reset(); if (next.elements.map(e => e.symbol).join() !== old.elements.map(e => e.symbol).join()) hidden.value = []; draw() })
onMounted(() => { resize = new ResizeObserver(() => { draw(); positionTooltip() }); if (canvas.value) resize.observe(canvas.value); themeObserver = new MutationObserver(draw); themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme','style'] }); window.addEventListener('resize', draw); draw() })
onUnmounted(() => { resize?.disconnect(); themeObserver?.disconnect(); window.removeEventListener('resize', draw) })
</script>
<template>
  <section class="panel spectrum-panel">
    <div class="chart-title-row"><div><h2>光谱 <span class="badge neutral">{{ label || '计算结果' }}</span></h2><p>{{ spec.title }} · Te / eV {{ format(spec.params.te) }} · {{ resolutionLabel }}</p></div><div class="chart-tools"><button class="icon-btn" aria-label="放大光谱" title="放大" @click="zoom(.65)"><AppIcon name="plus" :size="15" /></button><button class="icon-btn" aria-label="缩小光谱" title="缩小" @click="zoom(1.5)"><AppIcon name="minus" :size="15" /></button><button class="icon-btn" aria-label="恢复全谱" title="恢复全谱" :disabled="!zoomed" @click="reset"><AppIcon name="reset" :size="15" /></button></div></div>
    <p v-if="showComparison" class="hint">灰：名义薄谱 · 粉：基体薄谱 · 主题色：当前总谱；三谱使用同一归一化尺度。</p><p v-else-if="viewMode === 'elements'" class="hint">当前混合计算的总谱与各元素贡献共用尺度；单元素贡献可与总谱重合，可用图例隐藏总谱查看。</p><div class="chart-overline"><span>{{ unit }}</span><span class="mono">λ / nm {{ format(view[0]) }} — {{ format(view[1]) }}</span></div>
    <div class="chart-wrap"><canvas ref="canvas" class="chart-surface" tabindex="0" role="img" :aria-label="`${spec.title}，界面光谱。左键拖选缩放，中键或 Alt 加左键拖动平移，右键恢复全谱，滚轮缩放，Home/Escape 复原，左右方向键读取节点。`" @pointermove="move" @pointerdown="down" @pointerup="up" @pointercancel="cancelDrag" @lostpointercapture="cancelDrag" @mousedown="preventMiddleDefault" @auxclick="preventMiddleDefault" @contextmenu.prevent="reset" @pointerleave="leaveChart" @wheel.prevent="zoom($event.deltaY > 0 ? 1.15 : .85, xAt($event))" @keydown="key" />
      <div v-if="hoverValues && !drag" ref="tooltip" class="chart-tooltip" :style="{ left: tooltipPosition.left + 'px', top: tooltipPosition.top + 'px' }" tabindex="0" role="region" aria-label="光谱节点读数" @pointerleave="leaveChart"><b class="mono">λ / nm {{ format(hoverValues.x) }}</b><span>{{ snapped ? '局部峰吸附 · 10px 内' : '原始节点' }} · {{ hover }}</span><p class="tooltip-unit">原值单位：{{ valueUnit }}</p><div class="tooltip-values"><span>曲线</span><span>原值</span><span>共同归一化</span><template v-for="row in hoverValues.rows" :key="row.id"><span class="curve-name"><i :style="{ background: row.color || 'var(--chart)' }" />{{ row.label }}</span><strong class="mono" :title="String(row.value)">{{ format(row.value) }}</strong><strong class="mono">{{ format(row.value / max) }}</strong></template></div><p v-if="spec.elements.length" class="tooltip-note">元素贡献；当前数据不含谱线离子鉴定。</p><p v-if="hidden.includes('total')" class="tooltip-note">总谱已隐藏，读数仅列可见曲线。</p></div>
    </div>
    <div class="chart-bottom"><div class="legend"><button :aria-pressed="!hidden.includes('total')" :class="{ 'legend-off': hidden.includes('total') }" @click="toggle('total')"><i style="background:var(--chart)" />总谱</button><template v-if="showElements"><button v-for="e in spec.elements" :key="e.symbol" :aria-pressed="!hidden.includes(e.symbol)" :class="{ 'legend-off': hidden.includes(e.symbol) }" @click="toggle(e.symbol)"><i :style="{ background: elementColor(e.symbol) }" />{{ e.symbol }}</button></template></div><label class="inline-check"><input v-model="normalized" type="checkbox" />共同归一化</label></div>
    <div class="export-row"><div><button type="button" class="file-export-btn format-csv" :disabled="saving" title="保存 CSV" aria-label="保存 CSV" @click="exportFile('csv')"><FileFormatIcon format="csv" /></button><button type="button" class="file-export-btn format-json" :disabled="saving" title="保存来源 JSON" aria-label="保存来源 JSON" @click="exportFile('json')"><FileFormatIcon format="json" /></button><button type="button" class="file-export-btn format-png" :disabled="saving" title="保存 PNG" aria-label="保存 PNG" @click="exportFile('png')"><FileFormatIcon format="png" /></button></div></div><p v-if="saveFeedback" :class="saveFailed ? 'error-text' : 'hint'" style="overflow-wrap:anywhere" role="status">{{ saveFeedback }}</p>
  </section>
</template>
