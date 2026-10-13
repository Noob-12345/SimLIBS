import { createApp, nextTick } from 'vue'
import App from './App.vue'

declare global { interface Window { __SIMLIBS_BOOT__?: { step(node: 'module' | 'mounted' | 'fonts'): void; ready(): void; fail(): void; readonly phase: string; readonly progress: number; startedAt: number } } }
async function mountWorkbench() {
  try {
    window.__SIMLIBS_BOOT__?.step('module')
    const app = createApp(App)
    app.config.errorHandler = error => { console.error(error); window.__SIMLIBS_BOOT__?.fail() }
    app.mount('#app')
    await nextTick()
    window.__SIMLIBS_BOOT__?.step('mounted')
    if (document.fonts?.ready) await document.fonts.ready
    window.__SIMLIBS_BOOT__?.step('fonts')
    // First layout/paint when visible; the bounded fallback also works in minimized windows.
    await new Promise<void>(resolve => {
      let settled = false, first = 0, second = 0
      const finish = () => { if (settled) return; settled = true; clearTimeout(timer); cancelAnimationFrame(first); cancelAnimationFrame(second); resolve() }
      const timer = setTimeout(finish, 250)
      first = requestAnimationFrame(() => { second = requestAnimationFrame(finish) })
    })
    window.__SIMLIBS_BOOT__?.ready()
  } catch (error) { console.error(error); window.__SIMLIBS_BOOT__?.fail() }
}
void mountWorkbench()
