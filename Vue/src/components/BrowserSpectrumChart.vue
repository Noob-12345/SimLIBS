<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { elementColor } from '../lib/model'
import { spectrumBrowser, type Measurement, type ReferenceGroup, type ReferencePosition } from '../lib/spectrumBrowser'
const props=defineProps<{spectrum:Measurement;references:ReferenceGroup[]}>()
const view=defineModel<[number,number]|null>('view',{required:true})
const canvas=ref<HTMLCanvasElement>(),overview=ref<HTMLCanvasElement>(),host=ref<HTMLElement>()
const hover=ref<number|null>(null),drag=ref<{kind:'zoom'|'pan'|'overview';x:number;now:number;initial:[number,number];pointerId:number}|null>(null)
const full=computed<[number,number]>(()=>{
  const xs=props.spectrum.xs,low=xs[0],high=xs[xs.length-1]
  return low!==undefined&&high!==undefined&&Number.isFinite(low)&&Number.isFinite(high)&&high>low?[low,high]:[0,1]
})
const range=computed<[number,number]>(()=>{
  const candidate=view.value??full.value
  return candidate[1]>candidate[0]?candidate:full.value
})
const enabledReferences=computed(()=>props.spectrum.unit==='nm'?props.references:[])
const processing=computed(()=>spectrumBrowser.processingResult?.source.sha256===props.spectrum.sha256?spectrumBrowser.processingResult:null)
const legendCurves=computed(()=>{const result=processing.value,mode=spectrumBrowser.processingView;if(result&&mode!=='original'){const ys=mode==='background'?result.background:result.corrected;if(ys)return[{id:'derived:'+result.curve+':'+mode,label:(props.spectrum.curves.find(c=>c.id===result.curve)?.label??result.curve)+' · '+(mode==='background'?'背景':'扣背景'),ys}]}return props.spectrum.curves})
const displayCurves=computed(()=>legendCurves.value.filter(c=>!spectrumBrowser.hiddenCurves.includes(c.id)))
type IntensityRange=[number,number]
function paddedIntensityRange(min:number,max:number):IntensityRange{
  if(!Number.isFinite(min)||!Number.isFinite(max))return[-1,1]
  if(min>max)[min,max]=[max,min]
  const span=max-min
  const pad=span>0?(Number.isFinite(span)?span*.08:Math.max(Math.abs(min),Math.abs(max))*.08):Math.max(1,Math.abs(min)*.08)
  const low=Math.max(-Number.MAX_VALUE,min-pad),high=Math.min(Number.MAX_VALUE,max+pad)
  return high>low?[low,high]:[-1,1]
}
function interpolatedIntensity(curve:{ys:number[]},x:number){
  const xs=props.spectrum.xs,right=lower(xs,x)
  if(!xs.length)return Number.NaN
  if(right===0)return curve.ys[0]!
  if(right===xs.length)return curve.ys[xs.length-1]!
  if(xs[right]===x)return curve.ys[right]!
  const left=right-1,x0=xs[left]!,x1=xs[right]!,y0=curve.ys[left]!,y1=curve.ys[right]!
  if(x1===x0)return y0
  const ratio=(x-x0)/(x1-x0)
  return y0*(1-ratio)+y1*ratio
}
function intensityRange(selection:[number,number],curves=displayCurves.value):IntensityRange{
  const xs=props.spectrum.xs,low=Math.min(selection[0],selection[1]),high=Math.max(selection[0],selection[1])
  let min=Infinity,max=-Infinity
  const add=(value:number)=>{if(Number.isFinite(value)){min=Math.min(min,value);max=Math.max(max,value)}}
  const start=lower(xs,low),end=upper(xs,high)
  for(const curve of curves){
    for(let i=start;i<end;i++)add(curve.ys[i]!)
    add(interpolatedIntensity(curve,low));add(interpolatedIntensity(curve,high))
  }
  return paddedIntensityRange(min,max)
}
const globalIntensity=computed<IntensityRange>(()=>intensityRange(full.value))
const adaptiveIntensity=ref<IntensityRange|null>(null)
const activeIntensity=computed<IntensityRange>(()=>adaptiveIntensity.value??globalIntensity.value)
const palette=[210,24,150,285,350,185,55,255,105,325,0,225,75,300,170,40]
const dark=ref(false)
function curveColor(id:string){const source=id.startsWith('derived:')?processing.value?.curve:id,index=Math.max(0,props.spectrum.curves.findIndex(c=>c.id===source));return 'hsl('+palette[index%palette.length]+' 68% '+(dark.value?'69%':'39%')+')'}
function toggleCurve(id:string){const ids=spectrumBrowser.hiddenCurves;spectrumBrowser.hiddenCurves=ids.includes(id)?ids.filter(v=>v!==id):[...ids,id];hover.value=null;clearLine();schedule()}
const lineHits=ref<{group:ReferenceGroup;position:ReferencePosition}[]>([]),tooltip=ref<HTMLElement>(),linePoint=ref({left:12,top:12})
let lineTimer:ReturnType<typeof setTimeout>|undefined
function clearLine(){clearTimeout(lineTimer);lineHits.value=[]}
function keepLine(){clearTimeout(lineTimer)}
function leaveLine(){clearTimeout(lineTimer);lineTimer=setTimeout(clearLine,220)}
function scrollLine(event:Event){if(event.target instanceof Node&&tooltip.value?.contains(event.target))return;clearLine()}
function hitLine(event:PointerEvent){
  const el=canvas.value!,box=el.getBoundingClientRect(),g=geometry(el),px=event.clientX-box.left,py=event.clientY-box.top
  if(drag.value||props.spectrum.unit!=='nm'||px<g.left||px>g.w-g.right||py<g.top||py>g.h-g.bottom){clearLine();return}
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
function resizePlot(){const rect=canvas.value?.getBoundingClientRect();if(rect&&(rect.width!==lastPlotWidth||rect.height!==lastPlotHeight)){lastPlotWidth=rect.width;lastPlotHeight=rect.height;clearLine()}schedule()}
const fmt=(v:number)=>Number.isFinite(v)?Number(v.toPrecision(7)).toString():'—'
function setRange(a:number,b:number){
  let width=Math.abs(b-a),left=Math.min(a,b),total=full.value[1]-full.value[0]
  if(width<total*1e-9)return
  width=Math.min(total,width);left=Math.max(full.value[0],Math.min(full.value[1]-width,left));view.value=[left,left+width]
}
function reset(){adaptiveIntensity.value=null;view.value=null;hover.value=null;clearLine();schedule()}
function showGlobalIntensity(){adaptiveIntensity.value=null;schedule()}
function adaptIntensity(){adaptiveIntensity.value=intensityRange(range.value);hover.value=null;clearLine();schedule()}
function lower(xs:number[],x:number){let a=0,b=xs.length;while(a<b){const m=(a+b)>>>1;if(xs[m]!<x)a=m+1;else b=m}return a}
function upper(xs:number[],x:number){let a=0,b=xs.length;while(a<b){const m=(a+b)>>>1;if(xs[m]!<=x)a=m+1;else b=m}return a}
function nearest(x:number){const xs=props.spectrum.xs,i=lower(xs,x);return i===0?0:i===xs.length?xs.length-1:x-xs[i-1]!<=xs[i]!-x?i-1:i}
const hovered=computed(()=>{
  if(hover.value===null||hover.value<0||hover.value>=props.spectrum.xs.length)return null
  const i=hover.value,x=props.spectrum.xs[i]!,first=lower(props.spectrum.xs,x);let last=first
  while(last+1<props.spectrum.nodes&&props.spectrum.xs[last+1]===x)last++
  return {index:i,x,first,last,values:displayCurves.value.map(c=>({label:c.label,y:c.ys[i]!}))}
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
  const xs=props.spectrum.xs,from=Math.max(0,lower(xs,s[0])-1);let to=lower(xs,s[1]);while(to<xs.length&&xs[to]===s[1])to++;to=Math.min(xs.length,to+1)
  const [ymin,ymax]=yRange
  const X=(x:number)=>g.left+(x-s[0])/(s[1]-s[0])*pw,Y=(y:number)=>g.top+(ymax/2-y/2)/(ymax/2-ymin/2)*ph
  ctx.font='11px '+css.getPropertyValue('--font-code');ctx.fillStyle=color('--muted');ctx.lineWidth=1
  if(!mini){for(let i=0;i<=4;i++){const y=ymin*(1-i/4)+ymax*i/4;ctx.globalAlpha=.2;ctx.strokeStyle=color('--muted');ctx.beginPath();ctx.moveTo(g.left,Y(y));ctx.lineTo(g.w-g.right,Y(y));ctx.stroke();ctx.globalAlpha=1;ctx.textAlign='right';ctx.fillText(fmt(y),g.left-9,Y(y)+4)}for(let i=0;i<=5;i++){const x=s[0]+(s[1]-s[0])*i/5;ctx.textAlign=i===0?'left':i===5?'right':'center';ctx.fillText(fmt(x),X(x),g.h-22)}ctx.textAlign='right';ctx.fillText(props.spectrum.unit==='nm'?'波长 / nm':'像素 / pixel',g.w-g.right,g.h-3)}
  ctx.save();ctx.beginPath();ctx.rect(g.left,g.top,pw,ph);ctx.clip()
  if(!mini){enabledReferences.value.forEach(group=>{ctx.strokeStyle=elementColor(group.element);ctx.globalAlpha=.55;ctx.setLineDash([4,5]);for(let i=lower(group.xs,s[0]);i<group.xs.length&&group.xs[i]!<=s[1];i++){const x=X(group.xs[i]!);ctx.beginPath();ctx.moveTo(x,g.top);ctx.lineTo(x,g.top+ph);ctx.stroke()}});ctx.setLineDash([]);ctx.globalAlpha=1}
  displayCurves.value.forEach(curve=>{
    ctx.strokeStyle=curveColor(curve.id);ctx.lineWidth=mini?1:1.5;ctx.beginPath()
    // Every visible node participates. Pixel buckets retain original min/max,
    // endpoints and their order; hover always reads the full original arrays.
    const bucket=Math.max(1,Math.ceil((to-from)/(pw*2)));let begun=false
    for(let start=from;start<to;start+=bucket){const end=Math.min(to,start+bucket);let low=start,high=start;for(let i=start+1;i<end;i++){if(curve.ys[i]!<curve.ys[low]!)low=i;if(curve.ys[i]!>curve.ys[high]!)high=i}for(const i of [...new Set([start,low,high,end-1])].sort((a,b)=>a-b)){const x=X(xs[i]!),y=Y(curve.ys[i]!);begun?ctx.lineTo(x,y):ctx.moveTo(x,y);begun=true}}
    ctx.stroke()
  })
  if(!mini&&hover.value!==null&&displayCurves.value.length){const i=hover.value,x=X(xs[i]!);ctx.strokeStyle=color('--muted');ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x,g.top);ctx.lineTo(x,g.top+ph);ctx.stroke();ctx.setLineDash([]);for(const c of displayCurves.value){ctx.fillStyle=curveColor(c.id);ctx.beginPath();ctx.arc(x,Y(c.ys[i]!),3,0,2*Math.PI);ctx.fill()}}
  const peakCurve=processing.value?displayCurves.value.find(c=>c.id===processing.value!.curve||c.id==='derived:'+processing.value!.curve+':corrected'):undefined
  if(!mini&&processing.value&&peakCurve){ctx.fillStyle=color('--bad');for(const peak of processing.value.peaks){if(peak.x<s[0]||peak.x>s[1])continue;const x=X(peak.x),y=Y(peakCurve.ys[peak.index]!);ctx.beginPath();ctx.moveTo(x,y-4);ctx.lineTo(x-4,y-11);ctx.lineTo(x+4,y-11);ctx.closePath();ctx.fill()}}
  if(mini){const a=X(range.value[0]),b=X(range.value[1]);ctx.fillStyle=color('--accent');ctx.globalAlpha=.15;ctx.fillRect(a,g.top,b-a,ph);ctx.globalAlpha=1;ctx.strokeStyle=color('--accent-text');ctx.strokeRect(a,g.top,b-a,ph)}
  if(!mini&&drag.value?.kind==='zoom'){ctx.fillStyle=color('--accent');ctx.globalAlpha=.16;ctx.fillRect(X(Math.min(drag.value.x,drag.value.now)),g.top,Math.abs(X(drag.value.x)-X(drag.value.now)),ph);ctx.globalAlpha=1}
  ctx.restore()
}
function down(event:PointerEvent,mini=false){
  if(event.button!==0&&event.button!==1)return
  clearLine();event.preventDefault();const x=position(event,mini);drag.value={kind:mini?'overview':event.button===1||event.shiftKey||event.altKey?'pan':'zoom',x,now:x,initial:[...range.value],pointerId:event.pointerId};(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function move(event:PointerEvent,mini=false){const x=position(event,mini),d=drag.value;if(d){d.now=x;if(d.kind==='pan'){const delta=(event.movementX/(geometry(canvas.value!).w-82))*(d.initial[1]-d.initial[0]);setRange(range.value[0]-delta,range.value[1]-delta)}else if(d.kind==='overview'){const width=d.initial[1]-d.initial[0];if(width<full.value[1]-full.value[0])setRange(x-width/2,x+width/2)}schedule()}else if(!mini){hover.value=displayCurves.value.length?nearest(x):null;hitLine(event);schedule()}}
function up(event:PointerEvent,mini=false){const d=drag.value;if(!d)return;const x=position(event,mini);if(d.kind==='zoom')setRange(d.x,x);if(d.kind==='overview'&&d.initial[1]-d.initial[0]>=full.value[1]-full.value[0])setRange(d.x,x);drag.value=null;const target=event.currentTarget as HTMLElement;if(target.hasPointerCapture(event.pointerId))target.releasePointerCapture(event.pointerId);schedule()}
function wheel(event:WheelEvent){const x=position(event),s=range.value,factor=event.deltaY>0?1.2:1/1.2;setRange(x-(x-s[0])*factor,x+(s[1]-x)*factor)}
function key(event:KeyboardEvent){if(['Home','Escape'].includes(event.key)){event.preventDefault();reset()}else if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();hover.value=Math.max(0,Math.min(props.spectrum.nodes-1,(hover.value??nearest((range.value[0]+range.value[1])/2))+(event.key==='ArrowLeft'?-1:1)));schedule()}else if(event.key==='+'||event.key==='-'){event.preventDefault();const s=range.value,c=(s[0]+s[1])/2,w=(s[1]-s[0])*(event.key==='+'?.8:1.25);setRange(c-w/2,c+w/2)}}
watch(()=>[props.spectrum,spectrumBrowser.processingResult,spectrumBrowser.processingView],()=>{adaptiveIntensity.value=null})
watch(()=>[props.spectrum,props.references,view.value,spectrumBrowser.processingResult,spectrumBrowser.processingView,spectrumBrowser.hiddenCurves],()=>{hover.value=null;clearLine();schedule()},{deep:false})
onMounted(()=>{observer=new ResizeObserver(resizePlot);observer.observe(host.value!);theme=new MutationObserver(()=>{clearLine();schedule()});theme.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','style']});window.addEventListener('scroll',scrollLine,true);window.addEventListener('resize',clearLine);schedule()})
onUnmounted(()=>{observer?.disconnect();theme?.disconnect();window.removeEventListener('scroll',scrollLine,true);window.removeEventListener('resize',clearLine);clearTimeout(lineTimer);cancelAnimationFrame(frame)})
</script>
<template>
  <section ref="host" class="panel measured-chart" aria-label="测量光谱图">
    <div class="panel-heading"><span class="measured-label">{{ spectrum.unit }} · {{ spectrum.nodes.toLocaleString() }} 节点</span><div class="chart-actions" aria-label="光谱范围操作"><button type="button" class="icon-btn chart-reset" aria-label="恢复完整波长范围并重置强度范围" title="恢复全波长与全局强度范围（Home）" @click="reset"><AppIcon name="reset" /></button><button type="button" class="icon-btn" aria-label="仅恢复全局强度范围并保持横向选区" title="恢复全局强度（保持当前横向选区）" @click="showGlobalIntensity"><AppIcon name="cross-arrows" /></button><button type="button" class="icon-btn" aria-label="按当前选区自适应强度并锁定纵轴" title="自适应当前选区强度并锁定纵轴" @click="adaptIntensity"><AppIcon name="vertical-arrows" /></button></div></div>
    <div class="chart-legend-area" aria-label="图表右上曲线图例"><div class="measured-legend" aria-label="曲线显示"><button v-for="c in legendCurves" :key="c.id" type="button" :class="{'legend-hidden':spectrumBrowser.hiddenCurves.includes(c.id)}" :style="{'--curve-color':curveColor(c.id)}" :aria-pressed="!spectrumBrowser.hiddenCurves.includes(c.id)" :aria-label="'显示曲线 '+c.label" :data-curve-id="c.id" :data-color="curveColor(c.id)" @click="toggleCurve(c.id)"><i />{{ c.label }}</button></div></div>
    <canvas ref="canvas" class="measured-main" role="img" tabindex="0" aria-label="测量局部光谱，可缩放平移和逐节点读取" title="横向缩放和平移保持强度范围；自适应强度仅在点击按钮时调整" :data-peaks="processing?.peaks.length??0" :data-view-low="range[0]" :data-view-high="range[1]" :data-visible-curves="displayCurves.length" @wheel.prevent="wheel" @pointerdown="down($event)" @pointermove="move($event)" @pointerleave="leave" @pointerup="up($event)" @pointercancel="drag=null;clearLine()" @keydown="key" @contextmenu.prevent="reset" @auxclick.prevent />
    <p v-if="!displayCurves.length" class="measured-empty" role="status">曲线已全部隐藏，点击图例恢复。</p>
    <div class="measured-readout" role="status"><div class="readout-content"><template v-if="hovered&&displayCurves.length"><b>节点 {{ hovered.index+1 }} · {{ fmt(hovered.x) }} {{ spectrum.unit }}</b><span v-for="c in hovered.values" :key="c.label">{{ c.label }}：{{ fmt(c.y) }}</span><span v-if="hovered.last>hovered.first">重复轴 {{ hovered.first+1 }}–{{ hovered.last+1 }} · ←／→逐点</span></template><span v-else class="hint">悬停读取原始节点</span></div></div>
    <div class="chart-bottom"><span>{{ fmt(range[0]) }} — {{ fmt(range[1]) }} {{ spectrum.unit }}</span><details><summary>操作</summary><small>滚轮缩放 · 框选 · Shift／中键平移 · 概览联动 · ←／→逐节点 · Home全谱 · 自适应强度后锁定纵轴</small></details></div>
    <canvas ref="overview" class="measured-overview" role="img" aria-label="测量全局概览与选区" title="全局强度概览；拖动联动主图横向选区" @pointerdown="down($event,true)" @pointermove="move($event,true)" @pointerup="up($event,true)" @pointercancel="drag=null" />
    <p v-if="spectrum.unit==='pixel'" class="hint">pixel 轴 · nm参考已禁用</p>
    <div v-else class="reference-legend"><span v-for="g in enabledReferences" :key="g.id" :style="{color:elementColor(g.element)}">┆ {{ g.label }} · {{ g.xs.filter(x=>x>=range[0]&&x<=range[1]).length }} 位置</span></div>
    <Teleport to="body"><section v-if="lineHits.length" ref="tooltip" class="browser-line-tooltip" role="region" aria-label="谱线位置参考详情" tabindex="0" :style="{left:linePoint.left+'px',top:linePoint.top+'px'}" @pointerenter="keepLine" @pointerleave="clearLine" @keydown.esc="clearLine"><header><b>谱线位置参考 · {{ lineHits.length }} 个命中位置</b><button type="button" class="icon-btn" aria-label="关闭参考详情" @click="clearLine"><AppIcon name="close" :size="13" /></button></header><article v-for="hit in lineHits" :key="hit.group.id+hit.position.wavelength_nm"><h3 :style="{color:elementColor(hit.group.element)}">{{ hit.group.label }} · {{ fmt(hit.position.wavelength_nm) }} nm</h3><small>{{ hit.group.source }} · 原波长 {{ hit.group.original_unit }}</small><div v-for="(record,r) in hit.position.records" :key="r"><dl v-for="state in record.states" :key="state.line"><dt>原行 {{ state.line }}</dt><dd></dd><dt>Aki</dt><dd>{{ state.aki||'—' }}<span v-if="state.aki"> {{ state.aki_unit||'（原单位未说明）' }}</span></dd><dt>Energy</dt><dd>{{ state.energy||'—' }}<span v-if="state.energy"> {{ state.energy_unit||'（原单位未说明）' }}</span></dd><dt>Configuration</dt><dd>{{ state.configuration||'—' }}</dd><dt>Term / J / g</dt><dd>{{ state.term||'—' }} / {{ state.j||'—' }} / {{ state.g||'—' }}</dd></dl></div></article><p>仅参考位置，不是元素鉴定；原行未推断为上下态。</p></section></Teleport>
  </section>
</template>
<style scoped>
.measured-chart{padding:20px 24px;min-width:0}.measured-main{display:block;width:100%;height:380px;touch-action:none;cursor:crosshair}.measured-overview{display:block;width:100%;height:94px;touch-action:none;cursor:crosshair;border:1px solid var(--border);border-radius:7px;background:var(--panel-soft)}.measured-readout{min-height:72px;padding:10px 12px;border:1px solid var(--border);border-radius:7px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.readout-content{min-height:50px;display:flex;align-content:flex-start;align-items:flex-start;flex-wrap:wrap;gap:6px 16px}.readout-content b,.readout-content small{flex-basis:100%}.readout-content small{color:var(--muted)}.reference-legend{display:flex;gap:8px 16px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:10px}.panel-heading{gap:12px;align-items:flex-start}.chart-bottom{flex-wrap:wrap;gap:8px}@media(max-width:740px){.measured-chart{padding:16px 12px}.measured-main{height:300px}.measured-readout{min-height:96px}}
</style>
<style scoped>
.chart-actions{margin-left:auto;align-items:center}.chart-legend-area{width:100%;justify-content:flex-end;margin:0 0 8px}.measured-legend{max-width:100%;justify-content:flex-end}.measured-legend button{max-width:100%}@media(max-width:740px){.chart-actions{width:100%}.chart-legend-area{justify-content:flex-end}.measured-legend{justify-content:flex-end}}
</style>
<style scoped>
.measured-readout{height:104px;min-height:104px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable}.readout-content{min-height:0}@media(max-width:740px){.measured-readout{height:128px;min-height:128px}}
</style>
<style scoped>
.browser-line-tooltip dd > span{margin-left:.35em}
</style>
<style scoped>
.measured-label{font-size:12px;color:var(--muted);white-space:nowrap}.measured-tools{display:flex;justify-content:flex-end;align-items:flex-start;gap:18px;margin-left:auto;min-width:0}.chart-legend-area,.chart-actions{display:flex;align-items:flex-start;gap:6px;flex-wrap:wrap;min-width:0}.chart-legend-area{justify-content:flex-end}.chart-actions{justify-content:flex-end}.chart-area-label{flex-basis:100%;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.chart-reset{flex:none}.measured-legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px 12px;min-width:0}.measured-legend button{display:flex;align-items:center;gap:5px;border:0;background:transparent;color:var(--text);padding:3px 0;font-size:12px;min-width:0;overflow-wrap:anywhere;text-align:left}.measured-legend i{display:block;width:13px;height:3px;background:var(--curve-color);flex:none}.measured-legend button.legend-hidden{color:var(--muted);text-decoration:line-through}.measured-legend button.legend-hidden i{background:var(--border)}.measured-empty{text-align:center;color:var(--muted);font-size:12px}.chart-bottom details{font-size:11px;color:var(--muted);max-width:100%}.chart-bottom summary{cursor:pointer;color:var(--accent-text)}.browser-line-tooltip{position:fixed;z-index:var(--layer-tooltip,70);width:min(360px,calc(100vw - 24px));max-height:min(330px,calc(100dvh - 24px));overflow:auto;overscroll-behavior:contain;padding:12px 14px;border:1px solid var(--border);border-radius:9px;background:var(--panel-overlay);color:var(--text);box-shadow:var(--shadow-overlay);font-size:12px}.browser-line-tooltip header{display:flex;align-items:center;justify-content:space-between;gap:8px}.browser-line-tooltip header .icon-btn{width:25px;height:25px;flex:none}.browser-line-tooltip article{padding:8px 0;border-bottom:1px solid var(--border)}.browser-line-tooltip h3{font-size:13px;margin-bottom:3px}.browser-line-tooltip small,.browser-line-tooltip p{font-size:10px;color:var(--muted)}.browser-line-tooltip p{margin-top:9px}.browser-line-tooltip dl{display:grid;grid-template-columns:92px minmax(0,1fr);gap:3px 8px;margin:8px 0;padding-top:6px;border-top:1px solid var(--border)}.browser-line-tooltip dt{color:var(--muted)}.browser-line-tooltip dd{margin:0;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}@media(max-width:740px){.panel-heading{flex-wrap:wrap}.measured-tools{width:100%;max-width:100%;flex:1 1 100%;flex-wrap:wrap;gap:10px}.chart-legend-area,.chart-actions{width:100%;flex:1 1 100%;justify-content:flex-start}.chart-area-label{flex-basis:100%}.measured-legend{width:100%;flex:1 1 100%;justify-content:flex-start}.chart-actions{align-items:center}.measured-main{height:300px}}
</style>
