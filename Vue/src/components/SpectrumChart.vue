<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import FileFormatIcon from './FileFormatIcon.vue'
import { elementColor, format, type Spectrum } from '../lib/model'
import { spectrumCsv } from '../lib/demo'
import { useFileSave } from '../lib/fileAccess'
import { initialSpectrum } from '../lib/workbench'
const props = defineProps<{ spectrum?: Spectrum; label?: string }>()
const spec = computed(() => props.spectrum ?? initialSpectrum)
const canvas = ref<HTMLCanvasElement>()
const { pending: saving, feedback: saveFeedback, failed: saveFailed, run: saveOutput } = useFileSave()
const hidden = ref<string[]>([]), normalized = ref(true), hover = ref<number | null>(null)
const view = ref<[number, number]>([spec.value.params.low, spec.value.params.high])
const drag = ref<{ start: number; now: number; pan: boolean; initial: [number, number]; pointerId: number } | null>(null)
let resize: ResizeObserver | undefined, themeObserver: MutationObserver | undefined
const max = computed(() => Math.max(...spec.value.total, .00001))
const unit = computed(() => normalized.value ? '共同归一化强度' : '示意强度 / a.u.')
const zoomed = computed(() => Math.abs(view.value[0] - spec.value.params.low) > .00001 || Math.abs(view.value[1] - spec.value.params.high) > .00001)
const hoverValues = computed(() => hover.value === null ? null : { x: spec.value.xs[hover.value]!, total: spec.value.total[hover.value]!, elements: spec.value.elements.map(e => ({ symbol: e.symbol, value: e.ys[hover.value!]! })) })
function geometry() { const cv = canvas.value; if (!cv) return null; const rect = cv.getBoundingClientRect(); return { rect, left: rect.width < 360 ? 42 : 54, right: 12, top: 38, bottom: 53, w: rect.width, h: rect.height } }
function draw() {
  const cv = canvas.value, g = geometry(); if (!cv || !g || g.w < 20 || g.h < 20) return
  const dpr = window.devicePixelRatio || 1; cv.width = Math.round(g.w * dpr); cv.height = Math.round(g.h * dpr)
  const ctx = cv.getContext('2d'); if (!ctx) return; ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const css = getComputedStyle(document.documentElement), color = (key: string) => css.getPropertyValue(key).trim()
  const fontFamily = css.fontFamily || '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif'
  const auxiliarySize = css.getPropertyValue('--text-aux').trim() || '12px'
  const metadataSize = css.getPropertyValue('--text-meta').trim() || '11px'
  ctx.fillStyle = color('--panel'); ctx.fillRect(0, 0, g.w, g.h)
  const pw = g.w - g.left - g.right, ph = g.h - g.top - g.bottom, base = g.h - g.bottom
  const factor = normalized.value ? max.value : 1, ymax = max.value / factor * 1.12
  const xPos = (x: number) => g.left + (x - view.value[0]) / (view.value[1] - view.value[0]) * pw
  const yPos = (v: number) => base - v / factor / ymax * ph
  ctx.font = `${auxiliarySize} ${fontFamily}`; ctx.fillStyle = color('--muted'); ctx.strokeStyle = color('--grid'); ctx.lineWidth = 1
  for (let i = 0; i <= 4; i++) { const y = base - i / 4 * ph; ctx.beginPath(); ctx.moveTo(g.left, y); ctx.lineTo(g.w - g.right, y); ctx.stroke(); ctx.textAlign = 'right'; ctx.fillText(format(i / 4 * ymax), g.left - 10, y + 3) }
  const ticks = g.w < 420 ? 3 : 6
  for (let i = 0; i <= ticks; i++) { const x = g.left + i / ticks * pw; ctx.beginPath(); ctx.moveTo(x, g.top); ctx.lineTo(x, base); ctx.stroke(); ctx.textAlign = 'center'; ctx.fillText(format(view.value[0] + (view.value[1] - view.value[0]) * i / ticks), x, base + 20) }
  ctx.textAlign = 'left'; ctx.fillText(unit.value, g.left, 17)
  ctx.textAlign = 'right'; ctx.fillText('λ / nm', g.w - g.right, base + 37)
  ctx.save(); ctx.beginPath(); ctx.rect(g.left, g.top, pw, ph); ctx.clip()
  // Every source node is rendered. Canvas size never determines data density.
  const curve = (ys: number[], stroke: string, total = false) => {
    ctx.beginPath(); spec.value.xs.forEach((x, i) => { const px = xPos(x), py = yPos(ys[i]!); i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py) })
    ctx.strokeStyle = stroke; ctx.lineWidth = total ? 1.5 : 1; ctx.setLineDash([]); ctx.stroke(); ctx.setLineDash([])
    if (total) { ctx.lineTo(xPos(spec.value.xs[spec.value.xs.length - 1]!), base); ctx.lineTo(xPos(spec.value.xs[0]!), base); ctx.closePath(); ctx.globalAlpha = .06; ctx.fillStyle = stroke; ctx.fill(); ctx.globalAlpha = 1 }
  }
  spec.value.elements.filter(e => !hidden.value.includes(e.symbol)).forEach(e => curve(e.ys, elementColor(e.symbol)))
  if (!hidden.value.includes('total')) curve(spec.value.total, color('--chart'), true)
  if (hover.value !== null) { const x = xPos(spec.value.xs[hover.value]!); ctx.strokeStyle = color('--muted'); ctx.setLineDash([]); ctx.beginPath(); ctx.moveTo(x, g.top); ctx.lineTo(x, base); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = color('--chart'); ctx.beginPath(); ctx.arc(x, yPos(spec.value.total[hover.value]!), 3, 0, Math.PI * 2); ctx.fill() }
  if (drag.value && !drag.value.pan) { ctx.globalAlpha = .14; ctx.fillStyle = color('--accent'); const a = xPos(drag.value.start), b = xPos(drag.value.now); ctx.fillRect(Math.min(a,b), g.top, Math.abs(b - a), ph); ctx.globalAlpha = 1 }
  ctx.restore(); ctx.font = `${metadataSize} ${fontFamily}`; ctx.fillStyle = color('--muted'); ctx.textAlign = 'left'; ctx.fillText('frontend_demo / illustrative', g.left, g.h - 3)
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
function nearest(x: number) { let a = 0, b = spec.value.xs.length - 1; while (a < b) { const m = (a + b) >> 1; if (spec.value.xs[m]! < x) a = m + 1; else b = m } return a > 0 && x - spec.value.xs[a-1]! < spec.value.xs[a]! - x ? a - 1 : a }
function move(e: PointerEvent) {
  if (drag.value) {
    const x = xAt(e)
    if (drag.value.pan) { const g = geometry()!; const delta = (e.clientX - g.rect.left - g.left) / (g.w - g.left - g.right) * (drag.value.initial[1] - drag.value.initial[0]); const shift = drag.value.start - (drag.value.initial[0] + delta); clampView(drag.value.initial[0] + shift, drag.value.initial[1] + shift) }
    else drag.value.now = x
    draw()
  } else { hover.value = nearest(xAt(e)) }
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
function key(e: KeyboardEvent) { if (e.key === '+' || e.key === '=') zoom(.65); else if (e.key === '-') zoom(1.5); else if (e.key === 'Home' || e.key === 'Escape') reset(); else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') hover.value = Math.max(0, Math.min(spec.value.xs.length - 1, (hover.value ?? nearest((view.value[0] + view.value[1]) / 2)) + (e.key === 'ArrowRight' ? 1 : -1))); else return; e.preventDefault() }
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
  if (kind === 'csv') void saveOutput('SimLIBS-frontend_demo.csv', spectrumCsv(snapshot), 'text/csv;charset=utf-8')
  if (kind === 'json') void saveOutput('SimLIBS-frontend_demo-source.json', JSON.stringify(snapshot, null, 2), 'application/json')
  if (kind === 'png') void saveOutput('SimLIBS-frontend_demo.png', pngBlob, 'image/png')
}
watch([view, hidden, normalized, hover], draw)
watch(() => spec.value, (next, old) => { hover.value = null; if (next.params.low !== old.params.low || next.params.high !== old.params.high) reset(); if (next.elements.map(e => e.symbol).join() !== old.elements.map(e => e.symbol).join()) hidden.value = []; draw() })
onMounted(() => { resize = new ResizeObserver(draw); if (canvas.value) resize.observe(canvas.value); themeObserver = new MutationObserver(draw); themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme','style'] }); window.addEventListener('resize', draw); draw() })
onUnmounted(() => { resize?.disconnect(); themeObserver?.disconnect(); window.removeEventListener('resize', draw) })
</script>
<template>
  <section class="panel spectrum-panel">
    <div class="chart-title-row"><div><h2>光谱 <span class="badge neutral">{{ label || '示意光谱' }}</span></h2><p>{{ spec.title }} · Te {{ format(spec.params.te) }} eV · R {{ spec.params.resolution }}</p></div><div class="chart-tools"><button class="icon-btn" aria-label="放大光谱" title="放大" @click="zoom(.65)"><AppIcon name="plus" :size="15" /></button><button class="icon-btn" aria-label="缩小光谱" title="缩小" @click="zoom(1.5)"><AppIcon name="minus" :size="15" /></button><button class="icon-btn" aria-label="恢复全谱" title="恢复全谱" :disabled="!zoomed" @click="reset"><AppIcon name="reset" :size="15" /></button></div></div>
    <div class="chart-overline"><span>{{ unit }}</span><span class="mono">{{ format(view[0]) }} — {{ format(view[1]) }} nm</span></div>
    <div class="chart-wrap"><canvas ref="canvas" class="chart-surface" tabindex="0" role="img" :aria-label="`${spec.title}，界面示意光谱。左键拖选缩放，中键或 Alt 加左键拖动平移，右键恢复全谱，滚轮缩放，Home/Escape 复原，左右方向键读取节点。`" @pointermove="move" @pointerdown="down" @pointerup="up" @pointercancel="cancelDrag" @lostpointercapture="cancelDrag" @mousedown="preventMiddleDefault" @auxclick="preventMiddleDefault" @contextmenu.prevent="reset" @pointerleave="!drag && (hover = null)" @wheel.prevent="zoom($event.deltaY > 0 ? 1.15 : .85, xAt($event))" @keydown="key" />
      <div v-if="hoverValues && !drag" class="chart-tooltip"><b class="mono">{{ format(hoverValues.x) }} nm</b><span>原始示意节点 · {{ hover }}</span><div><span>总谱 / a.u.</span><strong class="mono">{{ format(hoverValues.total) }}</strong></div><div v-if="normalized"><span>共同归一化</span><strong class="mono">{{ format(hoverValues.total / max) }}</strong></div><div v-for="e in hoverValues.elements" :key="e.symbol"><span :style="{ color: elementColor(e.symbol) }">{{ e.symbol }} / a.u.</span><strong class="mono">{{ format(e.value) }}</strong></div></div>
    </div>
    <div class="chart-bottom"><div class="legend"><button :aria-pressed="!hidden.includes('total')" :class="{ 'legend-off': hidden.includes('total') }" @click="toggle('total')"><i style="background:var(--chart)" />总谱</button><button v-for="e in spec.elements" :key="e.symbol" :aria-pressed="!hidden.includes(e.symbol)" :class="{ 'legend-off': hidden.includes(e.symbol) }" @click="toggle(e.symbol)"><i :style="{ background: elementColor(e.symbol) }" />{{ e.symbol }}</button></div><label class="inline-check"><input v-model="normalized" type="checkbox" />共同归一化</label></div>
    <div class="export-row"><div><button type="button" class="file-export-btn format-csv" :disabled="saving" title="保存 CSV" aria-label="保存 CSV" @click="exportFile('csv')"><FileFormatIcon format="csv" /></button><button type="button" class="file-export-btn format-json" :disabled="saving" title="保存来源 JSON" aria-label="保存来源 JSON" @click="exportFile('json')"><FileFormatIcon format="json" /></button><button type="button" class="file-export-btn format-png" :disabled="saving" title="保存 PNG" aria-label="保存 PNG" @click="exportFile('png')"><FileFormatIcon format="png" /></button></div></div><p v-if="saveFeedback" :class="saveFailed ? 'error-text' : 'hint'" style="overflow-wrap:anywhere" role="status">{{ saveFeedback }}</p>
  </section>
</template>
