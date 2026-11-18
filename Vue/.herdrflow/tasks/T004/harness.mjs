import {createApp,nextTick} from 'vue'
import App from '/src/App.vue'
import {page} from '/src/lib/workbench.ts'
import {preferences,savedPreferences} from '/src/lib/preferences.ts'
import {spectrumBrowser as state,loadReferences} from '/src/lib/spectrumBrowser.ts'
preferences.endpoint='http://127.0.0.1:18524';preferences.backendToken='browser-cdp-t004';preferences.reducedMotion=true
savedPreferences.value={...savedPreferences.value,endpoint:preferences.endpoint,backendToken:preferences.backendToken,reducedMotion:true}
page.value='spectrum-browser'
const app=createApp(App);app.mount('#app');await nextTick()
window.fixture={ready:true,state,page,loadReferences,dispose(){app.unmount()}}
