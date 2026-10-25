<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import EmptyStateArt from '../components/EmptyStateArt.vue'
import ParameterEditor from '../components/ParameterEditor.vue'
import CompositionEditor from '../components/CompositionEditor.vue'
import TaskActivity from '../components/TaskActivity.vue'
import SpectrumChart from '../components/SpectrumChart.vue'
import WorkbenchLayout from '../components/WorkbenchLayout.vue'
import ChoiceSelect from '../components/ChoiceSelect.vue'
import { apiParams, apiComposition, download } from '../lib/backend'
import { useFileSave } from '../lib/fileAccess'
const { pending: saving, feedback: saveFeedback, failed: saveFailed, run: saveOutput } = useFileSave()
import { errorOf, format, numeric, validateComposition, validateParams, type ScanResult } from '../lib/model'
import { activeTask, runReal, loadFrame, invalidateFrame, scan } from '../lib/workbench'
import { issueAttrs, scanIssues } from '../lib/issues'
const running = activeTask('scan'), playing = ref(false), submitError = ref(''), interval = ref('650')
const compositionError = ref('')
const issues = computed(() => scanIssues(scan.axis, scan.from, scan.to, scan.count))
const attrs = (key: string) => issueAttrs(issues.value[key], 'scan-draft-error')
const intervalChoices = [{ value: '1000', label: '1.00 s' }, { value: '650', label: '0.65 s' }, { value: '300', label: '0.30 s' }] as const
let timer: ReturnType<typeof setTimeout> | undefined
const labels: Record<ScanResult['axis'], { name: string; unit: string; from: string; to: string; min: number; max: number }> = { te: { name: 'Te', unit: 'eV', from: '0.6', to: '1.8', min: .01, max: 100 }, ne: { name: 'Ne', unit: 'cm⁻³', from: '1e16', to: '1e18', min: 1e10, max: 1e23 }, resolution: { name: 'R (λ/Δλ)', unit: '', from: '1000', to: '10000', min: 1, max: 1000000 } }
function values(): number[] { const l = labels[scan.axis], a = numeric(scan.from, `${l.name} 起点`, l.min, l.max, scan.axis === 'resolution'), b = numeric(scan.to, `${l.name} 终点`, l.min, l.max, scan.axis === 'resolution'), count = numeric(scan.count, '帧数', 2, 200, true); if (a >= b) throw new Error('扫描终点须大于起点'); return Array.from({ length: count }, (_, i) => i === 0 ? a : i === count - 1 ? b : scan.axis === 'resolution' ? Math.round(a + (b - a) * i / (count - 1)) : a + (b - a) * i / (count - 1)) }
const axisValues = computed(() => { try { return values() } catch { return [] } })
const inputError = computed(() => errorOf(() => { if (compositionError.value) throw new Error(compositionError.value); const list = values(); validateParams(scan.params, { [scan.axis]: list[0] }); validateComposition(scan.composition) }))
watch(inputError, value => { if (!value) submitError.value = '' })
const currentFrame = computed(() => scan.spectrum && scan.result ? { value: scan.result.frames[scan.frame]!.value, spectrum: scan.spectrum } : null)
const resultLabel = computed(() => scan.result ? labels[scan.result.axis] : labels[scan.axis])
function stop() { playbackRevision++;if (timer !== undefined) clearTimeout(timer); timer = undefined; playing.value = false;invalidateFrame() }
const requestedFrame=ref(scan.frame)
async function setFrame(frame: number) { stop();requestedFrame.value=Math.max(0, Math.min((scan.result?.frames.length ?? 1)-1,frame));await loadFrame(requestedFrame.value) }
let playbackRevision = 0
async function play() {
  if (playing.value) { playbackRevision++; stop(); return }
  if (!scan.result) return
  playing.value = true; const revision = ++playbackRevision
  try {
    if (scan.frame === scan.result.frames.length - 1) {requestedFrame.value=0;if(!await loadFrame(0)){if(revision===playbackRevision)stop();return}}
    if(!playing.value || revision!==playbackRevision)return
    const next = async () => {
      if (!playing.value || revision !== playbackRevision || !scan.result) return
      if (scan.frame >= scan.result.frames.length - 1) { stop(); return }
      requestedFrame.value=scan.frame+1
      const loaded=await loadFrame(requestedFrame.value)
      if(revision!==playbackRevision || !playing.value)return
      if(!loaded){stop();return}
      timer=setTimeout(next,Number(interval.value))
    }
    timer = setTimeout(next, Number(interval.value))
  } catch (e) { submitError.value = String(e); stop() }
}
watch(interval, () => { if (playing.value) { stop(); play() } })
watch(() => scan.result, () => {playbackRevision++;clearTimeout(timer);timer=undefined;playing.value=false;requestedFrame.value=0})
function changeAxis(axis: ScanResult['axis']) { scan.axis = axis; scan.from = labels[axis].from; scan.to = labels[axis].to }
async function run() {
  try { if (inputError.value) throw new Error(inputError.value); const list = values(), axis = scan.axis, params = validateParams(scan.params, { [axis]: list[0] }), comp = validateComposition(scan.composition); stop(); submitError.value = ''
    await runReal('scan', `${labels[axis].name} 参数扫描`, { params: apiParams(params), composition: apiComposition(comp), axis: axis === 'resolution' ? 'r' : axis,
      start: axis === 'ne' ? Math.log10(list[0]!) : list[0], end: axis === 'ne' ? Math.log10(list[list.length - 1]!) : list[list.length - 1], frames: list.length })
  } catch (e) { submitError.value = String(e) }
}
function saveGif() { const job = scan.result?.jobId; if (job) void saveOutput('SimLIBS-scan.gif', () => download(job, 'gif')) }
onUnmounted(stop)
onMounted(()=>{if(scan.result && !scan.spectrum){requestedFrame.value=0;void loadFrame(0)}})
</script>
<template><WorkbenchLayout kind="scan" class="scan-grid"><template #controls="{ disabled }"><fieldset class="control-fieldset" :disabled="disabled"><div class="panel-heading"><h2>扫描轴</h2><span class="section-number">S</span></div><div class="segmented"><button v-for="(label, axis) in labels" :key="axis" :class="{ selected: scan.axis === axis }" :aria-pressed="scan.axis === axis" @click="changeAxis(axis)">{{ label.name }}</button></div><div class="row2"><label class="field">{{ labels[scan.axis].name }} 起点{{ labels[scan.axis].unit ? ' / ' + labels[scan.axis].unit : '' }}<input id="scan-from" v-model="scan.from" type="text" inputmode="decimal" v-bind="attrs('from')" /></label><label class="field">{{ labels[scan.axis].name }} 终点{{ labels[scan.axis].unit ? ' / ' + labels[scan.axis].unit : '' }}<input id="scan-to" v-model="scan.to" type="text" inputmode="decimal" v-bind="attrs('to')" /></label></div><label class="field">帧数 <span>包含两端</span><input id="scan-count" v-model="scan.count" type="text" inputmode="numeric" v-bind="attrs('count')" /></label><div class="value-preview"><span v-for="(value, i) in axisValues.slice(0,6)" :key="i" class="mono">{{ format(value) }}</span><span v-if="axisValues.length > 6">… {{ format(axisValues[axisValues.length - 1]!) }}</span></div><p v-if="scan.axis === 'resolution'" class="hint">R 逐帧取整；小跨度可能出现相同整数帧。</p></fieldset><div class="divider" /><ParameterEditor v-model="scan.params" scope="scan" :disabled="disabled" :hide-te="scan.axis === 'te'" :hide-ne="scan.axis === 'ne'" :hide-r="scan.axis === 'resolution'" :te-override="scan.axis === 'te' ? Number(scan.from) : undefined" :ne-override="scan.axis === 'ne' ? Number(scan.from) : undefined" :r-override="scan.axis === 'resolution' ? Number(scan.from) : undefined" /><div class="divider" /><CompositionEditor v-model="scan.composition" scope="scan" :disabled="disabled" @issue="compositionError = $event" /><button class="btn primary full" :disabled="!!running || !!inputError" @click="run"><AppIcon name="scan" :size="17" />生成扫描</button></template>
<template #spectrum><SpectrumChart v-if="currentFrame" :spectrum="currentFrame.spectrum" :label="`光谱预览 · 第 ${scan.frame + 1} 帧`" /><section v-else class="panel empty-state scan-empty"><EmptyStateArt /><h3>尚无扫描结果</h3><p>设定扫描轴与区间后点击“生成扫描”。</p></section></template>
  <TaskActivity kind="scan" :error="inputError || compositionError || submitError || scan.error" />
<div v-if="currentFrame" class="scan-frame-banner"><span>采样帧 <b class="mono">{{ String(scan.frame + 1).padStart(2,'0') }} / {{ scan.result!.frames.length }}</b></span><strong>{{ resultLabel.name }}{{ resultLabel.unit ? ' / ' + resultLabel.unit : '' }} <span class="mono">{{ format(currentFrame.value) }}</span></strong></div>
    <button v-if="scan.error" class="btn sm" @click="setFrame(requestedFrame)">重试读取帧</button><p v-if="scan.loading" class="hint">正在加载光谱帧…</p><p v-if="saveFeedback" :class="saveFailed ? 'error-text' : 'hint'">{{ saveFeedback }}</p><section class="panel playback-panel"><div class="panel-heading"><h2>参数时间轴</h2><span class="badge neutral">{{ playing ? '播放中' : currentFrame ? '可播放' : '未生成' }}</span></div><div class="timeline-labels"><span class="mono">{{ scan.result ? format(scan.result.frames[0]!.value) : '起点' }}</span><span>{{ scan.result ? resultLabel.name : '采样帧' }}</span><span class="mono">{{ scan.result ? format(scan.result.frames[scan.result.frames.length - 1]!.value) : '终点' }}</span></div><input type="range" aria-label="扫描时间轴" :min="0" :max="(scan.result?.frames.length ?? 1) - 1" :step="1" :value="scan.frame" :disabled="!scan.result" @input="setFrame(Number(($event.target as HTMLInputElement).value))" /><div class="playback-controls"><div class="playback-buttons"><button class="icon-btn" aria-label="上一帧" :disabled="!scan.result || scan.loading || scan.frame === 0" @click="setFrame(scan.frame - 1)"><AppIcon name="prev" /></button><button class="btn primary play-button" :aria-label="playing ? '暂停扫描' : '播放扫描'" :disabled="!scan.result || !!running" @click="play"><AppIcon :name="playing ? 'pause' : 'play'" :size="19" /></button><button class="icon-btn" aria-label="下一帧" :disabled="!scan.result || scan.loading || scan.frame >= scan.result.frames.length - 1" @click="setFrame(scan.frame + 1)"><AppIcon name="next" /></button></div><ChoiceSelect v-model="interval" class="playback-speed" label="帧间隔" :options="intervalChoices" /></div><p class="hint">扫描 R 线宽需启用本地展宽。</p></section><section class="panel activity-panel"><div class="panel-heading"><h2>扫描导出</h2></div><div class="backend-action"><button class="btn" :disabled="!scan.result || saving" @click="saveGif">导出 GIF 动画</button><span class="hint">完整扫描动画；当前帧可保存 CSV / JSON / PNG。</span></div></section>
</WorkbenchLayout></template>
