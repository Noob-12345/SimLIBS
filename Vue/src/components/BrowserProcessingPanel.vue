<script setup lang="ts">
import { computed, onUnmounted, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import ChoiceSelect from './ChoiceSelect.vue'
import { spectrumBrowser as state, runProcessing, cancelProcessing, clearProcessing, setProcessingTarget, processingParameters } from '../lib/spectrumBrowser'
const page=ref(0),pageSize=12
const id=useId()
const result=computed(()=>state.processingResult)
const rows=computed(()=>result.value?.peaks.slice(page.value*pageSize,(page.value+1)*pageSize)??[])
// Curve targets span every loaded file; value is docKey:curveId and the first
// colon always splits it because document keys are uuid hex without colons.
const targetOptions=computed(()=>state.docs.flatMap(doc=>doc.spectrum.curves.map(c=>({value:doc.key+':'+c.id,label:doc.name+' · '+c.label}))))
const targetValue=computed(()=>state.target?state.target.docKey+':'+state.target.curve:'')
const resultDoc=computed(()=>state.docs.find(d=>d.key===result.value?.docKey))
const resultOrphan=computed(()=>!!result.value&&!!result.value.docKey&&!state.docs.some(d=>d.key===result.value!.docKey))
function canonical(value:Record<string,unknown>){const p={...value};if(Array.isArray(p.scales))p.scales=[...new Set(p.scales)].sort((a,b)=>Number(a)-Number(b));const drift=p.drift_correction===true;if(!drift){delete p.max_degree;delete p.tolerance}for(const key of p.mode==='peaks'?['order','epsilon','max_iter']:!drift&&p.mode==='background'?['wavelet','scales','neighbor','min_length','threshold','window']:[])delete p[key];return JSON.stringify(Object.fromEntries(Object.entries(p).sort(([a],[b])=>a.localeCompare(b))))}
const stale=computed(()=>!!result.value&&canonical(processingParameters())!==canonical(result.value.parameters))
const wavelets=['mexh','morl','gaus1','gaus2'].map(value=>({value,label:value}))
const views=computed(()=>[{value:'original',label:'原始测量曲线'},...(result.value?.background?[{value:'background',label:'估计背景'},{value:'corrected',label:'扣背景曲线'}]:[]),...(result.value?.corrected_xs?[{value:'driftCorrected',label:'漂移校正曲线'}]:[])])
async function run(){page.value=0;await runProcessing()}
// BG/PF tiles are the only trigger: grey at start, click to activate and the
// processing runs immediately on the current curve; clicking again turns the
// tile grey and restores the original view. Both lit = background then peaks.
const tileState=ref<''|'background'|'peaks'|'both'>('')
const dcOn=ref(false)
const tileBgActive=computed(()=>tileState.value==='background'||tileState.value==='both')
const tilePfActive=computed(()=>tileState.value==='peaks'||tileState.value==='both')
const anyActive=computed(()=>tileState.value!==''||dcOn.value)
function autoRun(){
  if(!anyActive.value||!state.docs.length)return
  if(!state.target){
    const doc=state.docs.find(d=>d.key===state.activeKey)??state.docs[0]
    const curve=doc?.spectrum.curves[0]
    if(!doc||!curve)return
    setProcessingTarget(doc.key+':'+curve.id)
  }
  // Drift-only keeps the peaks stage alive: its peakfinding feeds the matcher.
  state.processing.mode=tileState.value||'peaks'
  state.processing.drift_correction=dcOn.value
  void run()
}
function toggleTile(kind:'background'|'peaks'){
  const cur=tileState.value
  tileState.value=kind==='background'
    ?(cur==='both'?'peaks':cur==='background'?'':cur==='peaks'?'both':'background')
    :(cur==='both'?'background':cur==='peaks'?'':cur==='background'?'both':'peaks')
  if(!anyActive.value){clearProcessing();return}
  autoRun()
}
function toggleDc(){dcOn.value=!dcOn.value;if(!anyActive.value){clearProcessing();return}autoRun()}
function onTargetChange(value:string){setProcessingTarget(value);autoRun()}
// Parameter edits re-run automatically after a short debounce.
let paramTimer:ReturnType<typeof setTimeout>|undefined
watch(()=>{const {mode,...rest}={...state.processing};return JSON.stringify(rest)},()=>{clearTimeout(paramTimer);paramTimer=setTimeout(()=>autoRun(),700)})
onUnmounted(()=>clearTimeout(paramTimer))
</script>
<template>
  <section class="panel processing-panel"><button type="button" class="processing-heading" :aria-controls="id" :aria-expanded="state.processingExpanded" @click="state.processingExpanded=!state.processingExpanded"><h2>光谱预处理</h2><span v-if="state.processingPending">处理中…</span><span v-else-if="state.processingError" class="error-text">处理失败</span><span v-else-if="result">{{ result.peaks.length }} 峰</span><AppIcon name="chevron" :size="14" :class="{expanded:state.processingExpanded}" /></button><div :id="id" v-show="state.processingExpanded" class="processing-body">
    <template v-if="state.docs.length&&targetOptions.length"><ChoiceSelect :model-value="targetValue" label="处理原始曲线（文件 · 曲线）" :options="targetOptions" :disabled="state.processingPending||state.importing" @update:model-value="onTargetChange" />
      <div class="processing-mode-tiles" role="group" aria-label="处理步骤"><button type="button" :class="['mode-tile','tile-bg',{'tile-active':tileBgActive}]" :aria-pressed="tileBgActive" :disabled="state.processingPending" @click="toggleTile('background')"><b>BG</b><span>去背景</span></button><button type="button" :class="['mode-tile','tile-pf',{'tile-active':tilePfActive}]" :aria-pressed="tilePfActive" :disabled="state.processingPending" @click="toggleTile('peaks')"><b>PF</b><span>小波寻峰</span></button><button type="button" :class="['mode-tile','tile-dc',{'tile-active':dcOn}]" :aria-pressed="dcOn" :disabled="state.processingPending" @click="toggleDc"><b>DC</b><span>漂移校正</span></button></div>
      <details class="processing-parameters"><summary>详细参数</summary><fieldset class="control-fieldset" :disabled="state.processingPending"><template v-if="state.processing.mode!=='peaks'"><div class="row2"><label class="field">交替阶数<input v-model="state.processing.order" inputmode="numeric" /></label><label class="field">最大迭代<input v-model="state.processing.max_iter" inputmode="numeric" /></label></div><label class="field">面积相对变化阈值<input v-model="state.processing.epsilon" inputmode="decimal" /></label></template><template v-if="state.processing.mode!=='background'||dcOn"><ChoiceSelect v-model="state.processing.wavelet" label="连续小波" :options="wavelets" /><label class="field">尺度（样本点，逗号分隔）<input v-model="state.processing.scales" /></label><div class="row2"><label class="field">脊线邻域<input v-model="state.processing.neighbor" inputmode="numeric" /></label><label class="field">最短脊线<input v-model="state.processing.min_length" inputmode="numeric" /></label></div><div class="row2"><label class="field">小波系数阈值<input v-model="state.processing.threshold" inputmode="decimal" /></label><label class="field">峰位修正窗口<input v-model="state.processing.window" inputmode="numeric" /></label></div></template><template v-if="dcOn"><div class="row2"><label class="field">拟合阶数上限（1–3）<input v-model="state.processing.max_degree" inputmode="numeric" /></label><label class="field">匹配容差 / nm<input v-model="state.processing.tolerance" inputmode="decimal" /></label></div><p class="hint">检测峰位与当前勾选显示的参考谱线位置在容差内贪心一对一配对；理论位置来自谱线位置参考（本地库/NIST/用户 CSV）。</p></template></fieldset></details>
      <div class="processing-actions"><button v-if="state.processingPending" type="button" class="btn" @click="cancelProcessing">取消处理</button><button type="button" class="btn" @click="state.processingView='original'">恢复原始视图</button></div><p v-if="state.processingPending" class="hint" role="status">正在自动处理当前曲线…</p><p v-if="state.processingError" class="error-text" role="alert">{{ state.processingError }}</p><p class="hint">点击 BG／PF／DC 模块即自动处理；未选曲线时自动使用当前选中文件的第一条曲线。参数修改后自动重跑。DC 点亮时先寻峰再与勾选的参考谱线位置匹配做多项式重标定；BG+DC 组合先扣背景再在校正信号上寻峰匹配；主图读数 x 仍显示原始波长。</p>
      <template v-if="result"><ChoiceSelect v-model="state.processingView" label="主图／概览显示" :options="views" /><p class="hint">{{ resultDoc?.name ?? '已移除文件' }} · {{ result.peaks.length }} 个峰 · 背景 {{ result.iterations }} 次迭代<span v-if="result.iteration_limit_reached">（已到上限，未收敛）</span><span v-else-if="result.iterations">（面积停止条件已满足，不代表逐点收敛）</span><span v-if="result.drift_model"> · 匹配 {{ result.drift_model.matched_line_count }} 条 · 阶数 {{ result.drift_model.degree }}</span></p><p v-if="stale" class="hint">参数已编辑；将自动重新处理。</p><p v-if="resultOrphan" class="hint">所属文件已移除；结果仅保留显示，重新选择曲线后更新。</p><details><summary>峰表与处理来源</summary><p class="hint">输入曲线 {{ result.curve }} · {{ result.source.unit }} · SHA256 {{ result.source.sha256.slice(0,12) }}…</p><div class="processing-table"><table><thead><tr><th>原节点</th><th>位置</th><th v-if="result.drift_model">校正后位置</th><th>处理输入强度</th><th>原始强度</th></tr></thead><tbody><tr v-for="(p,i) in rows" :key="i"><td>{{ p.index+1 }}</td><td>{{ p.x.toPrecision(7) }}</td><td v-if="result.drift_model">{{ p.corrected_x!==undefined?p.corrected_x.toPrecision(7):'—' }}</td><td>{{ p.intensity.toPrecision(7) }}</td><td>{{ p.original_intensity.toPrecision(7) }}</td></tr></tbody></table></div><p v-if="!result.peaks.length" class="hint">0 峰是有效结果；没有虚构峰位。</p><div class="pager"><span>{{ page+1 }}／{{ Math.max(1,Math.ceil(result.peaks.length/pageSize)) }}</span><div><button class="btn sm" :disabled="page===0" @click="page--">上一页</button><button class="btn sm" :disabled="(page+1)*pageSize>=result.peaks.length" @click="page++">下一页</button></div></div><pre>{{ JSON.stringify(result.parameters,null,2) }}</pre><p class="hint">{{ result.note }}</p></details></template>
    </template><p v-else class="hint">先导入文件并成功选择测量曲线，再估计背景或寻峰。</p>
  </div></section>
</template>
<style scoped>
.processing-panel{padding:0;min-width:0}.processing-heading{display:flex;width:100%;align-items:center;gap:10px;padding:17px 20px;border:0;background:transparent;border-radius:13px;color:var(--text);text-align:left}.processing-heading h2{margin:0;margin-right:auto}.processing-heading span{font-size:11px;color:var(--muted)}.processing-heading svg{transition:transform .18s}.processing-heading svg.expanded{transform:rotate(90deg)}.processing-body{padding:0 20px 18px}.processing-panel .hint{margin:10px 0}.processing-mode-tiles{display:flex;gap:10px;margin:12px 0}.mode-tile{width:72px;height:72px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:1.5px solid var(--border);border-radius:10px;background:var(--panel-soft);color:var(--muted);cursor:pointer;transition:border-color .15s,background .15s,color .15s}.mode-tile b{font-family:var(--font-code);font-size:17px;font-weight:700;letter-spacing:.04em}.mode-tile span{font-size:10px}.mode-tile.tile-bg.tile-active{border-color:color-mix(in srgb,var(--good) 60%,var(--border));background:color-mix(in srgb,var(--good) 16%,var(--panel));color:var(--good)}.mode-tile.tile-pf.tile-active{border-color:color-mix(in srgb,var(--accent) 60%,var(--border));background:color-mix(in srgb,var(--accent) 16%,var(--panel));color:var(--accent-text)}.mode-tile.tile-dc.tile-active{border-color:color-mix(in srgb,var(--bad) 60%,var(--border));background:color-mix(in srgb,var(--bad) 16%,var(--panel));color:var(--bad)}.mode-tile:disabled{cursor:default;opacity:.7}.processing-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.processing-parameters{margin:12px 0}.processing-parameters .field{margin-top:10px}summary{cursor:pointer;color:var(--accent-text)}.processing-table{max-width:100%;overflow:auto}.processing-table table{font-size:11px}.processing-table th,.processing-table td{padding:8px;white-space:nowrap}.pager{flex-wrap:wrap}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:var(--muted)}@media(max-width:740px){.processing-heading{padding:16px}.processing-body{padding:0 16px 16px}}@media(prefers-reduced-motion:reduce){.mode-tile{transition:none}}
</style>
