import {createApp,nextTick} from 'vue'
import App from '/src/App.vue'
import {page} from '/src/lib/workbench.ts'
import {preferences,savedPreferences} from '/src/lib/preferences.ts'
import {spectrumBrowser as state} from '/src/lib/spectrumBrowser.ts'
preferences.endpoint='http://127.0.0.1:18523';preferences.backendToken='browser-cdp-t003';preferences.reducedMotion=true
savedPreferences.value={...savedPreferences.value,endpoint:preferences.endpoint,backendToken:preferences.backendToken,reducedMotion:true}
page.value='spectrum-browser'
let delay=0
const nativeFetch=window.fetch.bind(window)
window.fetch=async(input,init)=>{const url=String(input);if(delay&&url.endsWith('/spectrum-browser/select'))await new Promise(resolve=>setTimeout(resolve,delay));return nativeFetch(input,init)}
const app=createApp(App);app.mount('#app');await nextTick()
window.fixture={ready:true,state,page,setDelay(ms){delay=ms},dispose(){app.unmount()}}
