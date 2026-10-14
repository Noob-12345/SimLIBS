mod backend;
use tauri::Manager;
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
fn default_output_directory(window: tauri::Window) -> Result<String, String> {
    if window.label() != "main" {
        return Err("仅主窗口可获取默认输出目录".into());
    }
    #[cfg(debug_assertions)]
    let project = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("无法解析项目输出目录")?;
    #[cfg(debug_assertions)]
    let output = project.join("outputs");
    #[cfg(not(debug_assertions))]
    let output = window.app_handle().path().app_local_data_dir().map_err(|e| e.to_string())?.join("outputs");
    std::fs::create_dir_all(&output).map_err(|error| format!("默认输出目录创建失败：{error}"))?;
    Ok(output.to_string_lossy().replace('\\', "/"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(backend::Service::default())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![greet, default_output_directory, backend::backend_connect])
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {if matches!(event, tauri::RunEvent::Exit) {backend::shutdown(app.state::<backend::Service>().inner());}});
}
