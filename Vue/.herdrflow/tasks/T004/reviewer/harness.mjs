import {createApp,nextTick} from 'vue'
import App from '/src/App.vue'
import {page} from '/src/lib/workbench.ts'
import {preferences,savedPreferences} from '/src/lib/preferences.ts'
import {spectrumBrowser as state,loadReferences,loadNistReferences,cancelReferences,clearReferences} from '/src/lib/spectrumBrowser.ts'
preferences.endpoint='http://127.0.0.1:18524';preferences.backendToken='browser-cdp-t004';preferences.reducedMotion=true
savedPreferences.value={...savedPreferences.value,endpoint:preferences.endpoint,backendToken:preferences.backendToken,reducedMotion:true}
page.value='spectrum-browser'
const app=createApp(App);app.mount('#app');await nextTick()
const realFetch=window.fetch.bind(window)
window.gate={mode:'normal',arrived:false,release:null}
window.fetch=async (url,opts)=>{
  if(String(url).endsWith('/spectrum-browser/references')&&opts?.body&&JSON.parse(opts.body).source==='nist'&&window.gate.mode!=='normal'){
    const mode=window.gate.mode
    if(mode==='fail')return new Response(JSON.stringify({error:{message:'reviewer injected failure'}}),{status:500,headers:{'Content-Type':'application/json'}})
    const response=await realFetch(url,{...opts,signal:undefined})
    window.gate.arrived=true
    await new Promise(resolve=>window.gate.release=resolve)
    return response
  }
  return realFetch(url,opts)
}
window.fixture={ready:true,state,page,loadReferences,loadNistReferences,cancelReferences,clearReferences,dispose(){app.unmount()}}
