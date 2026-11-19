import { isTauri, invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { reactive, watch, type WatchStopHandle } from 'vue'
import { connectBackend, envBootstrapNeeded, service } from './backend'
import { savedPreferences } from './preferences'
import { refreshTasks } from './workbench'

export interface EnvEvent { phase: string; detail: string; state: 'running' | 'done' | 'failed' | 'waiting' }
export const envSetup = reactive({
  active: false, running: false, failed: false, noToolchain: false,
  events: [] as EnvEvent[], finalError: ''
})

let unlisten: UnlistenFn | undefined, stopWatch: WatchStopHandle | undefined
// Attempts bound the auto loop: a freshly created environment that still fails
// to launch re-classifies here, but never restarts the bootstrap forever.
let attempts = 0, requested = false
const MAX_ATTEMPTS = 2

function record(event: EnvEvent) {
  envSetup.events.push(event)
  if (envSetup.events.length > 40) envSetup.events.splice(0, envSetup.events.length - 40)
  envSetup.running = event.state === 'running'
  if (event.state === 'waiting') envSetup.noToolchain = true
  if (event.state === 'failed') { envSetup.failed = true; envSetup.finalError = event.detail; requested = false }
  if (event.state === 'done') void reconnectAfterBootstrap()
}

async function reconnectAfterBootstrap() {
  requested = false
  try { await connectBackend(false, savedPreferences.value.pythonPath); await refreshTasks(); attempts = 0; reset() }
  catch { /* the service.error watch re-classifies the new failure */ }
}

function reset() { envSetup.active = false; envSetup.running = false; envSetup.failed = false; envSetup.noToolchain = false; envSetup.events = []; envSetup.finalError = '' }

export async function startBootstrap(usePython?: string): Promise<void> {
  if (requested || envSetup.running) return
  requested = true
  envSetup.failed = false; envSetup.finalError = ''
  try { await invoke(usePython ? 'use_python_for_env' : 'bootstrap_python', usePython ? { pythonPath: usePython } : undefined) }
  catch (error) { requested = false; envSetup.failed = true; envSetup.finalError = String(error instanceof Error ? error.message : error) }
}

export function retryBootstrap() { attempts = 0; envSetup.failed = false; envSetup.noToolchain = false; envSetup.events = []; void startBootstrap() }
export function useManualInterpreter(path: string) { envSetup.noToolchain = false; envSetup.events = []; void startBootstrap(path) }

export function installEnvironmentSetup(): void {
  if (!isTauri()) return
  void listen<EnvEvent>('env-progress', event => record(event.payload)).then(fn => { unlisten = fn })
  stopWatch = watch(() => service.error, error => {
    if (!error || !envBootstrapNeeded(error)) return
    envSetup.active = true
    if (attempts < MAX_ATTEMPTS) { attempts++; void startBootstrap() }
  })
}

export function uninstallEnvironmentSetup(): void { unlisten?.(); unlisten = undefined; stopWatch?.(); stopWatch = undefined }
