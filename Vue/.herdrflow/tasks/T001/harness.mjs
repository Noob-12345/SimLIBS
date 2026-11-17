import {createApp,h,markRaw,nextTick} from 'vue'
import App from '/src/App.vue'
import BrowserSpectrumChart from '/src/components/BrowserSpectrumChart.vue'
import {page} from '/src/lib/workbench.ts'
import {preferences,savedPreferences} from '/src/lib/preferences.ts'
import {spectrumBrowser as state,importSpectrum,applySpectrum,loadReferences,runProcessing} from '/src/lib/spectrumBrowser.ts'
preferences.endpoint='http://127.0.0.1:18521'
preferences.backendToken='browser-cdp-fixture'
preferences.reducedMotion=true
savedPreferences.value={...savedPreferences.value,endpoint:preferences.endpoint,backendToken:preferences.backendToken,reducedMotion:true}
page.value='spectrum-browser'
// Isolated UI fixtures only; this harness is not shipped or used for scientific results.
window.__frames={}
const proto=CanvasRenderingContext2D.prototype
for(const method of ['clearRect','fillText','beginPath','moveTo','lineTo','stroke']){
  const original=proto[method]
  proto[method]=function(...args){
    const kind=this.canvas.classList.contains('measured-main')?'main':this.canvas.classList.contains('measured-overview')?'overview':null
    if(kind){
      if(method==='clearRect')window.__frames[kind]={texts:[],strokes:[],invalid:[]}
      const frame=window.__frames[kind]
      if(frame){
        if(method==='fillText')frame.texts.push({text:String(args[0]),x:args[1],y:args[2]})
        if(method==='beginPath')this.__t001Path=[]
        if(method==='moveTo'||method==='lineTo'){this.__t001Path??=[];this.__t001Path.push([method,...args]);if(args.some(value=>!Number.isFinite(value)))frame.invalid.push([method,...args.map(String)])}
        if(method==='stroke')frame.strokes.push({path:[...(this.__t001Path??[])],color:this.strokeStyle,width:this.lineWidth,dash:this.getLineDash()})
      }
    }
    return original.apply(this,args)
  }
}
let app=createApp(App);app.mount('#app');await nextTick()
window.fixture={ready:true,state,preferences,importSpectrum,applySpectrum,loadReferences,runProcessing,
  mountChartOnly(){app.unmount();app=createApp({render(){return h(BrowserSpectrumChart,{spectrum:state.spectrum,references:[],view:state.view,'onUpdate:view':value=>{state.view=value}})}});app.mount('#app')},
  setTestData(xs,curves){state.processingResult=null;state.processingView='original';state.hiddenCurves=[];state.spectrum=markRaw({name:'T001 labelled isolated UI test',format:'ui-test',sha256:'T001-ui-test-'+Date.now(),unit:'nm',nodes:xs.length,xs,curves:curves.map((ys,i)=>({id:'test'+i,label:'UI test '+i,ys})),provenance:{isolatedUiTest:true}});state.view=null},
  dispose(){app.unmount()}}
