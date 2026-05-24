mod commands;

use tauri::Emitter;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let stop_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyR);

    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(commands::RecordingProcess::default())
        .setup(move |app| {
            let handle = app.handle().clone();
            app.global_shortcut().on_shortcut(stop_shortcut, move |_app, _shortcut, _event| {
                let _ = handle.emit("global-stop-recording", ());
            })?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_local_sessions,
            commands::open_viewer,
            commands::open_url,
            commands::show_overlay,
            commands::hide_overlay,
            commands::pick_file,
            commands::pick_folder,
            commands::get_output_root,
            commands::delete_session,
            commands::enumerate_windows,
            commands::pick_window_click,
            commands::find_window_for_log,
            commands::launch_exe,
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
