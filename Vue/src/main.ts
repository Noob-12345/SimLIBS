import { createApp, nextTick } from 'vue'
import App from './App.vue'

declare global { interface Window { __SIMLIBS_BOOT__?: { ready(): void; fail(): void; readonly phase: string; startedAt: number } } }
async function mountWorkbench() {
  try {
    const app = createApp(App)
    app.config.errorHandler = error => { console.error(error); window.__SIMLIBS_BOOT__?.fail() }
    app.mount('#app')
    await nextTick()
    if (document.fonts?.ready) await document.fonts.ready
    // First layout/paint when visible; the bounded fallback also works in minimized windows.
    await Promise.race([new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))), new Promise<void>(resolve => setTimeout(resolve, 250))])
    window.__SIMLIBS_BOOT__?.ready()
  } catch (error) { console.error(error); window.__SIMLIBS_BOOT__?.fail() }
}
void mountWorkbench()
