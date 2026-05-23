mod commands;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(commands::RecordingProcess::default())
        .invoke_handler(tauri::generate_handler![
            commands::list_local_sessions,
            commands::open_viewer,
            commands::open_url,
            commands::get_output_root,
            commands::delete_session,
            commands::enumerate_windows,
            commands::list_android_devices,
            commands::get_system_info,
            commands::start_recording,
            commands::stop_recording,
            commands::read_recording_status,
            commands::hub_healthz,
            commands::hub_login,
            commands::hub_list_sessions,
            commands::hub_upload,
            commands::hub_share,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
