import {createApp,h,markRaw,ref,nextTick} from 'vue'
import '/src/styles.css'
import BrowserSpectrumChart from '/src/components/BrowserSpectrumChart.vue'
// Labelled isolated UI data for icon button checks, never scientific results.
const spectrum=markRaw({name:'T005 isolated UI fixture',format:'ui-test',sha256:'t005-ui-test',unit:'nm',nodes:5,xs:[0,1,2,3,4],curves:[{id:'test',label:'UI fixture',ys:[0,10,2,6,1000]}],provenance:{isolatedUiTest:true}})
const view=ref(null)
window.ticks=[]
const original=CanvasRenderingContext2D.prototype.fillText,clear=CanvasRenderingContext2D.prototype.clearRect
CanvasRenderingContext2D.prototype.clearRect=function(...args){if(this.canvas.classList.contains('measured-main'))window.ticks=[];return clear.apply(this,args)}
CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...args){if(this.canvas.classList.contains('measured-main')&&x<64)window.ticks.push(Number(text));return original.call(this,text,x,y,...args)}
document.body.style.padding='20px';document.documentElement.dataset.theme='light'
const app=createApp({render(){return h(BrowserSpectrumChart,{spectrum,references:[],view:view.value,'onUpdate:view':value=>view.value=value})}});app.mount('#app');await nextTick()
window.fixture={ready:true,view,dispose(){app.unmount()}}
