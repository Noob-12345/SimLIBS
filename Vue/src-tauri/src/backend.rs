use serde::{Deserialize, Serialize};
use std::{fs, io::{Read, Write, Seek, SeekFrom}, path::{Path, PathBuf}, process::{Child, Command, Stdio}, sync::{Arc, Mutex}, time::{Duration, Instant}};
use tauri::Manager;

#[derive(Clone, Serialize, Deserialize)]
pub struct Connection { pub endpoint: String, pub token: String, pub python: String }
pub struct Owned { child: Child, connection: Connection, job: isize, ready: PathBuf }
pub type Service = Arc<Mutex<Option<Owned>>>;

#[cfg(windows)]
mod win {
    use std::ffi::c_void;
    #[repr(C)] #[derive(Default)] struct Basic { process_time:i64, job_time:i64, flags:u32, min_set:usize, max_set:usize, active:u32, affinity:usize, priority:u32, scheduling:u32 }
    #[repr(C)] #[derive(Default)] struct Extended { basic:Basic, io:[u64;6], memory:[usize;4] }
    #[link(name="kernel32")] extern "system" { fn CreateJobObjectW(a:*const c_void,b:*const u16)->isize; fn SetInformationJobObject(h:isize,c:u32,i:*const c_void,s:u32)->i32; fn AssignProcessToJobObject(h:isize,p:isize)->i32; fn CloseHandle(h:isize)->i32; }
    #[link(name="bcrypt")] extern "system" { fn BCryptGenRandom(h:isize,b:*mut u8,n:u32,f:u32)->i32; }
    pub fn token()->Result<String,String> { let mut bytes=[0u8;32]; if unsafe{BCryptGenRandom(0,bytes.as_mut_ptr(),32,2)}!=0 {return Err("无法生成会话凭证".into())}; Ok(bytes.iter().map(|b|format!("{b:02x}")).collect()) }
    pub fn attach(child:&std::process::Child)->Result<isize,String> { use std::os::windows::io::AsRawHandle; unsafe { let h=CreateJobObjectW(std::ptr::null(),std::ptr::null()); if h==0{return Err(std::io::Error::last_os_error().to_string())}; let mut info=Extended::default(); info.basic.flags=0x2000; if SetInformationJobObject(h,9,&info as *const _ as *const c_void,std::mem::size_of::<Extended>() as u32)==0 || AssignProcessToJobObject(h,child.as_raw_handle() as isize)==0 {CloseHandle(h);return Err(format!("专属进程树建立失败：{}",std::io::Error::last_os_error()))}; Ok(h) } }
    pub fn close(h:isize) { if h!=0 {unsafe{CloseHandle(h);}} }
}
impl Drop for Owned {
    fn drop(&mut self) {
        // Authenticated cooperative shutdown first; Job Object reaps only this tree.
        let address=self.connection.endpoint.trim_start_matches("http://");
        if let Ok(addr)=address.parse() { if let Ok(mut stream)=std::net::TcpStream::connect_timeout(&addr,Duration::from_millis(300)) {
            let _=stream.set_write_timeout(Some(Duration::from_millis(300)));
            let _=write!(stream,"POST /api/shutdown HTTP/1.1\r\nHost: {address}\r\nX-SimLIBS-Token: {}\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}",self.connection.token);
        }}
        let deadline=Instant::now()+Duration::from_secs(5);
        while Instant::now()<deadline { if self.child.try_wait().ok().flatten().is_some(){break}; std::thread::sleep(Duration::from_millis(50)); }
        #[cfg(windows)] win::close(self.job);
        let _=self.child.kill(); let _=self.child.wait(); let _=fs::remove_file(&self.ready);
    }
}
fn state_dir(app:&tauri::AppHandle)->Result<PathBuf,String> {app.path().app_local_data_dir().map_err(|e|e.to_string())}
fn resources(app:&tauri::AppHandle)->Result<PathBuf,String> {
    let resource=app.path().resource_dir().map_err(|e|e.to_string())?.join("backend");
    if resource.join("web/server.py").is_file(){return Ok(resource)}
    #[cfg(debug_assertions)] {let dev=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../backend");if dev.join("web/server.py").is_file(){return Ok(dev)}}
    Err(format!("缺少 backend 资源：{}",resource.display()))
}
fn startup_evidence(log:&Path)->String {
    // Inspect only the bounded owned log tail. Return recognised error classes and
    // safe module identifiers, never arbitrary traceback lines or credentials.
    let mut bytes=Vec::new();
    if let Ok(mut file)=fs::File::open(log) {
        let length=file.metadata().map(|m|m.len()).unwrap_or(0);
        let _=file.seek(SeekFrom::Start(length.saturating_sub(8192)));
        let _=file.take(8192).read_to_end(&mut bytes);
    }
    for line in String::from_utf8_lossy(&bytes).lines().rev() {
        if line.starts_with("ModuleNotFoundError:") {
            let module=line.split("No module named '").nth(1).and_then(|s|s.split('\'').next()).unwrap_or("").split('.').next().unwrap_or("");
            let package=match module {"numpy"=>"numpy","pandas"=>"pandas","scipy"=>"scipy","bs4"=>"beautifulsoup4","PIL"=>"Pillow","requests"=>"requests","matplotlib"=>"matplotlib","selenium"=>"selenium","webdriver_manager"=>"webdriver-manager",_=>""};
            if !package.is_empty() {return format!("ModuleNotFoundError：缺少 {module}（安装分发名 {package}）。请在下述 Python 中手动修复该包，再重新检查。")}
            return "ModuleNotFoundError：启动模块缺失。请核对 backend 资源完整性和所选 Python 的依赖，再重新检查。".into()
        }
        if line.starts_with("ImportError:") {return if line.contains("DLL load failed") {"ImportError：依赖 DLL 加载失败。请修复所选 Python 环境中的二进制依赖后重新检查。"} else {"ImportError：Python 依赖导入失败。请修复所选解释器中的包版本或二进制依赖后重新检查。"}.into()}
        if line.starts_with("FileNotFoundError:") {return "FileNotFoundError：启动资源缺失，请恢复完整 backend 文件夹。".into()}
        if line.starts_with("SyntaxError:") {return "SyntaxError：启动代码无法由所选解释器读取，请检查 Python 版本与完整 backend 资源。".into()}
        if line.starts_with("OSError:") {return "OSError：启动资源读取或动态库加载失败，请检查环境与资源权限。".into()}
    }
    "未取得可识别的导入错误；请核对解释器和完整 backend 资源，或由维护者检查本机日志。".into()
}
fn launch(app:tauri::AppHandle,state:Service,python:Option<String>,restart:bool)->Result<Connection,String> {
    let mut guard=state.lock().map_err(|e|e.to_string())?;
    if restart {if let Some(service)=guard.as_mut(){let mut stream=std::net::TcpStream::connect(service.connection.endpoint.trim_start_matches("http://")).map_err(|e|e.to_string())?;stream.set_read_timeout(Some(Duration::from_secs(3))).map_err(|e|e.to_string())?;write!(stream,"GET /api/status HTTP/1.1\r\nHost: localhost\r\nX-SimLIBS-Token: {}\r\nConnection: close\r\n\r\n",service.connection.token).map_err(|e|e.to_string())?;let mut response=String::new();stream.read_to_string(&mut response).map_err(|e|e.to_string())?;let body=response.split("\r\n\r\n").nth(1).ok_or("状态响应错误")?;let status:serde_json::Value=serde_json::from_str(body).map_err(|e|e.to_string())?;if status["jobs_running"].as_u64().unwrap_or(1)>0{return Err("存在运行任务，请完成或取消后更改 Python".into())}} guard.take(); }
    if let Some(service)=guard.as_mut(){if service.child.try_wait().map_err(|e|e.to_string())?.is_none(){return Ok(service.connection.clone())} guard.take();}
    let resource=resources(&app)?;let directory=state_dir(&app)?;fs::create_dir_all(&directory).map_err(|e|e.to_string())?;
    let config=directory.join("owned-python.json");
    let selected=python.filter(|s|!s.trim().is_empty()).or_else(||std::env::var("SIMLIBS_UI_PYTHON").ok()).or_else(||fs::read_to_string(&config).ok().and_then(|s|serde_json::from_str::<String>(&s).ok())).unwrap_or_else(||["E:/Anaconda/envs/simLIBS/python.exe","D:/Anaconda3/envs/simLIBS/python.exe"].into_iter().find(|p|std::path::Path::new(p).is_file()).unwrap_or("python").into());
    if selected!="python" && !std::path::Path::new(&selected).is_file(){return Err(format!("Python 解释器不存在：{selected}"))}
    #[cfg(windows)] let token=win::token()?;
    #[cfg(not(windows))] let token=return Err("当前 owned 后端仅支持 Windows".into());
    let ready=directory.join(format!("ready-{}.json",&token[..16]));let log=fs::File::create(directory.join("backend.log")).map_err(|e|e.to_string())?;
    #[cfg(debug_assertions)] let output=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../outputs");
    #[cfg(not(debug_assertions))] let output=directory.join("outputs");
    let mut command=Command::new(&selected);command.args(["-B","-u"]).arg(resource.join("web/server.py")).args(["--port","0","--no-browser"]).current_dir(&resource).env("SIMLIBS_SESSION_TOKEN",&token).env("SIMLIBS_READY_FILE",&ready).env("SIMLIBS_STATE_DIR",&directory).env("SIMLIBS_OUTPUT",output).env("SIMLIBS_UI_PYTHON",&selected).stdin(Stdio::null()).stdout(log.try_clone().map_err(|e|e.to_string())?).stderr(log);
    #[cfg(windows)] {use std::os::windows::process::CommandExt;command.creation_flags(0x08000000);}
    let mut child=command.spawn().map_err(|e|format!("Python 启动失败：{selected}：{e}"))?;
    #[cfg(windows)] let job=match win::attach(&child){Ok(h)=>h,Err(e)=>{let _=child.kill();let _=child.wait();return Err(e)}};
    #[cfg(not(windows))] let job=0;
    let mut service=Owned{child,connection:Connection{endpoint:String::new(),token,python:selected.clone()},job,ready:ready.clone()};
    let deadline=Instant::now()+Duration::from_secs(25);
    loop {if let Ok(body)=fs::read_to_string(&ready){if let Ok(value)=serde_json::from_str::<serde_json::Value>(&body){if let Some(url)=value["endpoint"].as_str(){service.connection.endpoint=url.into();break}}} if service.child.try_wait().map_err(|e|e.to_string())?.is_some() || Instant::now()>deadline {return Err(format!("后端未就绪；{} Python：{}；本机日志：{}",startup_evidence(&directory.join("backend.log")),selected,directory.join("backend.log").display()))};std::thread::sleep(Duration::from_millis(80));}
    fs::write(config,serde_json::to_string(&selected).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    let result=service.connection.clone();*guard=Some(service);Ok(result)
}
#[tauri::command]
pub async fn backend_connect(app:tauri::AppHandle,window:tauri::Window,state:tauri::State<'_,Service>,python:Option<String>,restart:Option<bool>)->Result<Connection,String> {
    if window.label()!="main" {return Err("仅主窗口可连接后端".into())}
    let shared=state.inner().clone();tauri::async_runtime::spawn_blocking(move||launch(app,shared,python,restart.unwrap_or(false))).await.map_err(|e|e.to_string())?
}
pub fn shutdown(state:&Service) {if let Ok(mut guard)=state.lock(){guard.take();}}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn startup_log_evidence_is_bounded_and_never_returns_arbitrary_secrets() {
        let path=std::env::temp_dir().join(format!("simlibs-startup-evidence-{}.log",std::process::id()));
        fs::write(&path,format!("{}\nModuleNotFoundError: No module named 'bs4'\n", "secret ".repeat(3000))).unwrap();
        let result=startup_evidence(&path);assert!(result.contains("beautifulsoup4"));assert!(!result.contains("secret"));
        fs::write(&path,"ImportError: DLL load failed password=private-token").unwrap();
        let result=startup_evidence(&path);assert!(result.contains("DLL"));assert!(!result.contains("private-token"));
        fs::write(&path,"ModuleNotFoundError: No module named 'private-token'").unwrap();
        assert!(!startup_evidence(&path).contains("private-token"));
        fs::remove_file(&path).unwrap();
        assert!(startup_evidence(&path).contains("未取得"));
    }
}
