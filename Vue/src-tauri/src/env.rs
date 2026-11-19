// Managed Python runtime bootstrap (Windows): conda-first, winget fallback,
// manual interpreter as the last resort. Only default-candidate interpreters
// can reach this module; an explicitly selected Python is never modified.
// Progress goes to the frontend through the `env-progress` event, and every
// long step streams its child output into state_dir/bootstrap.log so failures
// carry bounded evidence instead of silent exits.
use serde::Serialize;
use std::{fs, io::{Read, Seek, Write}, path::{Path, PathBuf}, process::{Command, Stdio}, sync::Mutex, thread, time::{Duration, Instant, SystemTime, UNIX_EPOCH}};
use tauri::{AppHandle, Emitter, Manager};

pub const PYTHON_SPEC: &str = "3.11";
const WINGET_PACKAGE: &str = "Python.Python.3.11";
// Same import surface the backend diagnostics check; server.py fails at import
// time when any of these is missing, so the probe must pass before relaunch.
const IMPORT_PROBE: &str = "import numpy,pandas,scipy,matplotlib,PIL,requests,bs4,selenium,webdriver_manager";

#[derive(Clone, Serialize)]
pub struct EnvProgress { pub phase: String, pub detail: String, pub state: String }
#[derive(Default)]
pub struct Bootstrap { pub running: bool, pub last: Option<EnvProgress> }
pub type BootstrapState = Mutex<Bootstrap>;

pub fn managed_python(directory: &Path) -> PathBuf { directory.join("runtime").join("simlibs-env").join("python.exe") }

fn emit(app: &AppHandle, phase: &str, detail: &str, state: &str) {
    let progress = EnvProgress { phase: phase.into(), detail: detail.into(), state: state.into() };
    if let Ok(mut guard) = app.state::<BootstrapState>().lock() { guard.last = Some(progress.clone()) }
    let _ = app.emit("env-progress", progress);
}

#[cfg(windows)]
fn hide(command: &mut Command) { use std::os::windows::process::CommandExt; command.creation_flags(0x08000000); }
#[cfg(not(windows))]
fn hide(_: &mut Command) {}

fn log_write(directory: &Path, phase: &str) -> Result<fs::File, String> {
    let mut file = fs::OpenOptions::new().create(true).append(true).open(directory.join("bootstrap.log")).map_err(|e| format!("引导日志打开失败：{e}"))?;
    let seconds = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let _ = writeln!(file, "===== {phase} · unix {seconds} =====");
    Ok(file)
}

fn log_tail(path: &Path, limit: u64) -> String {
    let mut file = match fs::File::open(path) { Ok(file) => file, Err(_) => return String::new() };
    let length = file.metadata().map(|m| m.len()).unwrap_or(0);
    let _ = file.seek(std::io::SeekFrom::Start(length.saturating_sub(limit)));
    let mut bytes = Vec::new();
    let _ = file.take(limit).read_to_end(&mut bytes);
    String::from_utf8_lossy(&bytes).lines().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join(" | ")
}

fn run_logged(mut command: Command, directory: &Path, phase: &str, deadline: Duration) -> Result<(), String> {
    let log = directory.join("bootstrap.log");
    let file = log_write(directory, phase)?;
    let stdout = file.try_clone().map_err(|e| format!("引导日志复制失败：{e}"))?;
    command.stdin(Stdio::null()).stdout(stdout).stderr(file); hide(&mut command);
    let mut child = command.spawn().map_err(|e| format!("{phase}启动失败：{e}"))?;
    let start = Instant::now();
    loop {
        match child.try_wait().map_err(|e| format!("{phase}状态读取失败：{e}"))? {
            Some(status) => return if status.success() { Ok(()) } else {
                let evidence = log_tail(&log, 2048);
                Err(format!("{phase}失败（退出码 {}）：{}", status.code().unwrap_or(-1), if evidence.is_empty() { format!("日志：{}", log.display()) } else { evidence }))
            },
            None if start.elapsed() > deadline => { let _ = child.kill(); let _ = child.wait(); return Err(format!("{phase}超时（超过 {} 秒）；日志：{}", deadline.as_secs(), log.display())) },
            None => thread::sleep(Duration::from_millis(120)),
        }
    }
}

fn capture(mut command: Command, timeout: Duration) -> Option<String> {
    command.stdin(Stdio::null()).stderr(Stdio::null()); hide(&mut command);
    let mut child = command.stdout(Stdio::piped()).spawn().ok()?;
    let start = Instant::now();
    let status = loop {
        match child.try_wait().ok().flatten() {
            Some(status) => break status,
            None if start.elapsed() > timeout => { let _ = child.kill(); let _ = child.wait(); return None }
            None => thread::sleep(Duration::from_millis(80)),
        }
    };
    if !status.success() { return None }
    let mut text = String::new();
    child.stdout.take()?.read_to_string(&mut text).ok()?;
    Some(text.trim().to_string())
}

pub fn probe_imports(python: &Path) -> Result<(), String> {
    let mut command = Command::new(python); command.args(["-B", "-c", IMPORT_PROBE]);
    match capture(command, Duration::from_secs(12)) { Some(_) => Ok(()), None => Err("后端依赖导入探测未通过".into()) }
}

fn conda_ok(conda: &Path) -> bool {
    let mut command = Command::new(conda); command.arg("--version");
    capture(command, Duration::from_secs(15)).is_some()
}

fn find_conda() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(text) = capture({ let mut command = Command::new("where"); command.arg("conda"); command }, Duration::from_secs(10)) {
        for line in text.lines() { let path = PathBuf::from(line.trim()); if path.is_file() { candidates.push(path) } }
    }
    let mut push_root = |root: &str| { for name in ["Anaconda3", "anaconda3", "Miniconda3", "miniconda3", "Anaconda", "Miniconda"] { candidates.push(Path::new(root).join(name).join("Scripts").join("conda.exe")) } };
    if let Ok(home) = std::env::var("USERPROFILE") { push_root(&home) }
    if let Ok(data) = std::env::var("ProgramData") { push_root(&data) }
    for root in ["C:\\", "D:\\", "E:\\"] { push_root(root) }
    candidates.into_iter().find(|path| conda_ok(path))
}

fn find_winget() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(local) = std::env::var("LOCALAPPDATA") { candidates.push(PathBuf::from(&local).join("Microsoft").join("WindowsApps").join("winget.exe")) }
    if let Some(text) = capture({ let mut command = Command::new("where"); command.arg("winget"); command }, Duration::from_secs(10)) {
        for line in text.lines() { let path = PathBuf::from(line.trim()); if path.is_file() { candidates.push(path) } }
    }
    candidates.into_iter().find(|path| { let mut command = Command::new(path); command.arg("--version"); capture(command, Duration::from_secs(20)).is_some() })
}

fn locate_installed_python() -> Option<PathBuf> {
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        let base = PathBuf::from(&local).join("Programs").join("Python");
        let direct = base.join("Python311").join("python.exe");
        if direct.is_file() { return Some(direct) }
        if let Ok(entries) = fs::read_dir(&base) { for entry in entries.flatten() { let candidate = entry.path().join("python.exe"); if candidate.is_file() { return Some(candidate) } } }
    }
    let machine = PathBuf::from(r"C:\Program Files\Python311\python.exe");
    if machine.is_file() { return Some(machine) }
    let mut command = Command::new("py"); command.args(["-3.11", "-c", "import sys;print(sys.executable)"]);
    capture(command, Duration::from_secs(20)).and_then(|text| {
        let path = PathBuf::from(text.lines().next().unwrap_or("").trim());
        if path.is_file() { Some(path) } else { None }
    })
}

enum Outcome { Done, WaitingManual }

fn bootstrap_flow(app: &AppHandle, source: Option<PathBuf>) -> Result<Outcome, String> {
    let directory = crate::backend::state_dir(app)?;
    fs::create_dir_all(&directory).map_err(|e| format!("应用数据目录创建失败：{e}"))?;
    let managed = directory.join("runtime").join("simlibs-env");
    let python = managed_python(&directory);
    let requirements = crate::backend::resources(app)?.join("requirements.txt");
    if !requirements.is_file() { return Err(format!("backend 资源缺少 requirements.txt：{}", requirements.display())) }
    // A partial or broken managed environment is our own artifact; rebuild it from scratch.
    if managed.exists() { let _ = fs::remove_dir_all(&managed); }
    fs::create_dir_all(directory.join("runtime")).map_err(|e| format!("托管环境目录创建失败：{e}"))?;
    let mut from_base: Option<PathBuf> = None;
    match source {
        Some(base) => from_base = Some(base),
        None => {
            emit(app, "conda", "正在检测本机 conda…", "running");
            if let Some(conda) = find_conda() {
                emit(app, "conda", &format!("使用 conda：{}；正在创建专用环境（可能需要几分钟）…", conda.display()), "running");
                let mut command = Command::new(&conda);
                command.args(["create", "--quiet", "--yes", "-p"]).arg(&managed).arg(format!("python={PYTHON_SPEC}"));
                run_logged(command, &directory, "创建 conda 环境", Duration::from_secs(600))?;
                let mut pip_check = Command::new(&python); pip_check.args(["-m", "pip", "--version"]);
                if capture(pip_check, Duration::from_secs(30)).is_none() {
                    emit(app, "conda", "conda 环境缺少 pip；正在补装…", "running");
                    let mut command = Command::new(&conda);
                    command.args(["install", "--quiet", "--yes", "-p"]).arg(&managed).arg("pip");
                    run_logged(command, &directory, "补装 pip", Duration::from_secs(300))?;
                }
            } else {
                emit(app, "winget", "未找到 conda；正在检测 winget…", "running");
                match find_winget() {
                    Some(winget) => {
                        emit(app, "winget", &format!("使用 winget 安装 Python {PYTHON_SPEC}（需要联网，可能需要几分钟）…"), "running");
                        let mut command = Command::new(&winget);
                        command.args(["install", "--exact", "--id", WINGET_PACKAGE, "--scope", "user", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]);
                        run_logged(command, &directory, "安装 Python（winget）", Duration::from_secs(900))?;
                        let located = locate_installed_python().ok_or("winget 安装完成后未定位到 python.exe；请在界面中手动选择解释器")?;
                        from_base = Some(located);
                    }
                    None => { emit(app, "no-toolchain", "本机没有可用的 conda 或 winget；请在手动安装 Python 后于界面中选择解释器。", "waiting"); return Ok(Outcome::WaitingManual) }
                }
            }
        }
    }
    if let Some(base) = from_base {
        emit(app, "venv", &format!("正在从 {} 创建托管虚拟环境…", base.display()), "running");
        let mut command = Command::new(&base); command.arg("-m").arg("venv").arg(&managed);
        run_logged(command, &directory, "创建虚拟环境", Duration::from_secs(300))?;
    }
    emit(app, "pip", "正在按已验证版本安装后端依赖（首次安装需要几分钟，请保持网络可用）…", "running");
    let mut command = Command::new(&python);
    command.args(["-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-r"]).arg(&requirements);
    run_logged(command, &directory, "安装依赖", Duration::from_secs(1200))?;
    emit(app, "verify", "正在验证后端依赖导入…", "running");
    probe_imports(&python)?;
    emit(app, "done", "托管 Python 环境已就绪。", "done");
    Ok(Outcome::Done)
}

fn start(state: tauri::State<'_, BootstrapState>, source: Option<PathBuf>, window: &tauri::Window) -> Result<(), String> {
    if window.label() != "main" { return Err("仅主窗口可配置环境".into()) }
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    if guard.running { return Err("环境配置已在进行中".into()) }
    guard.running = true; guard.last = None;
    let app = window.app_handle().clone();
    thread::spawn(move || {
        let result = bootstrap_flow(&app, source);
        if let Err(error) = &result { emit(&app, "failed", error, "failed") }
        if let Ok(mut guard) = app.state::<BootstrapState>().lock() { guard.running = false }
    });
    Ok(())
}

#[tauri::command]
pub fn bootstrap_python(window: tauri::Window, state: tauri::State<'_, BootstrapState>) -> Result<(), String> {
    start(state, None, &window)
}

#[tauri::command]
pub fn use_python_for_env(window: tauri::Window, state: tauri::State<'_, BootstrapState>, python_path: String) -> Result<(), String> {
    let path = PathBuf::from(python_path.trim());
    if !path.is_file() { return Err(format!("所选 Python 解释器不存在：{python_path}")) }
    start(state, Some(path), &window)
}

#[tauri::command]
pub fn env_status(window: tauri::Window, state: tauri::State<'_, BootstrapState>) -> Result<Option<EnvProgress>, String> {
    if window.label() != "main" { return Err("仅主窗口可读取环境状态".into()) }
    let guard = state.lock().map_err(|e| e.to_string())?;
    Ok(guard.last.clone())
}
