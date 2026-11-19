<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import AppIcon from '../components/AppIcon.vue'
import ChoiceSelect from '../components/ChoiceSelect.vue'
import EmptyStateArt from '../components/EmptyStateArt.vue'
import BrowserSpectrumChart from '../components/BrowserSpectrumChart.vue'
import BrowserProcessingPanel from '../components/BrowserProcessingPanel.vue'
import BrowserReferencePanel from '../components/BrowserReferencePanel.vue'
import BrowserSidebar from '../components/BrowserSidebar.vue'
import { docColor, spectrumBrowser as state, activeDocument, browserSelectionInfo as info, importSpectrum, cancelSpectrum, clearDocuments, removeDocument, setActiveDocument, toggleDocumentVisible, updateSpectrumSelection as updateSelection, disposeSpectrumSelection, type AxisUnit } from '../lib/spectrumBrowser'
const input=ref<HTMLInputElement>()
const units:{value:AxisUnit;label:string}[]=[{value:'nm',label:'nm（纳米）'},{value:'angstrom',label:'Å（埃，×0.1 → nm）'},{value:'um',label:'μm（×1000 → nm）'},{value:'pixel',label:'pixel（像素，禁用nm参考）'}]
const duplicateChoices=[{value:'error',label:'重复波长：明确报错'},{value:'keep',label:'重复波长：保留每个原值'}]
const table=computed(()=>info.value?.tables[Number(state.sheet)])
const columns=computed(()=>table.value?.columns.map((label,i)=>({value:String(i),label:String(i+1)+' · '+label}))??[])
const frames=computed(()=>info.value?.frames.map(f=>({value:f.id,label:f.label}))??[])
const currentFrame=computed(()=>info.value?.frames.find(f=>f.id===state.frame))
const selectedReferences=computed(()=>state.references.filter(g=>state.selected.includes(g.id)))
const showControls=computed(()=>state.docs.length>0)
const appliedSelection=computed(()=>{
  const doc=activeDocument.value;if(!doc)return ''
  const s=doc.selection
  if(doc.info.frames.length)return doc.info.frames.find(f=>f.id===s.frame)?.label??s.frame
  return (doc.info.tables[Number(s.sheet)]?.name??'')+' · 轴列 '+(Number(s.x)+1)+' · 强度列 '+s.ys.map(v=>Number(v)+1).join(',')+' · 从原第'+s.start+'行'
})
const dotColor=(index:number)=>docColor(index,0,1,false)
async function choose(){if(isTauri())await importSpectrum();else input.value?.click()}
function file(event:Event){const target=event.target as HTMLInputElement,files=Array.from(target.files??[]);if(files.length)void importSpectrum(files);target.value=''}
function toggleColumn(value:string){updateSelection({ys:state.ys.includes(value)?state.ys.filter(y=>y!==value):[...state.ys,value]})}
function toggleVector(value:string){updateSelection({curves:state.curves.includes(value)?state.curves.filter(c=>c!==value):[...state.curves,value]})}
function setStart(event:Event){updateSelection({start:(event.target as HTMLInputElement).value})}
function setUnit(value:string){updateSelection({unit:value as AxisUnit})}
onBeforeUnmount(disposeSpectrumSelection)
</script>
<template>
  <div class="spectrum-browser">
    <div v-if="showControls" class="browser-toolbar"><div class="browser-current"><b>{{ activeDocument?.name }}</b><span>共 {{ state.docs.length }} 个文件 · {{ activeDocument?.spectrum.unit }} · {{ activeDocument?.spectrum.nodes.toLocaleString() }} 节点 · {{ appliedSelection }}</span></div><div class="browser-actions"><button type="button" class="btn open-success" :disabled="state.importing" @click="choose"><AppIcon name="folder" />打开文件</button><button type="button" class="btn" :disabled="state.importing" @click="clearDocuments"><AppIcon name="close" :size="13" />清空全部</button><button type="button" :class="['btn browser-cancel',{'is-idle':!state.pending}]" :disabled="!state.pending" :tabindex="state.pending?0:-1" :aria-hidden="!state.pending" @click="cancelSpectrum">取消</button></div></div>
    <input ref="input" class="file-input" type="file" multiple accept=".csv,.xlsx,.sif,.raw,.raw8,.roh,.trm,.abs,.ref,.drk" aria-label="选择测量光谱文件（可多选）" @change="file" />
    <p v-if="state.error" class="error-text" role="alert">{{ state.error }}<template v-if="state.docs.length">；已加载文件保留。</template></p>
    <p v-if="state.failedFiles.length" class="error-text" role="alert"><template v-for="(f,i) in state.failedFiles" :key="f.name+i">{{ f.name }}：{{ f.error }}<br /></template>其余文件已正常加载。</p>
    <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ state.pending?(state.importing?'正在逐个读取所选文件…':'正在更新光谱选择…'):state.notice }}</p>
    <BrowserSidebar v-if="showControls"><template #controls>
      <section class="panel browser-panel"><h2>已加载文件 · {{ state.docs.length }}</h2><p class="hint">点击行切换下方选择面板的文件；图例或行内按钮控制显示。</p>
        <div class="doc-list">
          <div v-for="doc in state.docs" :key="doc.key" :class="['doc-row',{active:doc.key===state.activeKey}]" role="button" tabindex="0" :aria-label="'选择文件 '+doc.name" @click="setActiveDocument(doc.key)" @keydown.enter.prevent="setActiveDocument(doc.key)">
            <i class="doc-dot" :class="{muted:!doc.visible}" :style="{background:dotColor(doc.colorIndex)}" :title="doc.visible?'显示中':'已隐藏'" />
            <span class="doc-name" :title="doc.name">{{ doc.name }}</span>
            <small class="doc-meta">{{ doc.spectrum.unit }} · {{ doc.spectrum.nodes.toLocaleString() }}</small>
            <button type="button" class="icon-btn" :aria-label="(doc.visible?'隐藏':'显示')+'文件 '+doc.name" :title="(doc.visible?'点击隐藏':'点击显示')+doc.name" @click.stop="toggleDocumentVisible(doc.key)"><AppIcon :name="doc.visible?'check':'close'" :size="13" /></button>
            <button type="button" class="icon-btn" :aria-label="'移除文件 '+doc.name" :title="'移除 '+doc.name" @click.stop="removeDocument(doc.key)"><AppIcon name="close" :size="13" /></button>
          </div>
        </div>
        <p v-if="activeDocument?.selectionError" class="error-text" role="alert">{{ activeDocument.name }}：{{ activeDocument.selectionError }}；上一成功光谱保留。</p>
      </section>
      <section v-if="info" class="panel browser-panel"><h2>数据选择 · 当前文件</h2><p class="hint">修改选择后自动更新，仅作用于当前选中的文件。</p><p class="browser-filename">{{ info.name }}</p><details><summary>来源与帮助</summary><p class="hint">保留原值；文件≤32MB、单谱≤1M节点／4M数值；最多同时缓存8个文件，超限自动淘汰最早文件（过期后需重新打开）。</p><p class="hint mono browser-hash">SHA256 {{ info.sha256 }}</p><pre>{{ JSON.stringify(info.metadata,null,2) }}</pre><pre v-if="currentFrame">{{ JSON.stringify(currentFrame.metadata,null,2) }}</pre></details>
        <template v-if="info.tables.length"><ChoiceSelect :model-value="state.sheet" label="工作表" :options="info.tables.map((t,i)=>({value:String(i),label:t.name}))" :disabled="state.importing" @update:model-value="updateSelection({sheet:$event})" /><label class="field">数据起始行（原行号）<input :value="state.start" :disabled="state.importing" inputmode="numeric" aria-label="数据起始行" @input="setStart" /></label><ChoiceSelect :model-value="state.x" label="波长／像素列" :options="columns" :disabled="state.importing" @update:model-value="updateSelection({x:$event})" /><fieldset class="browser-multi"><legend>强度列（可多选，最多16）</legend><label v-for="c in columns" :key="c.value"><input type="checkbox" :checked="state.ys.includes(c.value)" :value="c.value" :disabled="state.importing||c.value===state.x && !state.ys.includes(c.value)" @change="toggleColumn(c.value)" />{{ c.label }}</label></fieldset><ChoiceSelect :model-value="state.unit" label="原轴单位（明确选择）" :options="units" :disabled="state.importing" @update:model-value="setUnit" /><details v-if="table"><summary>原始行预览</summary><div class="browser-preview"><div v-for="r in table.preview" :key="r.line"><b>{{ r.line }}</b> {{ r.values.join(' | ') }}</div></div></details></template>
        <template v-else><ChoiceSelect :model-value="state.frame" label="帧／ROI／轨道／通道" :options="frames" :disabled="state.importing" @update:model-value="updateSelection({frame:$event})" /><fieldset class="browser-multi"><legend>原始存储向量（不扣暗、不处理）</legend><label v-for="c in currentFrame?.curves" :key="c"><input type="checkbox" :checked="state.curves.includes(c)" :value="c" :disabled="state.importing" @change="toggleVector(c)" />{{ c }}</label></fieldset><p class="hint">{{ currentFrame?.unit }} · {{ currentFrame?.nodes.toLocaleString() }} 节点</p></template>
        <ChoiceSelect :model-value="state.duplicates" label="重复波长处理" :options="duplicateChoices" :disabled="state.importing" @update:model-value="updateSelection({duplicates:$event})" />
      </section>
      <BrowserProcessingPanel /><BrowserReferencePanel />
    </template><div class="browser-results"><BrowserSpectrumChart v-model:view="state.view" :docs="state.docs" :references="selectedReferences" /></div></BrowserSidebar>
    <section v-else class="panel empty-state browser-import-empty" aria-label="导入测量光谱"><div class="browser-import-intro"><EmptyStateArt /><h3>尚未导入测量光谱</h3><p>一次选择多个 CSV、XLSX、SIF 或 Avantes 文件，按不同颜色叠加显示。</p></div><div class="browser-actions"><button type="button" class="btn primary" :disabled="state.importing" @click="choose"><AppIcon name="folder" />打开文件</button><button v-if="state.pending" type="button" class="btn" @click="cancelSpectrum">取消</button></div></section>
  </div>
</template>
<style scoped>
.spectrum-browser{min-width:0;display:flex;flex-direction:column;gap:16px}.browser-toolbar{padding:18px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.browser-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.browser-layout{display:grid;grid-template-columns:292px minmax(0,1fr);gap:22px;align-items:start;min-width:0}.browser-settings,.browser-results{display:flex;flex-direction:column;gap:18px;min-width:0}.browser-panel{padding:18px 20px;min-width:0}.browser-panel>h2{margin-bottom:12px}.browser-panel>details,.browser-panel>.field,.browser-panel>.browser-multi{margin:12px 0}.browser-filename{font-weight:600;overflow-wrap:anywhere}.browser-hash{overflow-wrap:anywhere;font-size:11px}.browser-multi{border:1px solid var(--border);border-radius:8px;padding:10px;max-height:240px;overflow:auto;display:flex;flex-direction:column;gap:7px}.browser-multi legend{color:var(--muted);padding:0 5px}.browser-multi label{display:flex;gap:8px;align-items:center}.browser-panel pre{max-height:200px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:var(--muted);padding:8px;background:var(--panel-soft);border-radius:6px}.browser-preview{max-height:190px;overflow:auto;font-size:11px;overflow-wrap:anywhere}.doc-list{display:flex;flex-direction:column;gap:4px;margin:10px 0}.doc-row{display:flex;align-items:center;gap:8px;padding:7px 9px;border:1px solid var(--border);border-radius:8px;cursor:pointer;min-width:0}.doc-row:hover{background:var(--panel-soft)}.doc-row.active{border-color:var(--accent);background:var(--accent-soft)}.doc-dot{width:11px;height:11px;flex:none;border-radius:3px;border:1px solid color-mix(in srgb,var(--text) 25%,transparent)}.doc-dot.muted{background:var(--border)!important;filter:grayscale(1)}.doc-name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;font-weight:600}.doc-meta{flex:none;color:var(--muted);font-size:10px}.doc-row .icon-btn{width:24px;height:24px;flex:none}.browser-current{display:flex;flex-direction:column;gap:4px;min-width:0}.browser-current b{overflow-wrap:anywhere}.browser-current span{font-size:12px;color:var(--muted)}.file-input{display:none}details summary{cursor:pointer;color:var(--accent-text)}@media(max-width:1100px){.browser-layout{grid-template-columns:260px minmax(0,1fr);gap:16px}.browser-panel{padding:16px}}@media(max-width:740px){.browser-layout{grid-template-columns:minmax(0,1fr)}.browser-settings{order:2}.browser-results{order:1}.browser-toolbar{padding:15px}}
</style>
<style scoped>
.browser-toolbar>.browser-actions{flex:0 0 auto;flex-wrap:nowrap}.browser-cancel.is-idle{visibility:hidden;pointer-events:none}.browser-current{flex:1 1 240px}
</style>
<style scoped>
.empty-state.panel.browser-import-empty{position:relative;min-height:calc(100dvh - 128px);width:100%;align-self:center}.browser-import-intro{position:absolute;bottom:calc(50% + 34px);left:20px;right:20px;display:flex;flex-direction:column;align-items:center}.browser-import-empty>.browser-actions{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);margin:0;flex-wrap:nowrap;white-space:nowrap}.open-success{background:var(--good);border-color:var(--good);color:var(--panel)}.open-success:hover:not(:disabled){background:color-mix(in srgb,var(--good) 85%,var(--text));border-color:var(--good)}
@media(max-width:740px){.empty-state.panel.browser-import-empty{min-height:calc(100dvh - 99px)}}
</style>
