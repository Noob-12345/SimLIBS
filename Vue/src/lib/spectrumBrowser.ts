import { computed, markRaw, reactive } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { readFile, stat } from '@tauri-apps/plugin-fs'
import { request } from './backend'

export const MAX_FILE_BYTES = 32_000_000
export const MAX_NODES = 1_000_000, MAX_VALUES = 4_000_000
export type AxisUnit = 'nm' | 'angstrom' | 'um' | 'pixel'
export interface Measurement {
  name: string; format: string; sha256: string; unit: 'nm' | 'pixel'; nodes: number; xs: number[]
  curves: {id:string;label:string;ys:number[]}[]; provenance: Record<string,unknown>
}
export interface ReferenceState {line:number;role:string;aki?:string;aki_unit:string;energy?:string;energy_unit:string;configuration?:string;term?:string;j?:string;g?:string;intensity?:string;wavelength_angstrom?:string;line_ref?:string;aki_ref?:string}
export interface ReferencePosition {wavelength_nm:number;wavelength_angstrom?:string;records:{states:ReferenceState[]}[]}
export interface ReferenceGroup {id:string;element:string;species:string;label:string;xs:number[];positions:ReferencePosition[];source:string;sha256:string;original_unit:string;unit:string;count:number;unit_contract?:string;originKind?:'configured'|'user'|'nist';metadata?:Record<string,unknown>}
interface ImportInfo {
  document:string;name:string;format:string;sha256:string;bytes:number;metadata:Record<string,unknown>
  tables:{name:string;columns:string[];recommended_start:number;recommended_x:number;recommended_y:number[];preview:{line:number;values:string[]}[]}[]
  frames:{id:string;label:string;unit:string;nodes:number;curves:string[];metadata:Record<string,unknown>}[]
}
export interface ProcessingResult {algorithm:string;curve:string;parameters:Record<string,unknown>;source:{sha256:string;selection:Record<string,unknown>;unit:string};background:number[]|null;corrected:number[]|null;iterations:number;converged:boolean;iteration_limit_reached:boolean;last_change:number|null;peaks:{index:number;x:number;intensity:number;original_intensity:number}[];ridge_count:number;note:string;source_hashes:Record<string,string>;docKey?:string}
interface Selection {sheet:string;start:string;x:string;ys:string[];unit:AxisUnit;duplicates:string;frame:string;curves:string[]}
// One loaded file: its own server document, committed selection, visibility and
// per-curve hiding. Heavy payloads stay raw; the wrapper stays reactive so
// visibility/error toggles update the UI.
export interface LoadedDocument {
  key:string;name:string;format:string;sha256:string
  info:ImportInfo;spectrum:Measurement;selection:Selection
  visible:boolean;hiddenCurves:string[];colorIndex:number;selectionError:string
}
// File colors come from this hue cycle; curves within one file use lightness
// shades of the file hue (see docColor). Deleting a file never reassigns others.
export const DOC_HUES = [210,24,150,285,350,185,55,255,105,325,0,225,75,300,170,40]
export function docColor(colorIndex:number,curveIndex=0,curveCount=1,dark=false):string{
  const hue=DOC_HUES[colorIndex%DOC_HUES.length]!
  const spread=curveCount>1?(curveIndex-(curveCount-1)/2)*9:0
  const light=Math.max(25,Math.min(82,(dark?69:39)+spread))
  return 'hsl('+hue+' 68% '+light+'%)'
}
export const spectrumBrowser = reactive({
  docs:[] as LoadedDocument[], activeKey:'',
  view:null as [number,number]|null,
  // Draft selection fields, always describing the ACTIVE document.
  sheet:'0', start:'1', x:'0', ys:['1'] as string[], unit:'nm' as AxisUnit, duplicates:'error', frame:'', curves:[] as string[],
  references:[] as ReferenceGroup[], selected:[] as string[], referenceIssues:[] as {file:string;error:string}[], nistPending:false, nistElement:'Fe', nistIssues:[] as {file:string;error:string}[], nistStatus:'', referencePending:false, referenceError:'',
  addedElements:[] as string[], rememberedSpecies:{} as Record<string,string[]>,configuredIds:[] as string[],configuredLoaded:false,configuredCount:0,
  referencesExpanded:false,processingExpanded:false,sidebarCollapsed:false,
  pending:false, importing:false, error:'', notice:'', failedFiles:[] as {name:string;error:string}[],
  userElement:'',userSpecies:'',userUnit:'nm' as AxisUnit,userColumn:'0',
  target:null as {docKey:string;curve:string}|null,processingPending:false,processingError:'',processingResult:null as ProcessingResult|null,processingView:'original',
  processing:{mode:'both',order:'6',epsilon:'0.0001',max_iter:'1000',wavelet:'mexh',scales:'1,2,3,4,5,6,7',neighbor:'2',min_length:'2',threshold:'200',window:'3'}
})
export const browserSelectionInfo=computed(()=>spectrumBrowser.docs.find(d=>d.key===spectrumBrowser.activeKey)?.info??null)
export const activeDocument=computed(()=>spectrumBrowser.docs.find(d=>d.key===spectrumBrowser.activeKey)??null)
export const primaryUnit=computed<'nm'|'pixel'|null>(()=>spectrumBrowser.docs.find(d=>d.visible)?.spectrum.unit??null)
let revision=0, referenceRevision=0, controller:AbortController|undefined, referenceController:AbortController|undefined
let selectionTimer:ReturnType<typeof setTimeout>|undefined
let processingRevision=0,processingController:AbortController|undefined
let colorCounter=0
const api=<T>(action:string,body:unknown,signal?:AbortSignal)=>request<T>('/spectrum-browser/'+action,body,true,signal)
const fileName=(path:string)=>path.split(/[\\/]/).pop()||'selected-file'
async function selectedBytes():Promise<{name:string;bytes:Uint8Array}[]|null>{
  if(!isTauri())return null
  const paths=await open({multiple:true,directory:false,title:'选择测量光谱（可多选）',filters:[{name:'光谱文件',extensions:['csv','xlsx','sif','raw','raw8','roh','trm','abs','ref','drk']}]})
  if(!paths)return null
  const list=Array.isArray(paths)?paths:[paths]
  const out:{name:string;bytes:Uint8Array}[]=[]
  for(const path of list){
    const info=await stat(path)
    if(!info.isFile||info.size>MAX_FILE_BYTES||info.size===0)throw Error(`${fileName(path)}：请选择不超过32MB的非空文件`)
    out.push({name:fileName(path),bytes:await readFile(path)})
  }
  return out
}
function base64(bytes:Uint8Array){
  if(!bytes.length||bytes.length>MAX_FILE_BYTES)throw Error('文件为空或超过32MB')
  let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384))
  return btoa(binary)
}
function validate(measurement:Measurement){
  if(measurement.xs.length>MAX_NODES||measurement.xs.length*(measurement.curves.length+1)>MAX_VALUES)throw Error('测量节点超过限制')
  if(measurement.curves.some(c=>c.ys.length!==measurement.xs.length))throw Error('曲线与轴长度不一致')
  return markRaw(measurement)
}
async function browserFiles(files:File[]):Promise<{name:string;bytes:Uint8Array}[]>{
  const out:{name:string;bytes:Uint8Array}[]=[]
  for(const file of files){if(file.size===0||file.size>MAX_FILE_BYTES)throw Error(`${file.name}：请选择不超过32MB的非空文件`);out.push({name:file.name,bytes:new Uint8Array(await file.arrayBuffer())})}
  return out
}
function defaultSelection(info:ImportInfo):Selection{
  const selection:Selection={sheet:'0',start:'1',x:'0',ys:['1'],unit:'nm',duplicates:'error',frame:'',curves:[]}
  if(info.tables.length){const t=info.tables[0]!;selection.start=String(t.recommended_start);selection.x=String(t.recommended_x);selection.ys=t.recommended_y.map(String)}
  if(info.frames.length){const f=info.frames[0]!;selection.frame=f.id;selection.curves=[f.curves[0]!]}
  return selection
}
function loadSelectionDraft(doc:LoadedDocument){
  const s=spectrumBrowser;const selection=doc.selection
  s.sheet=selection.sheet;s.start=selection.start;s.x=selection.x;s.ys=[...selection.ys];s.unit=selection.unit
  s.duplicates=selection.duplicates;s.frame=selection.frame;s.curves=[...selection.curves]
}
export function sheetDefaults(){const t=browserSelectionInfo.value?.tables[Number(spectrumBrowser.sheet)];if(t){spectrumBrowser.start=String(t.recommended_start);spectrumBrowser.x=String(t.recommended_x);spectrumBrowser.ys=t.recommended_y.map(String)}}
export function frameDefaults(){const f=browserSelectionInfo.value?.frames.find(f=>f.id===spectrumBrowser.frame);if(f)spectrumBrowser.curves=[f.curves[0]!]}
function snapshot():Selection{const s=spectrumBrowser;return{sheet:s.sheet,start:s.start,x:s.x,ys:[...s.ys],unit:s.unit,duplicates:s.duplicates,frame:s.frame,curves:[...s.curves]}}
function optionsFrom(selection:Selection,info:ImportInfo){return info.frames.length?{frame:selection.frame,curves:selection.curves,duplicates:selection.duplicates}:{sheet:Number(selection.sheet),start:Number(selection.start),x:Number(selection.x),y:selection.ys.map(Number),unit:selection.unit,duplicates:selection.duplicates}}
function release(target:ImportInfo|string){const document=typeof target==='string'?target:target?.document;if(document)void api('release',{document}).catch(()=>{})}
function clearSelectionTimer(){clearTimeout(selectionTimer);selectionTimer=undefined}
// X fit: union of the visible documents' wavelength ranges for the primary unit.
export function refitView(){
  const s=spectrumBrowser,unit=primaryUnit.value
  const docs=s.docs.filter(d=>d.visible&&d.spectrum.unit===unit)
  if(!docs.length){s.view=null;return}
  const low=Math.min(...docs.map(d=>d.spectrum.xs[0]!)),high=Math.max(...docs.map(d=>d.spectrum.xs[d.spectrum.xs.length-1]!))
  s.view=low<high?[low,high]:null
}
function addDocument(info:ImportInfo,measurement:Measurement,selection:Selection){
  const s=spectrumBrowser
  const previous=s.docs.find(d=>d.sha256===info.sha256)
  const doc=reactive<LoadedDocument>({
    key:info.document,name:info.name,format:info.format,sha256:info.sha256,
    info:markRaw(info),spectrum:validate(measurement),selection:markRaw(selection),
    visible:previous?.visible??true,hiddenCurves:previous?previous.hiddenCurves.filter(id=>measurement.curves.some(c=>c.id===id)):[],
    colorIndex:previous?.colorIndex??colorCounter++%DOC_HUES.length,selectionError:''
  })
  if(previous){release(previous.key);s.docs.splice(s.docs.indexOf(previous),1)}
  s.docs.push(doc);s.activeKey=doc.key;loadSelectionDraft(doc);clearProcessing();refitView()
}
export function setActiveDocument(key:string){
  const doc=spectrumBrowser.docs.find(d=>d.key===key);if(!doc||key===spectrumBrowser.activeKey)return
  spectrumBrowser.activeKey=key;loadSelectionDraft(doc)
}
export function toggleDocumentVisible(key:string){
  const doc=spectrumBrowser.docs.find(d=>d.key===key);if(!doc)return
  doc.visible=!doc.visible;refitView()
}
export function toggleDocCurve(key:string,curveId:string){
  const doc=spectrumBrowser.docs.find(d=>d.key===key);if(!doc)return
  doc.hiddenCurves=doc.hiddenCurves.includes(curveId)?doc.hiddenCurves.filter(v=>v!==curveId):[...doc.hiddenCurves,curveId]
}
export function removeDocument(key:string){
  const s=spectrumBrowser,index=s.docs.findIndex(d=>d.key===key);if(index<0)return
  clearSelectionTimer();revision++;controller?.abort();release(key);s.docs.splice(index,1)
  if(s.activeKey===key){s.activeKey=s.docs[Math.min(index,s.docs.length-1)]?.key??'';const next=activeDocument.value;if(next)loadSelectionDraft(next)}
  if(s.processingResult?.docKey===key||s.target?.docKey===key)clearProcessing()
  refitView();s.notice='已移除文件；其余文件保留'
}
export function clearDocuments(){
  const s=spectrumBrowser
  clearSelectionTimer();revision++;controller?.abort()
  for(const doc of [...s.docs])release(doc.key)
  s.docs=[];s.activeKey='';s.view=null;clearProcessing();s.failedFiles=[];s.notice='已清空全部文件'
}
// Only user events call this function: defaults, commit and rollback never enqueue work.
export function updateSpectrumSelection(patch:Partial<Selection>){
  const s=spectrumBrowser;if(s.importing||!browserSelectionInfo.value)return
  Object.assign(s,patch)
  if(patch.sheet!==undefined)sheetDefaults()
  if(patch.frame!==undefined)frameDefaults()
  if(patch.x!==undefined)s.ys=s.ys.filter(y=>y!==s.x)
  clearSelectionTimer();revision++;controller?.abort();s.pending=true;s.error=''
  selectionTimer=setTimeout(()=>{selectionTimer=undefined;void applySpectrum()},patch.start!==undefined?220:0)
}
export function disposeSpectrumSelection(){
  clearSelectionTimer()
  if(spectrumBrowser.pending)cancelSpectrum()
}
export function cancelSpectrum(){clearSelectionTimer();revision++;controller?.abort();const s=spectrumBrowser;s.pending=false;s.importing=false;s.error='';s.notice=s.docs.length?'已取消；已加载文件保留':'已取消'}
export async function importSpectrum(files?:File|File[]){
  clearSelectionTimer()
  const id=++revision;controller?.abort();controller=new AbortController();const signal=controller.signal,s=spectrumBrowser
  s.pending=true;s.importing=true;s.error='';s.notice=''
  try{
    let chosen:{name:string;bytes:Uint8Array}[]
    if(files)chosen=await browserFiles(Array.isArray(files)?files:[files])
    else{const picked=await selectedBytes();if(id!==revision)return;if(!picked)return;chosen=picked}
    if(id!==revision)return
    s.failedFiles=[];let loaded=0
    // Serial on purpose: the backend allows two concurrent browser requests.
    for(const item of chosen){
      if(id!==revision)return
      try{
        const info=await api<ImportInfo>('import',{name:item.name,data:base64(item.bytes)},signal)
        if(id!==revision){release(info);return}
        const selection=defaultSelection(info)
        const measurement=await api<Measurement>('select',{document:info.document,options:optionsFrom(selection,info)},signal)
        if(id!==revision){release(info);return}
        addDocument(info,measurement,selection);loaded++
      }catch(error){
        if(id!==revision)return
        if(signal.aborted)return
        s.failedFiles.push({name:item.name,error:String(error instanceof Error?error.message:error)})
      }
    }
    s.notice=loaded?`${loaded} 个文件已加载`+(s.failedFiles.length?`，${s.failedFiles.length} 个失败`:''):(s.failedFiles.length?'全部文件读取失败':'')
  }catch(error){if(id===revision&&!signal.aborted)s.error=String(error instanceof Error?error.message:error)}
  finally{if(id===revision){s.pending=false;s.importing=false}}
}
function retainView(result:Measurement,oldUnit:string|undefined){
  const s=spectrumBrowser;if(!s.view)return
  const low=result.xs[0]!,high=result.xs[result.xs.length-1]!
  if(oldUnit!==result.unit||s.view[1]<=low||s.view[0]>=high){s.view=null;return}
  s.view=[Math.max(low,s.view[0]),Math.min(high,s.view[1])]
}
export async function applySpectrum(){
  clearSelectionTimer()
  const s=spectrumBrowser,doc=activeDocument.value;if(!doc||s.importing)return
  const id=++revision;controller?.abort();controller=new AbortController();const signal=controller.signal;s.pending=true;s.error=''
  const selection=snapshot(),oldUnit=doc.spectrum.unit
  try{
    const result=await api<Measurement>('select',{document:doc.key,options:optionsFrom(selection,doc.info)},signal)
    if(id===revision){doc.selection=markRaw(selection);doc.spectrum=validate(result);doc.selectionError='';retainView(result,oldUnit);s.notice=''}
  }catch(error){
    if(id===revision&&!signal.aborted){doc.selectionError=String(error instanceof Error?error.message:error);s.error=''}
  }finally{if(id===revision)s.pending=false}
}
export async function loadReferences(file?:File,user=false){
  const id=++referenceRevision;referenceController?.abort();referenceController=new AbortController();const signal=referenceController.signal,s=spectrumBrowser;s.referencePending=true;s.nistPending=false;s.referenceError=''
  try{
    let body:Record<string,unknown>={}
    if(user){const chosen=file?{name:file.name,bytes:new Uint8Array(await file.arrayBuffer())}:await selectedBytesReference();if(id!==referenceRevision||!chosen)return;body={name:chosen.name,data:base64(chosen.bytes),options:{unit:s.userUnit,column:Number(s.userColumn),...(s.userElement.trim()?{element:s.userElement.trim()}:{}),...(s.userSpecies.trim()?{species:s.userSpecies.trim()}:{})}}}
    const result=await api<{groups:ReferenceGroup[];issues:{file:string;error:string}[]}>('references',body,signal)
    if(id!==referenceRevision)return
    if(!result.groups.length)throw Error('没有可读取的谱线位置；上次成功数据保留')
    const incoming=result.groups.map(g=>({...g,id:(user?'user:':'configured:')+g.id,originKind:user?'user' as const:'configured' as const}))
    const active=new Set(s.references.filter(g=>s.selected.includes(g.id)).map(referenceKey))
    const groups=user?[...s.references,...incoming]:[...s.references.filter(g=>!s.configuredIds.includes(g.id)),...incoming]
    const unique=[...new Map(groups.map(g=>[g.id,g])).values()];if(unique.reduce((n,g)=>n+g.count,0)>100000)throw Error('合并参考线超过100000，请先清空参考库');s.references=markRaw(unique);s.referenceIssues=result.issues
    if(!user){s.configuredIds=incoming.map(g=>g.id);s.configuredLoaded=true;s.configuredCount=incoming.reduce((n,g)=>n+g.count,0)}
    s.addedElements=s.addedElements.filter(element=>unique.some(g=>g.element===element))
    s.selected=unique.filter(g=>s.addedElements.includes(g.element)&&active.has(referenceKey(g))).map(g=>g.id)
    for(const element of s.addedElements)s.rememberedSpecies[element]=(s.rememberedSpecies[element]??[]).filter(key=>unique.some(g=>g.element===element&&referenceKey(g)===key))
  }catch(error){if(id===referenceRevision&&!signal.aborted)s.referenceError=String(error instanceof Error?error.message:error)}
  finally{if(id===referenceRevision)s.referencePending=false}
}
// Reference CSVs stay single-file; reuse the same dialog without multi-select.
async function selectedBytesReference():Promise<{name:string;bytes:Uint8Array}|null>{
  if(!isTauri())return null
  const path=await open({multiple:false,directory:false,title:'选择参考谱线 CSV',filters:[{name:'参考谱线',extensions:['csv']}]})
  if(!path||typeof path!=='string')return null
  const info=await stat(path)
  if(!info.isFile||info.size>MAX_FILE_BYTES||info.size===0)throw Error('请选择不超过32MB的非空文件')
  return{name:fileName(path),bytes:await readFile(path)}
}
export function cancelReferences(){referenceRevision++;referenceController?.abort();spectrumBrowser.referencePending=false;spectrumBrowser.nistPending=false}
export async function loadNistReferences(element=spectrumBrowser.nistElement){
  const id=++referenceRevision;referenceController?.abort();referenceController=new AbortController();const signal=referenceController.signal,s=spectrumBrowser;s.referencePending=false;s.nistPending=true;s.referenceError='';s.nistElement=element
  try{
    const result=await api<{groups:ReferenceGroup[];issues:{file:string;error:string}[]}>('references',{source:'nist',element},signal);if(id!==referenceRevision)return
    if(!result.groups.length)throw Error('NIST未返回可用Persistent Lines：'+(result.issues?.map(x=>x.error).join('; ')||'无有效表'))
    const nist:ReferenceGroup[]=result.groups.map(g=>({...g,originKind:'nist' as const,id:'nist:'+g.id}))
    const previous=s.references.filter(g=>g.originKind==='nist'&&g.element===element)
    const old=s.references.filter(g=>!previous.includes(g))
    const selectedKeys=new Set(s.references.filter(g=>s.selected.includes(g.id)).map(referenceKey))
    const merged=[...old,...nist];if(merged.reduce((n,g)=>n+g.count,0)>100000)throw Error('合并参考线超过100000，请先清空参考库')
    s.references=markRaw(merged);s.nistIssues=result.issues;s.nistStatus=element+' 可用态：'+nist.map(g=>g.species).join(' / ');s.addedElements=s.addedElements.includes(element)?s.addedElements:[...s.addedElements,element]
    s.selected=merged.filter(g=>selectedKeys.has(referenceKey(g))||nist.includes(g)&&!previous.some(p=>p.species===g.species)).map(g=>g.id)
    s.rememberedSpecies[element]=merged.filter(g=>g.element===element&&s.selected.includes(g.id)).map(referenceKey)
  }catch(error){if(id===referenceRevision&&!signal.aborted)s.referenceError=String(error instanceof Error?error.message:error)}finally{if(id===referenceRevision)s.nistPending=false}
}
export function clearReferences(){cancelReferences();const s=spectrumBrowser;s.references=[];s.selected=[];s.addedElements=[];s.rememberedSpecies={};s.configuredIds=[];s.configuredLoaded=false;s.configuredCount=0;s.referenceError='';s.referenceIssues=[];s.nistIssues=[];s.nistStatus=''}
function referenceKey(g:ReferenceGroup){return JSON.stringify([g.originKind,g.source,g.element,g.species,g.original_unit,g.originKind==='user'?g.sha256:''])}
export function addReferenceElement(element:string){const s=spectrumBrowser,groups=s.references.filter(g=>g.element===element);if(!groups.length||s.addedElements.includes(element))return;s.addedElements.push(element);s.selected.push(...groups.map(g=>g.id));s.rememberedSpecies[element]=groups.map(referenceKey)}
export function toggleReferenceElement(element:string){const s=spectrumBrowser,groups=s.references.filter(g=>g.element===element),selected=groups.filter(g=>s.selected.includes(g.id));if(selected.length){s.rememberedSpecies[element]=selected.map(referenceKey);s.selected=s.selected.filter(id=>!groups.some(g=>g.id===id))}else{const previous=s.rememberedSpecies[element],targets=previous?.length?groups.filter(g=>previous.includes(referenceKey(g))):groups;s.selected=[...new Set([...s.selected,...targets.map(g=>g.id)])]}}
export function toggleReferenceSpecies(id:string){const s=spectrumBrowser,group=s.references.find(g=>g.id===id);if(!group)return;s.selected=s.selected.includes(id)?s.selected.filter(v=>v!==id):[...s.selected,id];const active=s.references.filter(g=>g.element===group.element&&s.selected.includes(g.id));if(active.length)s.rememberedSpecies[group.element]=active.map(referenceKey)}
export function cancelProcessing(){processingRevision++;processingController?.abort();spectrumBrowser.processingPending=false}
export function clearProcessing(){cancelProcessing();spectrumBrowser.processingResult=null;spectrumBrowser.processingView='original';spectrumBrowser.processingError=''}
export function setProcessingTarget(value:string){
  const s=spectrumBrowser,split=value.indexOf(':')
  if(split<=0)return
  const docKey=value.slice(0,split),curve=value.slice(split+1)
  if(!s.docs.some(d=>d.key===docKey))return
  if(s.target?.docKey!==docKey||s.target.curve!==curve){s.target={docKey,curve};clearProcessing()}
}
export function processingParameters(){const p=spectrumBrowser.processing;return{mode:p.mode,order:Number(p.order),epsilon:Number(p.epsilon),max_iter:Number(p.max_iter),wavelet:p.wavelet,scales:p.scales.split(/[ ,;]+/).filter(Boolean).map(Number),neighbor:Number(p.neighbor),min_length:Number(p.min_length),threshold:Number(p.threshold),window:Number(p.window)}}
export async function runProcessing(){
  const s=spectrumBrowser,doc=s.docs.find(d=>d.key===s.target?.docKey)
  if(!doc||!s.target)return
  const id=++processingRevision;processingController?.abort();processingController=new AbortController();const signal=processingController.signal
  const parameters=processingParameters(),spectrum=doc.spectrum,curve=s.target.curve
  s.processingPending=true;s.processingError=''
  try{
    const result=await api<ProcessingResult>('process',{document:doc.key,options:optionsFrom(doc.selection,doc.info),curve,parameters},signal)
    if(id===processingRevision&&doc.spectrum===spectrum&&s.target?.curve===curve){s.processingResult=markRaw({...result,docKey:doc.key});s.processingView=result.corrected?'corrected':'original'}
  }catch(error){if(id===processingRevision&&!signal.aborted)s.processingError=String(error instanceof Error?error.message:error)}
  finally{if(id===processingRevision)s.processingPending=false}
}
