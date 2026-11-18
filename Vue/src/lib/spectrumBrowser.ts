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
export interface ProcessingResult {algorithm:string;curve:string;parameters:Record<string,unknown>;source:{sha256:string;selection:Record<string,unknown>;unit:string};background:number[]|null;corrected:number[]|null;iterations:number;converged:boolean;iteration_limit_reached:boolean;last_change:number|null;peaks:{index:number;x:number;intensity:number;original_intensity:number}[];ridge_count:number;note:string;source_hashes:Record<string,string>}
interface Selection {sheet:string;start:string;x:string;ys:string[];unit:AxisUnit;duplicates:string;frame:string;curves:string[]}
export const spectrumBrowser = reactive({
  info:null as ImportInfo|null, spectrum:null as Measurement|null,
  candidate:null as ImportInfo|null,committed:null as Selection|null,
  view:null as [number,number]|null,
  sheet:'0', start:'1', x:'0', ys:['1'] as string[], unit:'nm' as AxisUnit, duplicates:'error', frame:'', curves:[] as string[],
  references:[] as ReferenceGroup[], selected:[] as string[], referenceIssues:[] as {file:string;error:string}[], nistPending:false, nistElement:'Fe', nistIssues:[] as {file:string;error:string}[], nistStatus:'',
  addedElements:[] as string[], rememberedSpecies:{} as Record<string,string[]>,configuredIds:[] as string[],configuredLoaded:false,configuredCount:0,
  referencesExpanded:false,processingExpanded:false,sidebarCollapsed:false,hiddenCurves:[] as string[],
  pending:false, importing:false, referencePending:false, error:'', referenceError:'', notice:'',
  userElement:'',userSpecies:'',userUnit:'nm' as AxisUnit,userColumn:'0',
  target:'',processingPending:false,processingError:'',processingResult:null as ProcessingResult|null,processingView:'original',
  processing:{mode:'both',order:'6',epsilon:'0.0001',max_iter:'1000',wavelet:'mexh',scales:'1,2,3,4,5,6,7',neighbor:'2',min_length:'2',threshold:'200',window:'3'}
})
export const browserSelectionInfo=computed(()=>spectrumBrowser.candidate??spectrumBrowser.info)
let revision=0, referenceRevision=0, controller:AbortController|undefined, referenceController:AbortController|undefined
let selectionTimer:ReturnType<typeof setTimeout>|undefined
let processingRevision=0,processingController:AbortController|undefined
const api=<T>(action:string,body:unknown,signal?:AbortSignal)=>request<T>('/spectrum-browser/'+action,body,true,signal)
const fileName=(path:string)=>path.split(/[\\/]/).pop()||'selected-file'
async function selectedBytes(reference=false):Promise<{name:string;bytes:Uint8Array}|null> {
  if(!isTauri())return null
  const path=await open({multiple:false,directory:false,title:reference?'选择参考谱线 CSV':'选择测量光谱',filters:[{name:reference?'参考谱线':'光谱文件',extensions:reference?['csv']:['csv','xlsx','sif','raw','raw8','roh','trm','abs','ref','drk']}]})
  if(!path||typeof path!=='string')return null
  const info=await stat(path)
  if(!info.isFile||info.size>MAX_FILE_BYTES||info.size===0)throw Error('请选择不超过32MB的非空文件')
  return{name:fileName(path),bytes:await readFile(path)}
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
async function browserFile(file:File){if(file.size===0||file.size>MAX_FILE_BYTES)throw Error('请选择不超过32MB的非空文件');return{name:file.name,bytes:new Uint8Array(await file.arrayBuffer())}}
function defaults(info:ImportInfo){
  const state=spectrumBrowser;state.sheet='0';state.unit='nm';state.duplicates='error'
  if(info.tables.length){const t=info.tables[0]!;state.start=String(t.recommended_start);state.x=String(t.recommended_x);state.ys=t.recommended_y.map(String)}
  if(info.frames.length){const f=info.frames[0]!;state.frame=f.id;state.curves=[f.curves[0]!]}
}
export function sheetDefaults(){const t=browserSelectionInfo.value?.tables[Number(spectrumBrowser.sheet)];if(t){spectrumBrowser.start=String(t.recommended_start);spectrumBrowser.x=String(t.recommended_x);spectrumBrowser.ys=t.recommended_y.map(String)}}
export function frameDefaults(){const f=browserSelectionInfo.value?.frames.find(f=>f.id===spectrumBrowser.frame);if(f)spectrumBrowser.curves=[f.curves[0]!]}
function snapshot():Selection{const s=spectrumBrowser;return{sheet:s.sheet,start:s.start,x:s.x,ys:[...s.ys],unit:s.unit,duplicates:s.duplicates,frame:s.frame,curves:[...s.curves]}}
function options(selection=snapshot(),info=browserSelectionInfo.value){return info?.frames.length?{frame:selection.frame,curves:selection.curves,duplicates:selection.duplicates}:{sheet:Number(selection.sheet),start:Number(selection.start),x:Number(selection.x),y:selection.ys.map(Number),unit:selection.unit,duplicates:selection.duplicates}}
function release(info:ImportInfo|null){if(info)void api('release',{document:info.document}).catch(()=>{})}
function clearSelectionTimer(){clearTimeout(selectionTimer);selectionTimer=undefined}
export function cancelSpectrum(){clearSelectionTimer();revision++;controller?.abort();const s=spectrumBrowser;s.pending=false;s.importing=false;s.error='';release(s.candidate);s.candidate=null;if(s.committed)Object.assign(s,{...s.committed,ys:[...s.committed.ys],curves:[...s.committed.curves]});s.notice=s.spectrum?'已取消；保留上一成功光谱':'已取消'}
// Only user events call this function: defaults, commit and rollback never enqueue work.
export function updateSpectrumSelection(patch:Partial<Selection>){
  const s=spectrumBrowser;if(s.importing||!browserSelectionInfo.value)return
  Object.assign(s,patch)
  if(patch.sheet!==undefined)sheetDefaults()
  if(patch.frame!==undefined)frameDefaults()
  if(patch.x!==undefined)s.ys=s.ys.filter(y=>y!==s.x)
  clearSelectionTimer();revision++;controller?.abort();s.pending=true;s.error='';s.notice=''
  selectionTimer=setTimeout(()=>{selectionTimer=undefined;void applySpectrum()},patch.start!==undefined?220:0)
}
export function disposeSpectrumSelection(){
  clearSelectionTimer()
  if(spectrumBrowser.pending)cancelSpectrum()
}
function commit(info:ImportInfo,result:Measurement,selection:Selection){const measurement=validate(result),s=spectrumBrowser,previous=s.info,old=s.spectrum;s.info=markRaw(info);s.candidate=null;s.committed=selection;s.spectrum=measurement;s.hiddenCurves=old?.sha256===result.sha256?s.hiddenCurves.filter(id=>result.curves.some(c=>c.id===id)):[];clearProcessing();s.target=result.curves[0]?.id??'';if(previous&&previous.document!==info.document)release(previous)}
function retainView(result:Measurement,oldUnit:string|undefined){const s=spectrumBrowser;if(!s.view)return;const low=result.xs[0]!,high=result.xs[result.xs.length-1]!;if(oldUnit!==result.unit||s.view[1]<=low||s.view[0]>=high){s.view=null;return}s.view=[Math.max(low,s.view[0]),Math.min(high,s.view[1])]}
export async function importSpectrum(file?:File){
  clearSelectionTimer()
  const id=++revision;controller?.abort();controller=new AbortController();const signal=controller.signal,s=spectrumBrowser;s.pending=true;s.importing=true;s.error='';s.notice=''
  try{
    const chosen=file?await browserFile(file):await selectedBytes()
    if(id!==revision)return
    if(!chosen)return
    release(s.candidate);s.candidate=null
    if(s.committed)Object.assign(s,{...s.committed,ys:[...s.committed.ys],curves:[...s.committed.curves]})
    const info=await api<ImportInfo>('import',{name:chosen.name,data:base64(chosen.bytes)},signal)
    if(id!==revision){release(info);return}
    s.candidate=markRaw(info);defaults(info);const selection=snapshot()
    const measurement=await api<Measurement>('select',{document:info.document,options:options(selection,info)},signal)
    if(id!==revision)return
    commit(info,measurement,selection);s.view=null
  }catch(error){if(id===revision&&!signal.aborted)s.error=String(error instanceof Error?error.message:error)}
  finally{if(id===revision){s.pending=false;s.importing=false}}
}
export async function applySpectrum(){
  clearSelectionTimer()
  const s=spectrumBrowser,info=browserSelectionInfo.value;if(!info||s.importing)return
  const id=++revision;controller?.abort();controller=new AbortController();const signal=controller.signal;s.pending=true;s.error=''
  const selection=snapshot(),oldUnit=s.spectrum?.unit
  try{const result=await api<Measurement>('select',{document:info.document,options:options(selection,info)},signal);if(id===revision){commit(info,result,selection);retainView(result,oldUnit);s.notice=''}}
  catch(error){if(id===revision&&!signal.aborted)s.error=String(error instanceof Error?error.message:error)}
  finally{if(id===revision)s.pending=false}
}
export async function loadReferences(file?:File,user=false){
  const id=++referenceRevision;referenceController?.abort();referenceController=new AbortController();const signal=referenceController.signal,s=spectrumBrowser;s.referencePending=true;s.nistPending=false;s.referenceError=''
  try{
    let body:Record<string,unknown>={}
    if(user){const chosen=file?await browserFile(file):await selectedBytes(true);if(id!==referenceRevision||!chosen)return;body={name:chosen.name,data:base64(chosen.bytes),options:{unit:s.userUnit,column:Number(s.userColumn),...(s.userElement.trim()?{element:s.userElement.trim()}:{}),...(s.userSpecies.trim()?{species:s.userSpecies.trim()}: {})}}}
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
export function setProcessingTarget(value:string){if(spectrumBrowser.target!==value){spectrumBrowser.target=value;clearProcessing()}}
export function processingParameters(){const p=spectrumBrowser.processing;return{mode:p.mode,order:Number(p.order),epsilon:Number(p.epsilon),max_iter:Number(p.max_iter),wavelet:p.wavelet,scales:p.scales.split(/[ ,;]+/).filter(Boolean).map(Number),neighbor:Number(p.neighbor),min_length:Number(p.min_length),threshold:Number(p.threshold),window:Number(p.window)}}
export async function runProcessing(){
  const s=spectrumBrowser;if(!s.info||!s.spectrum||!s.committed)return
  const id=++processingRevision;processingController?.abort();processingController=new AbortController();const signal=processingController.signal,spectrum=s.spectrum,curve=s.target,parameters=processingParameters();s.processingPending=true;s.processingError=''
  try{const result=await api<ProcessingResult>('process',{document:s.info.document,options:options(s.committed,s.info),curve,parameters},signal);if(id===processingRevision&&s.spectrum===spectrum&&s.target===curve){s.processingResult=markRaw(result);s.processingView=result.corrected?'corrected':'original'}}
  catch(error){if(id===processingRevision&&!signal.aborted)s.processingError=String(error instanceof Error?error.message:error)}
  finally{if(id===processingRevision)s.processingPending=false}
}
