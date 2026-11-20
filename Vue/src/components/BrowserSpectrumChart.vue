<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { docColor, spectrumBrowser, toggleDocCurve, toggleDocumentVisible, toggleReferenceSpecies, type LoadedDocument, type ReferenceGroup, type ReferencePosition } from '../lib/spectrumBrowser'
import { elementColor } from '../lib/model'
import { localPeakIndices, selectHoverNode } from '../lib/spectrumInteraction'
const props=defineProps<{docs:LoadedDocument[];references:ReferenceGroup[];loadedReferences:ReferenceGroup[]}>()
const view=defineModel<[number,number]|null>('view',{required:true})
const canvas=ref<HTMLCanvasElement>(),overview=ref<HTMLCanvasElement>(),host=ref<HTMLElement>()
const hover=ref<{docKey:string;index:number;curveId:string;snapped:boolean}|null>(null)
const drag=ref<{kind:'zoom'|'pan'|'overview';x:number;now:number;initial:[number,number];pointerId:number}|null>(null)
const dark=ref(false)
// Only files matching the first visible file's unit are overlaid; others stay
// listed greyed out with an explicit hint. nm references never touch pixel axes.
const primaryUnit=computed(()=>props.docs.find(d=>d.visible)?.spectrum.unit??null)
const drawnDocs=computed(()=>props.docs.filter(d=>d.visible&&d.spectrum.unit===primaryUnit.value))
const mixedDocs=computed(()=>props.docs.filter(d=>d.visible&&d.spectrum.unit!==primaryUnit.value))
const full=computed<[number,number]>(()=>{
  let low=Infinity,high=-Infinity
  for(const doc of drawnDocs.value){low=Math.min(low,doc.spectrum.xs[0]!);high=Math.max(high,doc.spectrum.xs[doc.spectrum.xs.length-1]!)}
  return low<high?[low,high]:[0,1]
})
const range=computed<[number,number]>(()=>{
  const candidate=view.value??full.value
  return candidate[1]>candidate[0]?candidate:full.value
})
interface DrawnCurve{doc:LoadedDocument;id:string;label:string;ys:number[];xs:number[];color:string}
// Per-file color; multiple curves inside one file use lightness shades of that
// hue. When a processing result belongs to the file, the derived curve replaces
// its curves in the selected view mode.
const drawnCurves=computed<DrawnCurve[]>(()=>drawnDocs.value.flatMap(doc=>{
  const result=spectrumBrowser.processingResult,mode=spectrumBrowser.processingView
  if(result&&result.docKey===doc.key&&mode!=='original'){
    // Drift-corrected view keeps intensities but re-draws the processed curve
    // on the recalibrated wavelength axis (same node count as the source).
    if(mode==='driftCorrected'&&result.corrected_xs){
      const source=doc.spectrum.curves.find(c=>c.id===result.curve)??doc.spectrum.curves[0]
      if(source&&result.corrected_xs.length===doc.spectrum.xs.length)return[{doc,id:'drift:'+result.curve,label:(doc.spectrum.curves.find(c=>c.id===result.curve)?.label??result.curve)+' · 漂移校正',ys:source.ys,xs:result.corrected_xs,color:docColor(doc.colorIndex,0,1,dark.value)}]
    }
    const ys=mode==='background'?result.background:result.corrected
    if(ys)return[{doc,id:'derived:'+result.curve+':'+mode,label:(doc.spectrum.curves.find(c=>c.id===result.curve)?.label??result.curve)+' · '+(mode==='background'?'背景':'扣背景'),ys,xs:doc.spectrum.xs,color:docColor(doc.colorIndex,0,1,dark.value)}]
  }
  const visible=doc.spectrum.curves.filter(c=>!doc.hiddenCurves.includes(c.id))
  return visible.map((curve,index)=>({doc,id:curve.id,label:curve.label,ys:curve.ys,xs:doc.spectrum.xs,color:docColor(doc.colorIndex,index,visible.length,dark.value)}))
}))
const overviewBands=[
  {name:'其他短波',from:1,to:10,color:'#64748b'},
  {name:'极紫外',from:10,to:100,color:'#a855f7'},
  {name:'深紫外',from:100,to:280,color:'#6366f1'},
  {name:'紫外',from:280,to:380,color:'#b34ca4'},
  {name:'可见光',from:380,to:780,color:'#25876d'},
  {name:'红外',from:780,to:100000,color:'#c76236'}
]
const overviewSegments=computed(()=>{
  if(primaryUnit.value!=='nm'||!drawnCurves.value.length)return[]
  const [low,high]=full.value,span=high-low
  if(!Number.isFinite(low)||!Number.isFinite(high)||span<=0)return[]
  return overviewBands.flatMap(band=>{const from=Math.max(low,band.from),to=Math.min(high,band.to);return to>from?[{...band,left:(from-low)/span*100,width:(to-from)/span*100}]:[]})
})
const bandTooltipId=useId(),bandTooltip=ref<HTMLElement>(),activeBand=shallowRef<(typeof overviewBands)[number]|null>(null),bandPoint=ref({left:12,top:12})
const bandTitle=(band:(typeof overviewBands)[number])=>band.name+' · '+band.from+'–'+band.to+' nm'
function clearBand(){activeBand.value=null}
async function showBand(band:(typeof overviewBands)[number],event:MouseEvent|FocusEvent){
  const element=event.currentTarget as HTMLElement
  activeBand.value=band
  await nextTick()
  if(activeBand.value!==band||!bandTooltip.value||!element.isConnected)return
  const rect=element.getBoundingClientRect(),tip=bandTooltip.value.getBoundingClientRect()
  bandPoint.value={left:Math.max(8,Math.min(innerWidth-tip.width-8,rect.left+rect.width/2-tip.width/2)),top:rect.top>=tip.height+14?rect.top-tip.height-6:Math.min(innerHeight-tip.height-8,rect.bottom+6)}
}
watch(overviewSegments,clearBand)
const processing=computed(()=>{const result=spectrumBrowser.processingResult;if(!result)return null;const doc=drawnDocs.value.find(d=>d.key===result.docKey);return doc?{doc,result}:null})
const enabledReferences=computed(()=>primaryUnit.value==='nm'?props.references:[])
// Position counts inside the current selection window; groups with zero hits
// render grey in the overview caption so the eye only chases live colors.
const referenceCounts=computed(()=>new Map(enabledReferences.value.map(g=>[g.id,g.xs.filter(x=>x>=range.value[0]&&x<=range.value[1]).length])))
// One dash color per (element, species): the element hue rotated per ion stage
// so Fe I and Fe II stay in the element's family yet are clearly distinct.
// Roman numerals map to the stage index; unknown species stay at stage 0.
function hexHsl(hex:string){const m=/^#([0-9a-f]{6})$/i.exec(hex.trim());if(!m)return{h:210,s:60,l:40};const n=parseInt(m[1]!,16),r=(n>>16&255)/255,g=(n>>8&255)/255,b=(n&255)/255,max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;let h=0;if(d){if(max===r)h=((g-b)/d+6)%6;else if(max===g)h=(b-r)/d+2;else h=(r-g)/d+4;h*=60}const l=(max+min)/2,s=d===0?0:d/(1-Math.abs(2*l-1));return{h,s:s*100,l:l*100}}
function romanStage(species:string){const table:Record<string,number>={I:1,II:2,III:3,IV:4,V:5,VI:6,VII:7,VIII:8,IX:9,X:10};const key=(/^\s*([IVX]+)\s*$/i.exec(species)?.[1]??'').toUpperCase();return (table[key]??1)-1}
function referenceColor(group:ReferenceGroup,dark:boolean){const base=hexHsl(elementColor(group.element)),idx=romanStage(group.species);const hue=(base.h+idx*36)%360;const light=Math.max(28,Math.min(78,(dark?64:39)+idx*5));return 'hsl('+hue.toFixed(0)+' '+base.s.toFixed(0)+'% '+light.toFixed(0)+'%)'}
// Peaks are cached per curve payload; hover never rescans a million nodes.
const peakCache=new Map<string,readonly number[]>()
function peaksOf(curve:DrawnCurve){
  const key=curve.doc.sha256+':'+curve.id
  let peaks=peakCache.get(key)
  if(!peaks){peaks=localPeakIndices(curve.ys);if(peakCache.size>128)peakCache.clear();peakCache.set(key,peaks)}
  return peaks
}
type IntensityRange=[number,number]
function paddedIntensityRange(min:number,max:number):IntensityRange{
  if(!Number.isFinite(min)||!Number.isFinite(max))return[-1,1]
  if(min>max)[min,max]=[max,min]
  const span=max-min
  const pad=span>0?(Number.isFinite(span)?span*.08:Math.max(Math.abs(min),Math.abs(max))*.08):Math.max(1,Math.abs(min)*.08)
  const low=Math.max(-Number.MAX_VALUE,min-pad),high=Math.min(Number.MAX_VALUE,max+pad)
  return high>low?[low,high]:[-1,1]
}
function lower(xs:number[],x:number){let a=0,b=xs.length;while(a<b){const m=(a+b)>>>1;if(xs[m]!<x)a=m+1;else b=m}return a}
function upper(xs:number[],x:number){let a=0,b=xs.length;while(a<b){const m=(a+b)>>>1;if(xs[m]!<=x)a=m+1;else b=m}return a}
function interpolated(curve:DrawnCurve,x:number){
  const xs=curve.xs,right=lower(xs,x)
  if(!xs.length)return Number.NaN
  if(right===0)return curve.ys[0]!
  if(right===xs.length)return curve.ys[xs.length-1]!
  if(xs[right]===x)return curve.ys[right]!
  const left=right-1,x0=xs[left]!,x1=xs[right]!,y0=curve.ys[left]!,y1=curve.ys[right]!
  if(x1===x0)return y0
  const ratio=(x-x0)/(x1-x0)
  return y0*(1-ratio)+y1*ratio
}
function intensityRange(selection:[number,number],curves=drawnCurves.value):IntensityRange{
  const low=Math.min(selection[0],selection[1]),high=Math.max(selection[0],selection[1])
  let min=Infinity,max=-Infinity
  const add=(value:number)=>{if(Number.isFinite(value)){min=Math.min(min,value);max=Math.max(max,value)}}
  for(const curve of curves){
    const xs=curve.xs,start=lower(xs,low),end=upper(xs,high)
    for(let i=start;i<end;i++)add(curve.ys[i]!)
    add(interpolated(curve,low));add(interpolated(curve,high))
  }
  return paddedIntensityRange(min,max)
}
const globalIntensity=computed<IntensityRange>(()=>intensityRange(full.value))
const adaptiveIntensity=ref<IntensityRange|null>(null)
const activeIntensity=computed<IntensityRange>(()=>adaptiveIntensity.value??globalIntensity.value)
const lineHits=ref<{group:ReferenceGroup;position:ReferencePosition}[]>([]),tooltip=ref<HTMLElement>(),linePoint=ref({left:12,top:12})
let lineTimer:ReturnType<typeof setTimeout>|undefined
function clearLine(){clearTimeout(lineTimer);lineHits.value=[]}
function keepLine(){clearTimeout(lineTimer)}
function leaveLine(){clearTimeout(lineTimer);lineTimer=setTimeout(clearLine,220)}
function scrollLine(event:Event){clearBand();if(event.target instanceof Node&&tooltip.value?.contains(event.target))return;clearLine()}
function hitLine(event:PointerEvent){
  const el=canvas.value!,box=el.getBoundingClientRect(),g=geometry(el),px=event.clientX-box.left,py=event.clientY-box.top
  if(drag.value||primaryUnit.value!=='nm'||px<g.left||px>g.w-g.right||py<g.top||py>g.h-g.bottom){clearLine();return}
  const s=range.value,pw=g.w-g.left-g.right,x=s[0]+(px-g.left)/pw*(s[1]-s[0]),tolerance=6/pw*(s[1]-s[0])
  const hits:{group:ReferenceGroup;position:ReferencePosition}[]=[]
  for(const group of enabledReferences.value){for(let i=lower(group.xs,Math.max(s[0],x-tolerance));i<group.xs.length&&group.xs[i]!<=Math.min(s[1],x+tolerance);i++){const position=group.positions?.[i];if(position)hits.push({group,position})}}
  if(!hits.length){leaveLine();return}
  keepLine()
  const same=lineHits.value.length===hits.length&&lineHits.value.every((hit,i)=>hit.group.id===hits[i]!.group.id&&hit.position.wavelength_nm===hits[i]!.position.wavelength_nm)
  lineHits.value=hits
  if(same)return
  const width=Math.min(360,innerWidth-24),height=Math.min(330,innerHeight-24)
  linePoint.value={left:Math.max(12,Math.min(innerWidth-width-12,event.clientX+18)),top:Math.max(12,Math.min(innerHeight-height-12,event.clientY+14))}
}
function leave(event:PointerEvent){if(tooltip.value?.contains(event.relatedTarget as Node)){keepLine();return}leaveLine();hover.value=null;schedule()}
let observer:ResizeObserver|undefined,theme:MutationObserver|undefined,frame=0
let lastPlotWidth=-1,lastPlotHeight=-1
function resizePlot(){const rect=canvas.value?.getBoundingClientRect();if(rect&&(rect.width!==lastPlotWidth||rect.height!==lastPlotHeight)){lastPlotWidth=rect.width;lastPlotHeight=rect.height;clearLine();clearBand()}schedule()}
const fmt=(v:number)=>Number.isFinite(v)?Number(v.toPrecision(7)).toString():'—'
function setRange(a:number,b:number){
  let width=Math.abs(b-a),left=Math.min(a,b),total=full.value[1]-full.value[0]
  if(width<total*1e-9)return
  width=Math.min(total,width);left=Math.max(full.value[0],Math.min(full.value[1]-width,left));view.value=[left,left+width]
}
function reset(){adaptiveIntensity.value=null;view.value=null;hover.value=null;clearLine();schedule()}
function showGlobalIntensity(){adaptiveIntensity.value=null;schedule()}
function adaptIntensity(){adaptiveIntensity.value=intensityRange(range.value);hover.value=null;clearLine();schedule()}
function nearest(doc:LoadedDocument,x:number){const xs=doc.spectrum.xs,i=lower(xs,x);return i===0?0:i===xs.length?xs.length-1:x-xs[i-1]!<=xs[i]!-x?i-1:i}
function pickHover(px:number,py:number){
  const el=canvas.value!,g=geometry(el)
  const plot={low:range.value[0],high:range.value[1],left:g.left,top:g.top,width:g.w-g.left-g.right,height:g.h-g.top-g.bottom,yMaximum:activeIntensity.value[1]}
  let best:null|{docKey:string;index:number;curveId:string;snapped:boolean}=null,bestD=Infinity
  for(const doc of drawnDocs.value){
    const visible=drawnCurves.value.filter(c=>c.doc.key===doc.key)
    if(!visible.length)continue
    const selection=selectHoverNode(doc.spectrum.xs,visible.map(c=>({id:c.id,ys:c.ys,peaks:peaksOf(c)})),plot,px,py)
    if(!selection)continue
    const curve=visible.find(c=>c.id===selection.curveId),value=curve?.ys[selection.index]
    if(value===undefined||!Number.isFinite(value))continue
    const x=doc.spectrum.xs[selection.index]!
    const dx=(g.left+(x-plot.low)/(plot.high-plot.low)*plot.width)-px,dy=(g.top+plot.height-value/plot.yMaximum*plot.height)-py,d=dx*dx+dy*dy
    if(d<bestD){bestD=d;best={docKey:doc.key,index:selection.index,curveId:selection.curveId,snapped:selection.snapped}}
  }
  return best
}
const hovered=computed(()=>{
  const h=hover.value;if(!h)return null
  const doc=drawnDocs.value.find(d=>d.key===h.docKey);if(!doc)return null
  const i=h.index;if(i<0||i>=doc.spectrum.xs.length)return null
  const x=doc.spectrum.xs[i]!,first=lower(doc.spectrum.xs,x);let last=first
  while(last+1<doc.spectrum.nodes&&doc.spectrum.xs[last+1]===x)last++
  return{doc,index:i,x,first,last,values:drawnCurves.value.filter(c=>c.doc.key===doc.key).map(c=>({label:c.label,y:c.ys[i]!,color:c.color}))}
})
function geometry(element:HTMLCanvasElement,mini=false){const r=element.getBoundingClientRect();return{w:r.width,h:r.height,left:mini?14:64,right:mini?14:18,top:mini?10:22,bottom:mini?14:42}}
function position(event:PointerEvent|WheelEvent,mini=false){const el=mini?overview.value!:canvas.value!,r=el.getBoundingClientRect(),g=geometry(el,mini),s=mini?full.value:range.value;return s[0]+Math.max(0,Math.min(1,(event.clientX-r.left-g.left)/(g.w-g.left-g.right)))*(s[1]-s[0])}
function schedule(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;draw(false);draw(true)})}
function draw(mini:boolean){
  const el=mini?overview.value:canvas.value;if(!el)return
  const g=geometry(el,mini),dpr=Math.min(devicePixelRatio||1,2),width=Math.round(g.w*dpr),height=Math.round(g.h*dpr)
  if(el.width!==width)el.width=width;if(el.height!==height)el.height=height
  const ctx=el.getContext('2d')!;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,g.w,g.h)
  const css=getComputedStyle(document.documentElement),color=(name:string)=>css.getPropertyValue(name).trim()||'#6688aa',s=mini?full.value:range.value,yRange=mini?globalIntensity.value:activeIntensity.value,pw=g.w-g.left-g.right,ph=g.h-g.top-g.bottom
  dark.value=document.documentElement.dataset.theme==='dark'
  const [ymin,ymax]=yRange
  const X=(x:number)=>g.left+(x-s[0])/(s[1]-s[0])*pw,Y=(y:number)=>g.top+(ymax/2-y/2)/(ymax/2-ymin/2)*ph
  ctx.font='11px '+css.getPropertyValue('--font-code');ctx.fillStyle=color('--muted');ctx.lineWidth=1
  if(!mini){for(let i=0;i<=4;i++){const y=ymin*(1-i/4)+ymax*i/4;ctx.globalAlpha=.2;ctx.strokeStyle=color('--muted');ctx.beginPath();ctx.moveTo(g.left,Y(y));ctx.lineTo(g.w-g.right,Y(y));ctx.stroke();ctx.globalAlpha=1;ctx.textAlign='right';ctx.fillText(fmt(y),g.left-9,Y(y)+4)}for(let i=0;i<=5;i++){const x=s[0]+(s[1]-s[0])*i/5;ctx.textAlign=i===0?'left':i===5?'right':'center';ctx.fillText(fmt(x),X(x),g.h-22)}ctx.textAlign='right';ctx.fillText(primaryUnit.value==='nm'?'波长 / nm':'像素 / pixel',g.w-g.right,g.h-3)}
  ctx.save();ctx.beginPath();ctx.rect(g.left,g.top,pw,ph);ctx.clip()
  // Reference dashes render in both the main plot and the overview so line
  // positions stay findable while zoomed in; same colors and dash pattern.
  enabledReferences.value.forEach(group=>{ctx.strokeStyle=referenceColor(group,dark.value);ctx.globalAlpha=.55;ctx.setLineDash([4,5]);for(let i=lower(group.xs,s[0]);i<group.xs.length&&group.xs[i]!<=s[1];i++){const x=X(group.xs[i]!);ctx.beginPath();ctx.moveTo(x,g.top);ctx.lineTo(x,g.top+ph);ctx.stroke()}});ctx.setLineDash([]);ctx.globalAlpha=1
  drawnCurves.value.forEach(curve=>{
    const xs=curve.xs
    ctx.strokeStyle=curve.color;ctx.lineWidth=mini?1:1.5;ctx.beginPath()
    // Every visible node participates. Pixel buckets retain original min/max,
    // endpoints and their order; hover always reads the full original arrays.
    const from=Math.max(0,lower(xs,s[0])-1);let to=lower(xs,s[1]);while(to<xs.length&&xs[to]===s[1])to++;to=Math.min(xs.length,to+1)
    const bucket=Math.max(1,Math.ceil((to-from)/(pw*2)));let begun=false
    for(let start=from;start<to;start+=bucket){const end=Math.min(to,start+bucket);let low=start,high=start;for(let i=start+1;i<end;i++){if(curve.ys[i]!<curve.ys[low]!)low=i;if(curve.ys[i]!>curve.ys[high]!)high=i}for(const i of [...new Set([start,low,high,end-1])].sort((a,b)=>a-b)){const x=X(xs[i]!),y=Y(curve.ys[i]!);begun?ctx.lineTo(x,y):ctx.moveTo(x,y);begun=true}}
    ctx.stroke()
  })
  const hoveredDoc=hover.value?drawnDocs.value.find(d=>d.key===hover.value!.docKey):null
  if(!mini&&hover.value&&hoveredDoc){const i=hover.value.index,x=X(hoveredDoc.spectrum.xs[i]!);ctx.strokeStyle=color('--muted');ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x,g.top);ctx.lineTo(x,g.top+ph);ctx.stroke();ctx.setLineDash([]);for(const c of drawnCurves.value.filter(c=>c.doc.key===hoveredDoc.key)){ctx.fillStyle=c.color;ctx.beginPath();ctx.arc(x,Y(c.ys[i]!),3,0,2*Math.PI);ctx.fill()}}
  const active=processing.value?drawnCurves.value.find(c=>c.doc.key===processing.value!.doc.key&&(c.id===processing.value!.result.curve||c.id==='derived:'+processing.value!.result.curve+':corrected')):undefined
  if(!mini&&processing.value&&active){ctx.fillStyle=color('--bad');for(const peak of processing.value.result.peaks){if(peak.x<s[0]||peak.x>s[1])continue;const x=X(peak.x),y=Y(active.ys[peak.index]!);ctx.beginPath();ctx.moveTo(x,y-4);ctx.lineTo(x-4,y-11);ctx.lineTo(x+4,y-11);ctx.closePath();ctx.fill()}}
  if(mini){const a=X(range.value[0]),b=X(range.value[1]);ctx.fillStyle=color('--accent');ctx.globalAlpha=.15;ctx.fillRect(a,g.top,b-a,ph);ctx.globalAlpha=1;ctx.strokeStyle=color('--accent-text');ctx.strokeRect(a,g.top,b-a,ph)}
  if(!mini&&drag.value?.kind==='zoom'){const reverse=drag.value.now<drag.value.x,a=X(Math.min(drag.value.x,drag.value.now)),b=X(Math.max(drag.value.x,drag.value.now));ctx.fillStyle=reverse?color('--muted'):color('--accent');ctx.globalAlpha=reverse?.08:.16;ctx.fillRect(a,g.top,b-a,ph);ctx.globalAlpha=1;if(reverse){ctx.strokeStyle=color('--accent');ctx.setLineDash([3,3]);ctx.strokeRect(a,g.top,b-a,ph);ctx.setLineDash([])}}
  ctx.restore()
}
function down(event:PointerEvent,mini=false){
  if(event.button!==0&&event.button!==1)return
  clearLine();event.preventDefault();const x=position(event,mini);drag.value={kind:mini?'overview':event.button===1||event.shiftKey||event.altKey?'pan':'zoom',x,now:x,initial:[...range.value],pointerId:event.pointerId};(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function move(event:PointerEvent,mini=false){const x=position(event,mini),d=drag.value;if(d){d.now=x;if(d.kind==='pan'){const delta=(event.movementX/(geometry(canvas.value!).w-82))*(d.initial[1]-d.initial[0]);setRange(range.value[0]-delta,range.value[1]-delta)}else if(d.kind==='overview'){const width=d.initial[1]-d.initial[0];if(width<full.value[1]-full.value[0])setRange(x-width/2,x+width/2)}schedule()}else if(!mini){hover.value=drawnCurves.value.length?pickHover(event.clientX-(canvas.value!.getBoundingClientRect().left),event.clientY-(canvas.value!.getBoundingClientRect().top)):null;hitLine(event);schedule()}}
function up(event:PointerEvent,mini=false){const d=drag.value;if(!d)return;const x=position(event,mini);if(d.kind==='zoom'){const dragSpan=Math.abs(x-d.x),currentSpan=range.value[1]-range.value[0],totalSpan=full.value[1]-full.value[0];if(dragSpan>currentSpan*.012){if(x>d.x)setRange(d.x,x);else{const factor=Math.max(1.2,currentSpan/dragSpan),center=(d.x+x)/2,newWidth=Math.min(totalSpan,currentSpan*factor);setRange(center-newWidth/2,center+newWidth/2)}}}if(d.kind==='overview'&&d.initial[1]-d.initial[0]>=full.value[1]-full.value[0])setRange(d.x,x);drag.value=null;const target=event.currentTarget as HTMLElement;if(target.hasPointerCapture(event.pointerId))target.releasePointerCapture(event.pointerId);schedule()}
function wheel(event:WheelEvent){const x=position(event),s=range.value,factor=event.deltaY>0?1.2:1/1.2;setRange(x-(x-s[0])*factor,x+(s[1]-x)*factor)}
function key(event:KeyboardEvent){
  if(['Home','Escape'].includes(event.key)){event.preventDefault();reset()}
  else if(['ArrowLeft','ArrowRight'].includes(event.key)){
    event.preventDefault()
    const doc=hover.value?drawnDocs.value.find(d=>d.key===hover.value!.docKey):drawnDocs.value[0]
    if(!doc)return
    const base=hover.value?.docKey===doc.key?hover.value!.index:nearest(doc,(range.value[0]+range.value[1])/2)
    hover.value={docKey:doc.key,index:Math.max(0,Math.min(doc.spectrum.nodes-1,base+(event.key==='ArrowLeft'?-1:1))),curveId:drawnCurves.value.find(c=>c.doc.key===doc.key)?.id??'',snapped:false}
    schedule()
  }
  else if(event.key==='+'||event.key==='-'){event.preventDefault();const s=range.value,c=(s[0]+s[1])/2,w=(s[1]-s[0])*(event.key==='+'?.8:1.25);setRange(c-w/2,c+w/2)}
}
// Grouped legend: file row toggles the whole file; indented rows toggle single
// curves. Hidden entries stay greyed out instead of disappearing.
const legendGroups=computed(()=>props.docs.map(doc=>{
  const result=spectrumBrowser.processingResult,mode=spectrumBrowser.processingView
  const derived=!!(result&&result.docKey===doc.key&&mode!=='original'&&(mode==='background'?result.background:result.corrected))
  const visible=doc.spectrum.curves.filter(c=>!doc.hiddenCurves.includes(c.id))
  return{
    doc,
    unitMismatch:doc.visible&&doc.spectrum.unit!==primaryUnit.value,
    curves:doc.spectrum.curves.map(c=>({id:c.id,label:c.label,hidden:doc.hiddenCurves.includes(c.id),color:docColor(doc.colorIndex,Math.max(0,visible.findIndex(v=>v.id===c.id)),Math.max(1,visible.length),dark.value)})),
    derived,
    derivedLabel:derived?(doc.spectrum.curves.find(c=>c.id===result!.curve)?.label??result!.curve)+' · '+(mode==='background'?'背景':'扣背景'):''
  }
}))
const fileColor=(doc:LoadedDocument)=>docColor(doc.colorIndex,0,1,dark.value)
function toggleCurve(id:string,curveId:string){toggleDocCurve(id,curveId);hover.value=null;clearLine();schedule()}
function toggleVisible(id:string){toggleDocumentVisible(id);hover.value=null;clearLine();schedule()}
watch(()=>props.docs.map(d=>`${d.key}|${d.visible}|${d.hiddenCurves.join(',')}|${d.spectrum.sha256}`).join(';'),()=>{adaptiveIntensity.value=null;hover.value=null;clearLine();schedule()})
watch(()=>[props.references,view.value,spectrumBrowser.processingResult,spectrumBrowser.processingView],()=>{hover.value=null;clearLine();schedule()},{deep:false})
onMounted(()=>{observer=new ResizeObserver(resizePlot);observer.observe(host.value!);theme=new MutationObserver(()=>{clearLine();schedule()});theme.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','style']});window.addEventListener('scroll',scrollLine,true);window.addEventListener('resize',clearLine);schedule()})
onUnmounted(()=>{observer?.disconnect();theme?.disconnect();window.removeEventListener('scroll',scrollLine,true);window.removeEventListener('resize',clearLine);clearTimeout(lineTimer);cancelAnimationFrame(frame)})
</script>
<template>
  <section ref="host" class="panel measured-chart" aria-label="测量光谱图">
    <div class="panel-heading"><span class="measured-label">{{ drawnDocs.length ? primaryUnit : '—' }} · {{ drawnDocs.length }} 个可见文件 · {{ drawnDocs.reduce((n,d)=>n+d.spectrum.nodes,0).toLocaleString() }} 节点</span><div class="chart-actions" aria-label="光谱范围操作"><button type="button" class="icon-btn chart-reset" aria-label="恢复完整波长范围并重置强度范围" title="恢复全波长与全局强度范围（Home）" @click="reset"><AppIcon name="reset" /></button><button type="button" class="icon-btn" aria-label="仅恢复全局强度范围并保持横向选区" title="恢复全局强度（保持当前横向选区）" @click="showGlobalIntensity"><AppIcon name="cross-arrows" /></button><button type="button" class="icon-btn" aria-label="按当前选区自适应强度并锁定纵轴" title="自适应当前选区强度并锁定纵轴" @click="adaptIntensity"><AppIcon name="vertical-arrows" /></button></div></div>
    <p v-if="mixedDocs.length" class="hint">单位不一致的文件（{{ mixedDocs.map(d=>d.name+' · '+d.spectrum.unit).join('；') }}）不参与叠加；隐藏主单位文件后按剩余文件单位显示。</p>
    <div class="chart-legend-area" aria-label="文件与曲线图例"><div class="measured-legend" aria-label="文件与曲线显示">
      <template v-for="group in legendGroups" :key="group.doc.key">
        <button type="button" :class="{'legend-hidden':!group.doc.visible||group.unitMismatch}" :style="{'--curve-color':fileColor(group.doc)}" :aria-pressed="group.doc.visible&&!group.unitMismatch" :aria-label="'显示文件 '+group.doc.name" :title="group.doc.name" @click="toggleVisible(group.doc.key)"><i />{{ group.doc.name }}<small class="legend-meta">{{ group.unitMismatch?'单位不一致 · 不参与叠加':group.doc.spectrum.unit+' · '+group.doc.spectrum.nodes.toLocaleString()+' 节点' }}</small></button>
        <button v-for="c in group.curves" :key="group.doc.key+':'+c.id" type="button" :class="['legend-curve',{'legend-hidden':!group.doc.visible||c.hidden}]" :style="{'--curve-color':c.color}" :aria-pressed="group.doc.visible&&!c.hidden" :aria-label="'显示曲线 '+c.label" @click="toggleCurve(group.doc.key,c.id)"><i />{{ c.label }}</button>
        <button v-if="group.derived" type="button" class="legend-curve" :style="{'--curve-color':fileColor(group.doc)}" aria-pressed="true" :aria-label="'恢复原始曲线视图'" @click="spectrumBrowser.processingView='original'"><i />{{ group.derivedLabel }}</button>
      </template>
    </div>
    <div v-if="loadedReferences.length" class="reference-legend-column" aria-label="谱线参考图例"><button v-for="g in loadedReferences" :key="'ref:'+g.id" type="button" :class="['legend-reference',{'legend-off':!spectrumBrowser.selected.includes(g.id)}]" :style="{'--curve-color':referenceColor(g,dark)}" :aria-pressed="spectrumBrowser.selected.includes(g.id)" :title="g.label+' · '+g.count+' 条谱线位置'+(spectrumBrowser.selected.includes(g.id)?'':'（已隐藏，点击恢复）')" @click="toggleReferenceSpecies(g.id)"><i class="dash-swatch" />{{ g.species?g.element+' '+g.species:g.element }}</button></div>
  </div>
    <canvas ref="canvas" class="measured-main" role="img" tabindex="0" aria-label="测量局部光谱，可缩放平移和逐节点读取" title="横向缩放和平移保持强度范围；自适应强度仅在点击按钮时调整" @wheel.prevent="wheel" @pointerdown="down($event)" @pointermove="move($event)" @pointerleave="leave" @pointerup="up($event)" @pointercancel="drag=null;clearLine()" @keydown="key" @contextmenu.prevent="reset" @auxclick.prevent />
    <p v-if="!drawnCurves.length" class="measured-empty" role="status">没有可见曲线；点击图例或文件列表恢复。</p>
    <div class="measured-readout" role="status"><div class="readout-content"><template v-if="hovered"><b>{{ hovered.doc.name }} · 节点 {{ hovered.index+1 }} · {{ fmt(hovered.x) }} {{ hovered.doc.spectrum.unit }}</b><span v-for="c in hovered.values" :key="c.label"><i class="readout-dot" :style="{background:c.color}" />{{ c.label }}：{{ fmt(c.y) }}</span><span v-if="hovered.last>hovered.first">重复轴 {{ hovered.first+1 }}–{{ hovered.last+1 }} · ←／→逐点</span></template><span v-else class="hint">悬停读取原始节点（跨文件吸附最近曲线）</span></div></div>
    <div class="chart-bottom"><span>{{ fmt(range[0]) }} — {{ fmt(range[1]) }} {{ primaryUnit ?? '' }}</span><details><summary>操作</summary><small>滚轮缩放 · 框选 · Shift／中键平移 · 概览联动 · ←／→逐节点 · Home全谱 · 自适应强度后锁定纵轴 · 点击图例切换文件/曲线显隐</small></details></div>
    <canvas ref="overview" class="measured-overview" role="img" aria-label="测量全局概览与选区" title="全局强度概览；拖动联动主图横向选区" @pointerdown="down($event,true)" @pointermove="move($event,true)" @pointerup="up($event,true)" @pointercancel="drag=null" />
    <div v-if="primaryUnit==='nm'&&overviewSegments.length" class="overview-bands" aria-label="概览波长分区"><div class="overview-band-track"><span v-for="band in overviewSegments" :key="band.name" class="overview-band-segment" role="img" tabindex="0" :style="{left:band.left+'%',width:band.width+'%','--band-color':band.color}" :title="bandTitle(band)" :aria-label="bandTitle(band)" :aria-describedby="activeBand===band?bandTooltipId:undefined" @mouseenter="showBand(band,$event)" @mouseleave="clearBand" @focus="showBand(band,$event)" @blur="clearBand" @keydown.esc="clearBand" /></div></div>
    <Teleport to="body"><Transition name="overview-band-tip"><div v-if="activeBand" :id="bandTooltipId" ref="bandTooltip" class="overview-band-tooltip" role="tooltip" :style="{left:bandPoint.left+'px',top:bandPoint.top+'px'}"><i :style="{backgroundColor:activeBand.color}" aria-hidden="true" />{{ bandTitle(activeBand) }}</div></Transition></Teleport>
    <p v-if="primaryUnit==='pixel'" class="hint">pixel 轴 · nm参考已禁用</p>
    <div v-else-if="enabledReferences.length" class="reference-legend"><span v-for="g in enabledReferences" :key="'bottom:'+g.id" :class="{'reference-empty':(referenceCounts.get(g.id)??0)===0}" :style="{color:(referenceCounts.get(g.id)??0)===0?'var(--muted)':referenceColor(g,dark)}">┆ {{ g.label }} · {{ referenceCounts.get(g.id)??0 }} 位置</span></div>
    <Teleport to="body"><section v-if="lineHits.length" ref="tooltip" class="browser-line-tooltip" role="region" aria-label="谱线位置参考详情" tabindex="0" :style="{left:linePoint.left+'px',top:linePoint.top+'px'}" @pointerenter="keepLine" @pointerleave="clearLine" @keydown.esc="clearLine"><header><b>谱线位置参考 · {{ lineHits.length }} 个命中位置</b><button type="button" class="icon-btn" aria-label="关闭参考详情" @click="clearLine"><AppIcon name="close" :size="13" /></button></header><article v-for="hit in lineHits" :key="hit.group.id+hit.position.wavelength_nm"><h3 :style="{color:referenceColor(hit.group,dark)}">{{ hit.group.label }} · {{ fmt(hit.position.wavelength_nm) }} nm</h3><small>{{ hit.group.source }} · 原波长 {{ hit.group.original_unit }}</small><div v-for="(record,r) in hit.position.records" :key="r"><dl v-for="state in record.states" :key="state.line"><dt>原行 {{ state.line }}</dt><dd></dd><dt>Aki</dt><dd>{{ state.aki||'—' }}<span v-if="state.aki"> {{ state.aki_unit||'（原单位未说明）' }}</span></dd><dt>Energy</dt><dd>{{ state.energy||'—' }}<span v-if="state.energy"> {{ state.energy_unit||'（原单位未说明）' }}</span></dd><dt>Configuration</dt><dd>{{ state.configuration||'—' }}</dd><dt>Term / J / g</dt><dd>{{ state.term||'—' }} / {{ state.j||'—' }} / {{ state.g||'—' }}</dd></dl></div></article><p>仅参考位置，不是元素鉴定；原行未推断为上下态。</p></section></Teleport>
  </section>
</template>
<style scoped>
.measured-chart{padding:20px 24px;min-width:0}.measured-main{display:block;width:100%;height:380px;touch-action:none;cursor:crosshair}.measured-overview{display:block;width:100%;height:94px;touch-action:none;cursor:crosshair;border:1px solid var(--border);border-radius:7px;background:var(--panel-soft)}.measured-readout{height:104px;min-height:104px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.readout-content{min-height:0;display:flex;align-content:flex-start;align-items:flex-start;flex-wrap:wrap;gap:6px 16px}.readout-content b,.readout-content small{flex-basis:100%}.readout-content small{color:var(--muted)}.readout-dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}.reference-legend{display:flex;gap:8px 16px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:10px}.panel-heading{gap:12px;align-items:flex-start}.chart-bottom{flex-wrap:wrap;gap:8px}.measured-label{font-size:12px;color:var(--muted);white-space:nowrap}.chart-legend-area{width:100%;justify-content:flex-end;margin:0 0 8px;display:flex;align-items:flex-start;gap:6px;flex-wrap:wrap;min-width:0}.measured-legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:4px 14px;min-width:0;max-width:100%}.measured-legend button{display:flex;align-items:baseline;gap:5px;border:0;background:transparent;color:var(--text);padding:3px 0;font-size:12px;min-width:0;max-width:100%;overflow-wrap:anywhere;text-align:left}.measured-legend i{display:block;width:13px;height:3px;background:var(--curve-color);flex:none;align-self:center}.measured-legend button.legend-hidden{color:var(--muted);text-decoration:line-through}.measured-legend button.legend-hidden i{background:var(--border)}.legend-reference{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text);white-space:nowrap;border:0;background:transparent;padding:0;cursor:pointer}.legend-reference.legend-off{color:var(--muted);text-decoration:line-through}.legend-reference.legend-off .dash-swatch{border-top-color:var(--border)}.reference-legend-column{display:grid;grid-auto-flow:column;grid-template-rows:repeat(4,auto);grid-auto-columns:max-content;gap:3px 14px;flex:none;padding-left:12px;border-left:1px solid var(--border);justify-items:end}.dash-swatch{display:block;width:16px;height:0;border-top:2px dashed var(--curve-color);flex:none}.legend-curve{font-weight:400;padding-left:14px!important}.legend-meta{font-size:10px;color:var(--muted)}.measured-empty{text-align:center;color:var(--muted);font-size:12px}.chart-bottom details{font-size:11px;color:var(--muted);max-width:100%}.chart-bottom summary{cursor:pointer;color:var(--accent-text)}.chart-actions{margin-left:auto;align-items:center;display:flex;gap:6px;flex-wrap:wrap;min-width:0}.chart-reset{flex:none}.browser-line-tooltip{position:fixed;z-index:var(--layer-tooltip,70);width:min(360px,calc(100vw - 24px));max-height:min(330px,calc(100dvh - 24px));overflow:auto;overscroll-behavior:contain;padding:12px 14px;border:1px solid var(--border);border-radius:9px;background:var(--panel-overlay);color:var(--text);box-shadow:var(--shadow-overlay);font-size:12px}.browser-line-tooltip header{display:flex;align-items:center;justify-content:space-between;gap:8px}.browser-line-tooltip header .icon-btn{width:25px;height:25px;flex:none}.browser-line-tooltip article{padding:8px 0;border-bottom:1px solid var(--border)}.browser-line-tooltip h3{font-size:13px;margin-bottom:3px}.browser-line-tooltip small,.browser-line-tooltip p{font-size:10px;color:var(--muted)}.browser-line-tooltip p{margin-top:9px}.browser-line-tooltip dl{display:grid;grid-template-columns:92px minmax(0,1fr);gap:3px 8px;margin:8px 0;padding-top:6px;border-top:1px solid var(--border)}.browser-line-tooltip dt{color:var(--muted)}.browser-line-tooltip dd{margin:0;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.browser-line-tooltip dd>span{margin-left:.35em}@media(max-width:740px){.panel-heading{flex-wrap:wrap}.chart-legend-area,.chart-actions{width:100%;justify-content:flex-start}.measured-legend{justify-content:flex-start}.reference-legend-column{justify-items:start}.measured-chart{padding:16px 12px}.measured-main{height:300px}.measured-readout{height:128px;min-height:128px}}
</style>
<style scoped>
.overview-bands{padding:0 14px;margin:6px 0 8px;min-width:0}.overview-band-track{position:relative;height:7px;border-radius:4px;background:var(--border);overflow:hidden}.overview-band-segment{position:absolute;top:0;bottom:0;display:block;background:var(--band-color);cursor:pointer;transition:filter .15s ease}.overview-band-segment:hover,.overview-band-segment:focus-visible{filter:brightness(1.15);outline:1px solid var(--text);outline-offset:-1px}.overview-band-tooltip{position:fixed;z-index:var(--layer-tooltip,70);display:flex;align-items:center;gap:6px;max-width:calc(100vw - 16px);padding:5px 8px;border:1px solid var(--border);border-radius:5px;background:var(--panel-overlay,var(--panel));color:var(--text);box-shadow:var(--shadow-overlay);font-size:11px;font-weight:500;pointer-events:none}.overview-band-tooltip i{width:6px;height:6px;border-radius:50%;flex:none}.overview-band-tip-enter-active,.overview-band-tip-leave-active{transition:opacity .12s ease}.overview-band-tip-enter-from,.overview-band-tip-leave-to{opacity:0}@media(prefers-reduced-motion:reduce){.overview-band-segment,.overview-band-tip-enter-active,.overview-band-tip-leave-active{transition:none}}:global(:root[data-reduced-motion=true]) .overview-band-segment,:global(:root[data-reduced-motion=true]) .overview-band-tip-enter-active,:global(:root[data-reduced-motion=true]) .overview-band-tip-leave-active{transition:none}
</style>
