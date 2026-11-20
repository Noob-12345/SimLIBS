<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import AppIcon from './AppIcon.vue'
import ChoiceSelect from './ChoiceSelect.vue'
import ElementCandidate from './ElementCandidate.vue'
import { elementColor, symbols } from '../lib/model'
import { spectrumBrowser as state, primaryUnit, setReferenceSource, sourceAllowed, loadReferences, loadNistReferences, cancelReferences, addReferenceElement, toggleReferenceElement, toggleReferenceSpecies } from '../lib/spectrumBrowser'
const id=useId(),input=ref<HTMLInputElement>(),adding=ref(''),error=ref(''),nistExpanded=ref(false)
// Reference lists follow the exclusive source switch: inactive-source groups
// stay cached but disappear from the candidate/display lists.
const scopedGroups=computed(()=>state.references.filter(sourceAllowed))
// The add form offers elements that have lines of the current mode's source not
// yet explicitly loaded there — including elements first added from the other
// source, so both line sets can coexist side by side.
const availableSymbols=computed(()=>{
  const kinds=state.referenceSource==='nist'?['nist','user']:['configured','user']
  const out:string[]=[]
  for(const g of state.references){
    if(!kinds.includes(g.originKind??''))continue
    if(g.originKind!=='user'&&(state.elementLoaded[g.element]??[]).includes(g.originKind as 'configured'|'nist'))continue
    if(!out.includes(g.element))out.push(g.element)
  }
  return out
})
const sourceGroups=computed(()=>scopedGroups.value.filter(g=>state.addedElements.includes(g.element)))
// Tiles only list elements whose bound source matches the active mode.
const panelElements=computed(()=>state.addedElements.filter(element=>scopedGroups.value.some(g=>g.element===element)))
// Heading badge follows the active source: NIST mode reports the online fetch
// result (green ok / red failed), local mode keeps the loaded-library badge.
const headingStatus=computed(()=>{
  // NIST loading is already reported by the progress banner under the grid;
  // showing the heading badge too would duplicate it.
  if(state.nistPending)return null
  if(state.referencePending)return {cls:'',text:'加载中…'}
  if(state.referenceSource==='nist'){
    if(state.nistOk===true)return {cls:'reference-success',text:'NIST 谱线库连接正常'}
    if(state.nistOk===false)return {cls:'reference-error',text:'NIST 谱线库连接失败'}
    return null
  }
  if(state.referenceError)return {cls:'reference-error',text:'加载失败'}
  if(state.configuredLoaded)return {cls:'reference-success',text:'本地库 · '+state.configuredCount+' 位置'}
  if(state.references.length)return {cls:'',text:'参考组 · '+state.references.length}
  return null
})
// Elements already fetched from NIST stay highlighted in the chip grid.
const loadedNistElements=computed(()=>[...new Set(state.references.filter(g=>g.originKind==='nist').map(g=>g.element))])
function chooseLocal(){setReferenceSource('local');nistExpanded.value=false;void loadReferences()}
function chooseNist(){setReferenceSource('nist');nistExpanded.value=!nistExpanded.value}
const units=[{value:'nm',label:'nm'},{value:'angstrom',label:'Å（×0.1 → nm）'},{value:'um',label:'μm（×1000 → nm）'}]
const enabled=(element:string)=>state.references.some(g=>g.element===element&&state.selected.includes(g.id))
function add(){const symbol=availableSymbols.value.find(e=>e.toLowerCase()===adding.value.trim().toLowerCase());if(!symbol){error.value='请选择当前已加载库中的元素';return}addReferenceElement(symbol);adding.value='';error.value=''}
async function choose(){if(isTauri())await loadReferences(undefined,true);else input.value?.click()}
function file(event:Event){const target=event.target as HTMLInputElement,f=target.files?.[0];if(f)void loadReferences(f,true);target.value=''}
</script>
<template>
  <section class="panel reference-panel">
    <button type="button" class="reference-heading" :aria-expanded="state.referencesExpanded" :aria-controls="id" @click="state.referencesExpanded=!state.referencesExpanded"><h2>谱线位置参考</h2><span v-if="headingStatus" :class="headingStatus.cls" role="status">{{ headingStatus.text }}</span><AppIcon name="chevron" :size="14" :class="{expanded:state.referencesExpanded}" /></button>
    <div :id="id" v-show="state.referencesExpanded" class="reference-body">
      <div class="reference-actions"><div class="reference-entry-grid"><button type="button" :class="['btn',{'reference-source-active':state.referenceSource==='local'}]" :aria-pressed="state.referenceSource==='local'" :disabled="state.referencePending||state.nistPending" @click="chooseLocal">{{ state.referencePending?'正在加载…':'本地谱线库' }}</button><button type="button" :class="['btn',{'reference-source-active':state.referenceSource==='nist'}]" :aria-pressed="state.referenceSource==='nist'" :disabled="state.referencePending||state.nistPending" :aria-expanded="nistExpanded" :aria-controls="id+'-nist'" title="选择元素并从 NIST Handbook Persistent Lines 加载 I/II" @click="chooseNist">NIST 在线谱线库</button></div><div v-if="state.referencePending||state.nistPending" class="reference-secondary-actions"><button type="button" class="btn reference-cancel" @click="cancelReferences">取消</button></div></div>
      <p v-if="state.referenceError" class="error-text" role="alert">{{ state.referenceError }}<span v-if="state.references.length">；上次成功数据保留。</span></p>
      <div v-if="nistExpanded" :id="id+'-nist'" class="nist-online"><div :class="['nist-element-grid',{'grid-loading':state.nistPending}]"><button v-for="symbol in symbols" :key="symbol" type="button" :class="['element-tile','nist-element',{'nist-element-loaded':loadedNistElements.includes(symbol),'nist-element-loading':state.nistPending&&state.nistElement===symbol}]" :style="{'--el-color':elementColor(symbol)}" :disabled="state.referencePending||state.nistPending" :aria-busy="state.nistPending&&state.nistElement===symbol" :aria-label="loadedNistElements.includes(symbol)?'刷新 NIST '+symbol:'加载 NIST '+symbol" :title="loadedNistElements.includes(symbol)?symbol+'（已加载，点击刷新）':symbol" @click="loadNistReferences(symbol)">{{ symbol }}</button></div><div v-if="state.nistPending" class="nist-loading" role="status"><span class="nist-loading-spinner" aria-hidden="true" /><b>正在从 NIST 加载 {{ state.nistElement }}</b><div class="nist-loading-track"><span class="nist-loading-bar" /></div></div><small v-for="issue in state.nistIssues" :key="issue.file" class="error-text">{{ issue.file }}：{{ issue.error }}</small></div><form v-if="state.references.length&&state.referenceSource!=='nist'" class="add-element" @submit.prevent="add"><ElementCandidate :id="id+'-element'" v-model="adding" :symbols="availableSymbols" :disabled="state.referencePending||state.nistPending" :issue="error" /><button type="submit" class="btn sm" :disabled="!availableSymbols.length">添加</button></form><p v-if="error&&state.referenceSource!=='nist'" class="error-text" role="alert">{{ error }}</p>
      <div class="reference-elements"><div v-for="element in panelElements" :key="element" class="reference-element"><button type="button" :class="['element-tile',{'element-muted':!enabled(element)}]" :style="{'--el-color':elementColor(element)}" :aria-pressed="enabled(element)" :aria-label="(enabled(element)?'关闭':'启用')+'参考元素 '+element" :title="'点击启用／关闭 '+element" @click="toggleReferenceElement(element)">{{ element }}</button><div class="reference-species"><label v-for="group in scopedGroups.filter(g=>g.element===element)" :key="group.id" :title="group.source"><input type="checkbox" :checked="state.selected.includes(group.id)" :aria-label="'参考 '+group.label" @change="toggleReferenceSpecies(group.id)" /><span>{{ group.species }}</span><small>{{ group.originKind==='nist'?'NIST':group.originKind==='user'?'CSV':'本地' }} · {{ group.count }}</small></label></div></div></div>
      <details v-for="group in sourceGroups.filter(g=>g.originKind==='nist')" :key="group.id" class="nist-originals"><summary>{{ group.label }} · 来源与原字段</summary><p class="hint">{{ group.source }}<br />获取时间：{{ group.metadata?.fetched_at }}<br />HTML SHA256：{{ group.sha256 }}<br />波长原值 Å，仅除以10转换为 nm，不推断空气/真空介质。</p><details v-for="position in group.positions" :key="position.wavelength_nm"><summary>{{ position.wavelength_angstrom }} Å · {{ position.wavelength_nm }} nm</summary><article v-for="(record,i) in position.records" :key="i"><dl v-for="row in record.states" :key="row.line"><dt>页面行</dt><dd>{{ row.line }}</dd><dt>Intensity</dt><dd>{{ row.intensity||'—' }}</dd><dt>Å 原值</dt><dd>{{ row.wavelength_angstrom||'（该行未重复列出）' }}</dd><dt>Aki</dt><dd>{{ row.aki||'—' }} {{ row.aki_unit }}</dd><dt>Energy</dt><dd>{{ row.energy||'—' }} {{ row.energy_unit }}</dd><dt>Configuration</dt><dd>{{ row.configuration||'—' }}</dd><dt>Term / J</dt><dd>{{ row.term||'—' }} / {{ row.j||'—' }}</dd><dt>Line Ref</dt><dd>{{ row.line_ref||'—' }}</dd><dt>Aki Ref</dt><dd>{{ row.aki_ref||'—' }}</dd></dl></article></details></details>
      <p v-if="primaryUnit==='pixel'" class="hint">pixel 轴不叠加 nm 参考。</p>
      <details><summary>用户参考 CSV／来源</summary><div class="row2"><label class="field">元素（可留空）<input v-model="state.userElement" placeholder="Fe" /></label><label class="field">species（可留空）<input v-model="state.userSpecies" placeholder="II" /></label></div><label class="field">波长列（从0开始）<input v-model="state.userColumn" inputmode="numeric" /></label><ChoiceSelect v-model="state.userUnit" label="参考波长原单位" :options="units" /><button type="button" class="btn sm" :disabled="state.referencePending" @click="choose">打开用户参考 CSV</button><input ref="input" type="file" accept=".csv" class="reference-file" aria-label="选择参考谱线CSV" @change="file" /><p class="hint">虚线仅位置，不是元素鉴定。悬停可读库原字段；无 Aki 的线仍显示。</p><p v-for="issue in state.referenceIssues" :key="issue.file" class="hint">{{ issue.file }}：{{ issue.error }}</p><div v-for="group in sourceGroups" :key="group.id" class="reference-source"><b>{{ group.label }}</b> · {{ group.source }} · {{ group.original_unit }} → nm<small>{{ group.unit_contract }}</small><small class="mono">SHA256 {{ group.sha256 }}</small></div></details>
    </div>
  </section>
</template>
<style scoped>
.reference-panel{padding:0;min-width:0}.reference-heading{width:100%;display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:17px 20px;border:0;border-radius:13px;background:transparent;color:var(--text);text-align:left}.reference-heading h2{margin:0;margin-right:auto}.reference-heading>span{font-size:11px;color:var(--muted)}.reference-heading>svg{transition:transform .18s}.reference-heading>svg.expanded{transform:rotate(90deg)}.reference-heading .reference-success{color:var(--good)}.reference-heading .reference-error{color:var(--bad)}.reference-body{padding:0 20px 18px}.reference-actions{display:flex;flex-direction:column;gap:8px;margin-bottom:14px}.reference-entry-grid{display:flex;gap:8px;min-width:0}.reference-entry-grid>.btn{flex:1 1 0;min-width:0;white-space:normal;line-height:1.35}.reference-secondary-actions{display:flex;gap:8px;min-height:36px}.reference-source-active{color:var(--good);border-color:color-mix(in srgb,var(--good) 55%,var(--border));background:color-mix(in srgb,var(--good) 14%,var(--panel))}.nist-button{color:var(--accent-text)}.nist-online{display:flex;flex-direction:column;gap:6px;margin:12px 0}.nist-element-grid{display:flex;flex-wrap:wrap;gap:4px;max-height:220px;overflow:auto;overscroll-behavior:contain}.nist-element-grid.grid-loading .nist-element:not(.nist-element-loading){opacity:.4}.nist-element{display:grid;place-items:center;width:38px;height:30px;padding:0;font-size:11px;font-weight:600;filter:grayscale(1);opacity:.75;background:var(--panel-soft);border:1px solid var(--border);border-radius:7px;color:var(--muted);cursor:pointer}.nist-element-loaded{filter:none;opacity:1;color:var(--text);border-color:color-mix(in srgb,var(--el-color) 60%,var(--border));background:color-mix(in srgb,var(--el-color) 12%,var(--panel))}.nist-element-loading{filter:none;opacity:1;border-color:var(--accent);color:var(--accent-text);background:color-mix(in srgb,var(--accent) 14%,var(--panel));animation:nist-pulse 1s ease-in-out infinite}.nist-loading{display:flex;align-items:center;gap:9px;margin:4px 0 0;padding:8px 11px;border:1px solid color-mix(in srgb,var(--accent) 40%,var(--border));border-radius:8px;background:color-mix(in srgb,var(--accent) 8%,var(--panel));font-size:12px}.nist-loading b{color:var(--accent-text);flex:none}.nist-loading-spinner{width:12px;height:12px;flex:none;border:2px solid color-mix(in srgb,var(--accent) 35%,transparent);border-top-color:var(--accent);border-radius:50%;animation:nist-spin .8s linear infinite}.nist-loading-track{flex:1;height:4px;border-radius:2px;background:var(--panel-soft);overflow:hidden}.nist-loading-bar{display:block;height:100%;width:40%;border-radius:2px;background:var(--accent);animation:nist-slide 1.1s ease-in-out infinite}@keyframes nist-pulse{50%{box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent)}}@keyframes nist-spin{to{transform:rotate(360deg)}}@keyframes nist-slide{0%{transform:translateX(-100%)}100%{transform:translateX(260%)}}@media(prefers-reduced-motion:reduce){.nist-element-loading,.nist-loading-spinner,.nist-loading-bar{animation:none}}:global(:root[data-reduced-motion=true]) .nist-element-loading,:global(:root[data-reduced-motion=true]) .nist-loading-spinner,:global(:root[data-reduced-motion=true]) .nist-loading-bar{animation:none}.nist-online small{color:var(--muted);font-size:10px}.reference-elements{display:flex;flex-wrap:wrap;gap:14px;margin:15px 0}.reference-element{display:flex;align-items:flex-start;gap:8px}.reference-species{display:flex;gap:6px;flex-wrap:wrap;max-width:170px}.reference-species label{display:flex;gap:4px;align-items:center;font-size:12px}.reference-species small{color:var(--muted);font-size:10px}.element-muted{--el-color:var(--muted)!important;filter:grayscale(1);background:var(--panel-soft);border-color:var(--border)}.reference-file{display:none}details{font-size:12px}summary{cursor:pointer;color:var(--accent-text)}details .field{margin-top:10px}.reference-source{margin:10px 0;overflow-wrap:anywhere;font-size:11px}.reference-source small{display:block;color:var(--muted);font-size:10px}.hint{margin:10px 0}@media(max-width:740px){.reference-heading{padding:16px}.reference-body{padding:0 16px 16px}}
</style>
<style scoped>
.reference-species label{max-width:100%;overflow-wrap:anywhere}.nist-originals{overflow-wrap:anywhere}.nist-originals dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:3px 8px;font-size:11px}.nist-originals dd{margin:0}.nist-originals article{margin:10px 0;border-top:1px solid var(--border);padding-top:8px}
</style>
