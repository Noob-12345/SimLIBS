<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import AppIcon from '../components/AppIcon.vue'
import ChoiceSelect from '../components/ChoiceSelect.vue'
import EmptyStateArt from '../components/EmptyStateArt.vue'
import BrowserSpectrumChart from '../components/BrowserSpectrumChart.vue'
import BrowserProcessingPanel from '../components/BrowserProcessingPanel.vue'
import BrowserReferencePanel from '../components/BrowserReferencePanel.vue'
import BrowserSidebar from '../components/BrowserSidebar.vue'
import { spectrumBrowser as state, browserSelectionInfo as info, importSpectrum, applySpectrum, cancelSpectrum, sheetDefaults, frameDefaults } from '../lib/spectrumBrowser'
const input=ref<HTMLInputElement>()
const units=[{value:'nm',label:'nm（纳米）'},{value:'angstrom',label:'Å（埃，×0.1 → nm）'},{value:'um',label:'μm（×1000 → nm）'},{value:'pixel',label:'pixel（像素，禁用nm参考）'}]
const duplicateChoices=[{value:'error',label:'重复波长：明确报错'},{value:'keep',label:'重复波长：保留每个原值'}]
const table=computed(()=>info.value?.tables[Number(state.sheet)])
const columns=computed(()=>table.value?.columns.map((label,i)=>({value:String(i),label:String(i+1)+' · '+label}))??[])
const frames=computed(()=>info.value?.frames.map(f=>({value:f.id,label:f.label}))??[])
const currentFrame=computed(()=>info.value?.frames.find(f=>f.id===state.frame))
const selectedReferences=computed(()=>state.references.filter(g=>state.selected.includes(g.id)))
watch(()=>state.x,value=>{state.ys=state.ys.filter(y=>y!==value)})
const appliedSelection=computed(()=>{const s=state.committed;if(!s)return '';if(state.info?.frames.length)return state.info.frames.find(f=>f.id===s.frame)?.label??s.frame;return (state.info?.tables[Number(s.sheet)]?.name??'')+' · 轴列 '+(Number(s.x)+1)+' · 强度列 '+s.ys.map(v=>Number(v)+1).join(',')+' · 从原第'+s.start+'行'})
async function choose(){if(isTauri())await importSpectrum();else input.value?.click()}
function file(event:Event){const target=event.target as HTMLInputElement,f=target.files?.[0];if(f)void importSpectrum(f);target.value=''}
function setSheet(value:string){state.sheet=value;sheetDefaults()}
function setFrame(value:string){state.frame=value;frameDefaults()}
</script>
<template>
  <div class="spectrum-browser">
    <div class="browser-toolbar"><div class="browser-current"><b>{{ state.spectrum?.name || '测量光谱' }}</b><span v-if="state.spectrum">{{ state.spectrum.unit }} · {{ state.spectrum.nodes.toLocaleString() }} 节点 · {{ appliedSelection }}</span></div><div class="browser-actions"><button type="button" class="btn primary" :disabled="state.pending" @click="choose"><AppIcon name="folder" />打开文件</button><button v-if="state.pending" type="button" class="btn" @click="cancelSpectrum">取消</button></div><input ref="input" class="file-input" type="file" accept=".csv,.xlsx,.sif,.raw,.raw8,.roh,.trm,.abs,.ref,.drk" aria-label="选择测量光谱文件" @change="file" /></div>
    <p v-if="state.error" class="error-text" role="alert">{{ state.error }}；上一成功光谱保留。</p><p v-if="state.pending" class="hint" role="status">正在读取／校验所选字节…</p><p v-else-if="state.notice" class="hint" role="status">{{ state.notice }}</p>
    <BrowserSidebar><template #controls>
      <section v-if="info" class="panel browser-panel"><h2>数据选择</h2><p v-if="state.candidate" class="hint">{{ info.name }} · 待应用</p><p class="browser-filename">{{ info.name }}</p><details><summary>来源与帮助</summary><p class="hint">选项应用后更新。保留原值；文件≤32MB、单谱≤1M节点／4M数值。</p><p class="hint mono browser-hash">SHA256 {{ info.sha256 }}</p><pre>{{ JSON.stringify(info.metadata,null,2) }}</pre><pre v-if="currentFrame">{{ JSON.stringify(currentFrame.metadata,null,2) }}</pre></details>
        <template v-if="info.tables.length"><ChoiceSelect :model-value="state.sheet" label="工作表" :options="info.tables.map((t,i)=>({value:String(i),label:t.name}))" :disabled="state.pending" @update:model-value="setSheet" /><label class="field">数据起始行（原行号）<input v-model="state.start" inputmode="numeric" aria-label="数据起始行" /></label><ChoiceSelect v-model="state.x" label="波长／像素列" :options="columns" :disabled="state.pending" /><fieldset class="browser-multi"><legend>强度列（可多选，最多16）</legend><label v-for="c in columns" :key="c.value"><input v-model="state.ys" type="checkbox" :value="c.value" :disabled="state.pending||c.value===state.x && !state.ys.includes(c.value)" />{{ c.label }}</label></fieldset><ChoiceSelect v-model="state.unit" label="原轴单位（明确选择）" :options="units" :disabled="state.pending" /><details v-if="table"><summary>原始行预览</summary><div class="browser-preview"><div v-for="r in table.preview" :key="r.line"><b>{{ r.line }}</b> {{ r.values.join(' | ') }}</div></div></details></template>
        <template v-else><ChoiceSelect :model-value="state.frame" label="帧／ROI／轨道／通道" :options="frames" :disabled="state.pending" @update:model-value="setFrame" /><fieldset class="browser-multi"><legend>原始存储向量（不扣暗、不处理）</legend><label v-for="c in currentFrame?.curves" :key="c"><input v-model="state.curves" type="checkbox" :value="c" :disabled="state.pending" />{{ c }}</label></fieldset><p class="hint">{{ currentFrame?.unit }} · {{ currentFrame?.nodes.toLocaleString() }} 节点</p></template>
        <ChoiceSelect v-model="state.duplicates" label="重复波长处理" :options="duplicateChoices" :disabled="state.pending" /><button type="button" class="btn full" :disabled="state.pending" @click="applySpectrum">应用选择</button>
      </section>
      <BrowserProcessingPanel /><BrowserReferencePanel />
    </template><div class="browser-results"><BrowserSpectrumChart v-if="state.spectrum" v-model:view="state.view" :spectrum="state.spectrum" :references="selectedReferences" /><section v-else class="panel empty-state"><EmptyStateArt /><h3>尚未导入测量光谱</h3><p>选择 CSV、XLSX、SIF 或 Avantes 文件。保留原节点与负强度，不生成模拟数据。</p></section></div></BrowserSidebar>
  </div>
</template>
<style scoped>
.spectrum-browser{min-width:0;display:flex;flex-direction:column;gap:16px}.browser-toolbar{padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.browser-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.browser-layout{display:grid;grid-template-columns:292px minmax(0,1fr);gap:22px;align-items:start;min-width:0}.browser-settings,.browser-results{display:flex;flex-direction:column;gap:18px;min-width:0}.browser-panel{padding:18px 20px;min-width:0}.browser-panel>h2{margin-bottom:12px}.browser-panel>details,.browser-panel>.field,.browser-panel>.browser-multi{margin:12px 0}.browser-filename{font-weight:600;overflow-wrap:anywhere}.browser-hash{overflow-wrap:anywhere;font-size:11px}.browser-multi{border:1px solid var(--border);border-radius:8px;padding:10px;max-height:240px;overflow:auto;display:flex;flex-direction:column;gap:7px}.browser-multi legend{color:var(--muted);padding:0 5px}.browser-multi label{display:flex;gap:8px;align-items:center}.browser-panel pre{max-height:200px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:var(--muted);padding:8px;background:var(--panel-soft);border-radius:6px}.browser-preview{max-height:190px;overflow:auto;font-size:11px;overflow-wrap:anywhere}.browser-elements{display:flex;gap:5px;flex-wrap:wrap;margin:12px 0}.browser-references{max-height:420px;overflow:auto;overscroll-behavior:contain}.browser-reference{display:flex;flex-direction:column;gap:3px;padding:9px 0;border-bottom:1px solid var(--border);overflow-wrap:anywhere}.browser-reference>span{display:flex;gap:7px;align-items:center}.browser-reference small{font-size:10px;color:var(--muted)}.browser-reference small.mono{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.browser-current{display:flex;flex-direction:column;gap:4px;min-width:0}.browser-current b{overflow-wrap:anywhere}.browser-current span{font-size:12px;color:var(--muted)}.file-input{display:none}details summary{cursor:pointer;color:var(--accent-text)}@media(max-width:1100px){.browser-layout{grid-template-columns:260px minmax(0,1fr);gap:16px}.browser-panel{padding:16px}}@media(max-width:740px){.browser-layout{grid-template-columns:minmax(0,1fr)}.browser-settings{order:2}.browser-results{order:1}.browser-toolbar{padding:15px}.browser-references{max-height:260px}}
</style>
