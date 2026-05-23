// Trailbox Desktop — Tauri 2 shell.
//
// Today this is intentionally minimal: spin up the main window, register
// no IPC commands yet. Subsequent commits will land tauri::command
// handlers that talk to the existing Python backend (subprocess for v1,
// native Rust ports later).

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
