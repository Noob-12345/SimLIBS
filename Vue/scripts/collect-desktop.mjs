import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const pkg = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'))
const release = path.join(root, 'src-tauri', 'target', 'release')
const nsisDirectory = path.join(release, 'bundle', 'nsis')
const installer = (await fs.readdir(nsisDirectory)).find(name => name === `SimLIBS_${pkg.version}_x64-setup.exe`)
if (!installer) throw new Error(`没有找到本次版本 ${pkg.version} 的 x64 NSIS 安装包，请先执行 desktop:build`)
const out = path.join(root, 'dist-desktop')
const relativeOut = path.relative(root, out)
if (relativeOut.startsWith('..') || path.isAbsolute(relativeOut)) throw new Error('桌面产物必须收集到当前项目目录')
await fs.mkdir(out, { recursive: true })
const artifacts = []
for (const [source, name, kind] of [
  [path.join(release, 'simlibs-vue.exe'), 'SimLIBS.exe', 'windows-x64-application'],
  [path.join(nsisDirectory, installer), 'SimLIBS-Setup.exe', 'nsis-installer']
]) {
  const original = await fs.readFile(source)
  if (original.toString('ascii', 0, 2) !== 'MZ') throw new Error(`产物不是 Windows 可执行文件：${source}`)
  const destination = path.join(out, name)
  await fs.copyFile(source, destination)
  const copied = await fs.readFile(destination)
  const hash = data => crypto.createHash('sha256').update(data).digest('hex')
  if (hash(original) !== hash(copied)) throw new Error(`复制后 SHA256 不一致：${name}`)
  artifacts.push({ kind, file: name, source: path.relative(root, source), bytes: copied.length, sha256: hash(copied) })
}
// Match the explicit production bundle allowlist; never collect test/cache/output files.
const backendFiles = []
for (const [directory, accept] of [
  ['simlibs_ui', name => name.endsWith('.py')],
  ['web', name => ['server.py', 'backend_api.py', 'real_backend.py', 'sampling.py'].includes(name)],
  ['source/simLIBS', name => name.endsWith('.py') || name === 'py.typed'],
  ['source', name => name.startsWith('LICENSE')],
  ['Linedatabase', name => /\.(csv|json|md)$/i.test(name)],
  ['', name => name === 'README.md']
]) {
  for (const name of await fs.readdir(path.join(root, 'backend', directory))) {
    if (!accept(name)) continue
    const relative = path.posix.join('backend', directory, name)
    const source = path.join(root, relative), destination = path.join(out, relative)
    await fs.mkdir(path.dirname(destination), { recursive: true }); await fs.copyFile(source, destination)
    const data = await fs.readFile(destination), original = await fs.readFile(source)
    const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex')
    if (hash(data) !== hash(original)) throw new Error(`backend 复制校验失败：${relative}`)
    backendFiles.push({ kind: 'python-backend-resource', file: relative, bytes: data.length, sha256: hash(data) })
  }
}
artifacts.push(...backendFiles)
const instructions = `SimLIBS Windows 桌面软件 · ${pkg.version}\r\n交付目录：${relativeOut}\r\n\r\n` +
  `直接使用：双击 SimLIBS.exe，或“启动 SimLIBS.cmd”。程序自动启动本程序拥有的 Python 后端，无需手工启动服务。EXE 必须与同目录 backend 文件夹一起分发。\r\n` +
  `安装使用：自行双击 SimLIBS-Setup.exe，按向导安装到当前 Windows 用户。生成者没有执行或安装此安装包。\r\n` +
  `要求：Windows x64，系统 WebView2 Runtime。安装包使用 Tauri 默认的 WebView2 检测/引导策略，缺少运行时可能需联网。\r\n` +
  `已接入真实 Python 后端，local=本地 LTE/Saha；client=NIST 计算线强+Python展宽；server=NIST官方页面。默认空谱，失败不回退示意结果。\r\n` +
  `未打包 Python runtime：需配置具有原后端依赖的 Python 3.11 环境。本机默认 E:/Anaconda/envs/simLIBS/python.exe，可用 SIMLIBS_UI_PYTHON 或设置指定解释器。安装包不自动安装 Python/全局依赖，不保证跨机器免 Python。\r\n` +
  `配置/session/驱动缓存/默认任务输出写入当前用户 app_local_data_dir；backend 资源只读。关闭应用只清理 owned 后端和所属 worker/Chrome，不影响其他服务。\r\n` +
  `CSV 打开及 CSV/JSON/PNG/GIF/ZIP 另存为沿用 Windows 原生对话框动态scope；取消不写文件，保存失败在界面说明。\r\n` +
  `程序前端静态资源嵌入 EXE。正式运行不启动 1420 服务。\r\n` +
  `此构建未配置代码签名。安装程序未实际安装验收，原生对话框实际点击与独立桌面验收见本项目任务 review.md。\r\n` +
  `SHA256SUMS.txt 和 artifact-manifest.json 提供源产物路径、字节数与 SHA256。\r\n`
await fs.writeFile(path.join(out, '使用说明.txt'), '\uFEFF' + instructions, 'utf8')
await fs.writeFile(path.join(out, '启动 SimLIBS.cmd'), '@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0SimLIBS.exe"\r\n', 'ascii')
await fs.writeFile(path.join(out, 'SHA256SUMS.txt'), artifacts.map(a => `${a.sha256}  ${a.file}`).join('\r\n') + '\r\n', 'ascii')
await fs.writeFile(path.join(out, 'artifact-manifest.json'), JSON.stringify({ version: pkg.version, deliveryDirectory: relativeOut, collectedAt: new Date().toISOString(), runtime: 'Windows x64 / system WebView2 / external Python 3.11', frontend: 'embedded static dist', scientificSource: 'real Python / local LTE-Saha / NIST', installerExecuted: false, artifacts }, null, 2), 'utf8')
console.log(JSON.stringify({ directory: out, artifacts }, null, 2))
