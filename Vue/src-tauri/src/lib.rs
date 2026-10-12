// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
fn default_output_directory(window: tauri::Window) -> Result<String, String> {
    if window.label() != "main" {
        return Err("仅主窗口可获取默认输出目录".into());
    }
    let project = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("无法解析项目输出目录")?;
    let output = project.join("outputs");
    std::fs::create_dir_all(&output).map_err(|error| format!("默认输出目录创建失败：{error}"))?;
    Ok(output.to_string_lossy().replace('\\', "/"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![greet, default_output_directory])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
