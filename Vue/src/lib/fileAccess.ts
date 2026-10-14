import { ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { open, save } from '@tauri-apps/plugin-dialog'
import { readTextFile, stat, writeFile, writeTextFile } from '@tauri-apps/plugin-fs'
import { savedPreferences } from './preferences'
import { defaultOutputDirectory, ensureDefaultOutputDirectory, outputDefaultPath, outputDirectoryIssue } from './outputDirectory'

export const desktopHost = typeof window !== 'undefined' && isTauri()
export type SaveResult = { status: 'saved'; path: string; bytes: number } | { status: 'cancelled' } | { status: 'failed'; message: string } | { status: 'browser-download' }
export type OpenResult = { status: 'opened'; path: string; name: string; text: string; bytes: number } | { status: 'cancelled' } | { status: 'failed'; message: string }
const maxCsvBytes = 2_000_000
function messageOf(error: unknown): string { return error instanceof Error ? error.message : String(error || '未知文件错误') }
function fileName(path: string): string { return path.split(/[\\/]/).pop() || path }
function validateCsv(name: string, size: number) {
  if (!/\.csv$/i.test(name)) throw new Error('请选择 .csv 文件')
  if (!Number.isFinite(size) || size < 0 || size > maxCsvBytes) throw new Error('CSV 最大支持 2 MB')
}

export async function openCsvTemplate(): Promise<OpenResult> {
  try {
    if (!desktopHost) throw new Error('开发辅助模式请使用文件选择控件')
    const path = await open({ title: '打开 CSV 模板', directory: false, multiple: false, filters: [{ name: 'CSV 模板', extensions: ['csv'] }] })
    if (path === null) return { status: 'cancelled' }
    const info = await stat(path)
    if (!info.isFile) throw new Error('请选择 CSV 文件，不能选择文件夹')
    const name = fileName(path); validateCsv(name, info.size)
    const text = await readTextFile(path), bytes = new TextEncoder().encode(text).byteLength
    validateCsv(name, bytes)
    return { status: 'opened', path, name, text, bytes }
  } catch (error) { return { status: 'failed', message: `读取失败：${messageOf(error)}` } }
}

export async function readBrowserCsv(file: File): Promise<OpenResult> {
  try { validateCsv(file.name, file.size); const text = await file.text(), bytes = new TextEncoder().encode(text).byteLength; validateCsv(file.name, bytes); return { status: 'opened', path: file.name, name: file.name, text, bytes } }
  catch (error) { return { status: 'failed', message: `读取失败：${messageOf(error)}` } }
}

export async function saveDemoFile(filename: string, content: string | Blob, mime = 'text/plain;charset=utf-8'): Promise<SaveResult> {
  try {
    if (!desktopHost) {
      // Development only. A download request is not reported as a successful disk write.
      const blob = typeof content === 'string' ? new Blob([content], { type: mime }) : content
      const url = URL.createObjectURL(blob), a = document.createElement('a')
      try { a.href = url; a.download = filename; a.click() } finally { window.setTimeout(() => URL.revokeObjectURL(url), 1500) }
      return { status: 'browser-download' }
    }
    const extension = filename.split('.').pop()?.toLowerCase()
    if (!extension || !['csv', 'json', 'png', 'gif', 'zip'].includes(extension)) throw new Error('仅支持 CSV、JSON、PNG、GIF、ZIP 保存')
    const directory = savedPreferences.value.outputDirectory
    const directoryError = outputDirectoryIssue(directory)
    if (directoryError) throw new Error(directoryError)
    const isDefault = directory.replace(/\\/g, '/').replace(/\/$/, '').toLowerCase() === defaultOutputDirectory.toLowerCase()
    const initialDirectory = isDefault ? await ensureDefaultOutputDirectory() : directory
    const path = await save({ title: '另存为结果文件', defaultPath: outputDefaultPath(initialDirectory, filename), filters: [{ name: `${extension.toUpperCase()} 文件`, extensions: [extension] }] })
    if (path === null) return { status: 'cancelled' }
    // Do not append an extension or rewrite the path: dynamic scope grants this exact selection.
    let bytes: number
    if (typeof content === 'string') { bytes = new TextEncoder().encode(content).byteLength; await writeTextFile(path, content) }
    else { const data = new Uint8Array(await content.arrayBuffer()); bytes = data.byteLength; await writeFile(path, data) }
    return { status: 'saved', path, bytes }
  } catch (error) { return { status: 'failed', message: `保存失败：${messageOf(error)}` } }
}

export function useFileSave() {
  const pending = ref(false), feedback = ref(''), failed = ref(false)
  async function run(filename: string, content: string | Blob | (() => Promise<Blob>), mime?: string) {
    if (pending.value) return
    pending.value = true; feedback.value = ''; failed.value = false
    try {
      const result = await saveDemoFile(filename, typeof content === 'function' ? await content() : content, mime)
      if (result.status === 'saved') feedback.value = `已保存 ${result.bytes.toLocaleString()} 字节：${result.path}`
      if (result.status === 'cancelled') feedback.value = '已取消保存，未写入文件'
      if (result.status === 'browser-download') feedback.value = '开发辅助：已请求浏览器下载'
      if (result.status === 'failed') { failed.value = true; feedback.value = result.message }
    } catch (error) { failed.value = true; feedback.value = `导出失败：${messageOf(error)}` }
    finally { pending.value = false }
  }
  return { pending, feedback, failed, run }
}
