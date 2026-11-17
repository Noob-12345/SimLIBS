import {createApp,nextTick} from 'vue'
import App from '/src/App.vue'
import {page} from '/src/lib/workbench.ts'
import {preferences,savedPreferences} from '/src/lib/preferences.ts'
import {spectrumBrowser as state,importSpectrum,cancelSpectrum,updateSpectrumSelection,disposeSpectrumSelection,loadReferences,runProcessing} from '/src/lib/spectrumBrowser.ts'
preferences.endpoint='http://127.0.0.1:18522';preferences.backendToken='browser-cdp-t002';preferences.reducedMotion=true
savedPreferences.value={...savedPreferences.value,endpoint:preferences.endpoint,backendToken:preferences.backendToken,reducedMotion:true}
page.value='spectrum-browser'
window.__t002Frames={}
const proto=CanvasRenderingContext2D.prototype
for(const method of ['clearRect','fillText','beginPath','moveTo','lineTo','stroke']){
  const original=proto[method]
  proto[method]=function(...args){
    const kind=this.canvas.classList.contains('measured-main')?'main':this.canvas.classList.contains('measured-overview')?'overview':null
    if(kind){if(method==='clearRect')window.__t002Frames[kind]={texts:[],strokes:[],invalid:[]};const frame=window.__t002Frames[kind];if(frame){if(method==='fillText')frame.texts.push({text:String(args[0]),x:args[1],y:args[2]});if(method==='beginPath')this.__t002Path=[];if(method==='moveTo'||method==='lineTo'){this.__t002Path??=[];this.__t002Path.push([method,...args]);if(args.some(value=>!Number.isFinite(value)))frame.invalid.push(args.map(String))}if(method==='stroke')frame.strokes.push({path:[...(this.__t002Path??[])],dash:this.getLineDash()})}}
    return original.apply(this,args)
  }
}
const nativeFetch=window.fetch.bind(window),requests=[],controls={delays:[],ignoreAbort:false,failNextSelect:false}
window.fetch=async(input,init)=>{
  const url=String(input);if(!url.includes('/spectrum-browser/'))return nativeFetch(input,init)
  const body=init?.body?JSON.parse(init.body):null,select=url.endsWith('/select');requests.push({url,body,at:performance.now()})
  if(select&&controls.failNextSelect){controls.failNextSelect=false;return new Response(JSON.stringify({error:{message:'T002 isolated select failure'}}),{status:400,headers:{'Content-Type':'application/json'}})}
  const response=await nativeFetch(input,controls.ignoreAbort?{...init,signal:undefined}:init)
  const delay=select?(controls.delays.shift()??0):0;if(delay)await new Promise(resolve=>setTimeout(resolve,delay));return response
}
const app=createApp(App);app.mount('#app');await nextTick()
window.fixture={ready:true,state,page,preferences,requests,controls,importSpectrum,cancelSpectrum,updateSpectrumSelection,loadReferences,runProcessing,dispose(){disposeSpectrumSelection();app.unmount()},setDelays(values,ignoreAbort=true){controls.delays=[...values];controls.ignoreAbort=ignoreAbort},setFailNextSelect(){controls.failNextSelect=true}}
