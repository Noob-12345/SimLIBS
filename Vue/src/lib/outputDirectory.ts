import { invoke, isTauri } from '@tauri-apps/api/core'
export const defaultOutputDirectory = 'D:/LIBS/SimLIBS/Vue/outputs'
export async function ensureDefaultOutputDirectory(): Promise<string> {
  return isTauri() ? await invoke<string>('default_output_directory') : defaultOutputDirectory
}
export function outputDirectoryIssue(value: string): string {
  return /^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)(?:[^<>:"|?*\x00-\x1f]*)$/.test(value.trim()) ? '' : '输出目录须为 Windows 绝对路径'
}
export function outputDefaultPath(directory: string, filename: string): string { return directory.trim().replace(/[\\/]+$/, '') + '/' + filename }
