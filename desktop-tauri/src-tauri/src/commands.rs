use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader, Write as IoWrite};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, State};

fn output_root() -> PathBuf {
    // Use project_root() which reliably finds the repo root via main.py
    let root = project_root();
    let from_root = root.join("output");
    if from_root.is_dir() {
        return from_root.canonicalize().unwrap_or(from_root);
    }
    // Fallback for production: next to the exe
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default();
    let from_exe = exe_dir.join("output");
    if from_exe.is_dir() {
        return from_exe.canonicalize().unwrap_or(from_exe);
    }
    from_root
}

#[derive(Serialize)]
pub struct SessionSummary {
    session_id: String,
    exe_path: Option<String>,
    started_at: Option<String>,
    duration_seconds: f64,
    size_bytes: u64,
    screen_frames: u64,
    log_lines: u64,
    input_events: u64,
    metric_samples: u64,
    has_viewer: bool,
    device: String,
}

#[derive(Deserialize)]
struct SessionMeta {
    session_id: Option<String>,
    exe_path: Option<String>,
    started_at: Option<String>,
    duration_seconds: Option<f64>,
    screen_frames: Option<u64>,
    log_lines: Option<u64>,
    input_events: Option<u64>,
    metric_samples: Option<u64>,
}

fn dir_size(path: &PathBuf) -> u64 {
    let mut total = 0u64;
    if let Ok(entries) = fs::read_dir(path) {
        for entry in entries.flatten() {
            let meta = entry.metadata();
            if let Ok(m) = meta {
                if m.is_file() {
                    total += m.len();
                } else if m.is_dir() {
                    total += dir_size(&entry.path());
                }
            }
        }
    }
    total
}

#[tauri::command]
pub fn list_local_sessions() -> Result<Vec<SessionSummary>, String> {
    let root = output_root();
    if !root.is_dir() {
        return Ok(vec![]);
    }

    let mut sessions = Vec::new();
    let entries = fs::read_dir(&root).map_err(|e| e.to_string())?;

    for entry in entries.flatten() {
        let dir = entry.path();
        if !dir.is_dir() {
            continue;
        }
        let name = dir.file_name().unwrap_or_default().to_string_lossy().to_string();
        if name.starts_with('_') || name.starts_with('.') {
            continue;
        }

        let meta_path = dir.join("session_meta.json");
        if !meta_path.is_file() {
            continue;
        }

        let raw = match fs::read_to_string(&meta_path) {
            Ok(s) => s,
            Err(_) => continue,
        };
        let meta: SessionMeta = match serde_json::from_str(&raw) {
            Ok(m) => m,
            Err(_) => continue,
        };

        let has_viewer = dir.join("viewer.html").is_file();
        let device = if name.starts_with("android_") {
            "Android".to_string()
        } else {
            "PC".to_string()
        };

        sessions.push(SessionSummary {
            session_id: meta.session_id.unwrap_or_else(|| name.clone()),
            exe_path: meta.exe_path,
            started_at: meta.started_at,
            duration_seconds: meta.duration_seconds.unwrap_or(0.0),
            size_bytes: dir_size(&dir),
            screen_frames: meta.screen_frames.unwrap_or(0),
            log_lines: meta.log_lines.unwrap_or(0),
            input_events: meta.input_events.unwrap_or(0),
            metric_samples: meta.metric_samples.unwrap_or(0),
            has_viewer,
            device,
        });
    }

    sessions.sort_by(|a, b| b.started_at.cmp(&a.started_at));
    Ok(sessions)
}

#[tauri::command]
pub fn get_output_root() -> String {
    output_root().to_string_lossy().to_string()
}

#[tauri::command]
pub fn open_viewer(session_id: String) -> Result<(), String> {
    let viewer = output_root().join(&session_id).join("viewer.html");
    if !viewer.is_file() {
        return Err(format!("viewer.html not found for {}", session_id));
    }
    open::that(&viewer).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn open_url(url: String) -> Result<(), String> {
    open::that(&url).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_session(session_id: String) -> Result<(), String> {
    let dir = output_root().join(&session_id);
    if !dir.is_dir() {
        return Err(format!("session directory not found: {}", session_id));
    }
    // Safety: only delete within output root
    let root = output_root();
    let canonical = dir.canonicalize().map_err(|e| e.to_string())?;
    let root_canonical = root.canonicalize().map_err(|e| e.to_string())?;
    if !canonical.starts_with(&root_canonical) {
        return Err("path traversal blocked".to_string());
    }
    fs::remove_dir_all(&dir).map_err(|e| e.to_string())
}

// ── Window picker / app launcher ───────────────────────────────────

#[tauri::command]
pub fn pick_window_click(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.minimize();
    }
    let result = call_bridge(&["pick-window-click"]);
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
    result
}

#[tauri::command]
pub fn find_window_for_log(log_dir: String) -> Result<serde_json::Value, String> {
    call_bridge(&["find-window-for-log", &log_dir])
}

#[tauri::command]
pub fn launch_exe(exe_path: String) -> Result<serde_json::Value, String> {
    call_bridge(&["launch-exe", &exe_path])
}

// ── Overlay window control ─────────────────────────────────────────

#[tauri::command]
pub fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("overlay") {
        let _ = win.set_position(tauri::PhysicalPosition::new(
            win.primary_monitor().ok().flatten()
                .map(|m| m.size().width as i32 - 280).unwrap_or(1640),
            16,
        ));
        win.show().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn sync_overlay_time(app: tauri::AppHandle, elapsed: u64) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("overlay") {
        let _ = win.eval(&format!("if(window.setElapsed)window.setElapsed({})", elapsed));
    }
    Ok(())
}

#[tauri::command]
pub fn hide_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("overlay") {
        win.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ── File picker dialogs ────────────────────────────────────────────

#[tauri::command]
pub fn pick_file() -> Result<Option<String>, String> {
    let path = rfd::FileDialog::new()
        .add_filter("Executable", &["exe"])
        .pick_file();
    Ok(path.map(|p| p.to_string_lossy().to_string()))
}

#[tauri::command]
pub fn pick_folder() -> Result<Option<String>, String> {
    let path = rfd::FileDialog::new().pick_folder();
    Ok(path.map(|p| p.to_string_lossy().to_string()))
}

// ── Python bridge helpers ──────────────────────────────────────────

fn project_root() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default();
    // Dev: src-tauri/target/debug → project root is ../../../..
    let candidates = [
        exe_dir.join("..").join("..").join("..").join(".."),
        exe_dir.join("..").join("..").join(".."),
        exe_dir.join(".."),
        PathBuf::from("."),
    ];
    for c in &candidates {
        if c.join("main.py").is_file() {
            return c.canonicalize().unwrap_or_else(|_| c.clone());
        }
    }
    PathBuf::from(".")
}

fn python_exe() -> PathBuf {
    let root = project_root();
    let venv = root.join(".venv").join("Scripts").join("python.exe");
    if venv.is_file() { return venv; }
    PathBuf::from("python")
}

fn bridge_command(extra_args: &[&str]) -> (PathBuf, Vec<String>) {
    let root = project_root();
    let exe_dir = std::env::current_exe()
        .ok().and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default();
    // Production: trailbox-bridge.exe next to the Tauri exe
    let bridge_exe = exe_dir.join("trailbox-bridge.exe");
    if bridge_exe.is_file() {
        let args: Vec<String> = extra_args.iter().map(|s| s.to_string()).collect();
        return (bridge_exe, args);
    }
    // Dev: python desktop-tauri/bridge.py
    let bridge_py = root.join("desktop-tauri").join("bridge.py");
    let mut args = vec![bridge_py.to_string_lossy().to_string()];
    args.extend(extra_args.iter().map(|s| s.to_string()));
    (python_exe(), args)
}

fn bridge_record_command() -> (PathBuf, Vec<String>) {
    let root = project_root();
    let exe_dir = std::env::current_exe()
        .ok().and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default();
    let bridge_exe = exe_dir.join("trailbox-bridge.exe");
    if bridge_exe.is_file() {
        return (bridge_exe, vec!["record".to_string()]);
    }
    let bridge_py = root.join("desktop-tauri").join("bridge_record.py");
    (python_exe(), vec![bridge_py.to_string_lossy().to_string()])
}

fn call_bridge(args: &[&str]) -> Result<serde_json::Value, String> {
    let root = project_root();
    let (cmd, cmd_args) = bridge_command(args);
    let output = Command::new(&cmd)
        .args(&cmd_args)
        .current_dir(&root)
        .output()
        .map_err(|e| format!("failed to spawn bridge: {}", e))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        return Err(format!("bridge exited {}: {} {}", output.status, stdout, stderr));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str(&stdout).map_err(|e| format!("invalid JSON from bridge: {}", e))
}

#[tauri::command]
pub fn enumerate_windows() -> Result<serde_json::Value, String> {
    call_bridge(&["enumerate-windows"])
}

#[tauri::command]
pub fn list_android_devices() -> Result<serde_json::Value, String> {
    call_bridge(&["list-devices"])
}

#[tauri::command]
pub fn get_system_info() -> Result<serde_json::Value, String> {
    call_bridge(&["system-info"])
}

#[tauri::command]
pub fn hub_healthz(url: String, token: String) -> Result<serde_json::Value, String> {
    call_bridge(&["hub-healthz", &url, &token])
}

#[tauri::command]
pub fn hub_login(url: String, username: String, password: String) -> Result<serde_json::Value, String> {
    call_bridge(&["hub-login", &url, &username, &password])
}

#[tauri::command]
pub fn hub_list_sessions(url: String, token: String) -> Result<serde_json::Value, String> {
    call_bridge(&["hub-list-sessions", &url, &token])
}

#[tauri::command]
pub fn hub_upload(url: String, token: String, session_id: String) -> Result<serde_json::Value, String> {
    call_bridge(&["hub-upload", &url, &token, &session_id])
}

#[tauri::command]
pub fn hub_share(url: String, token: String, session_id: String) -> Result<serde_json::Value, String> {
    call_bridge(&["hub-share", &url, &token, &session_id])
}

// ── Recording subprocess management ────────────────────────────────

use std::sync::Arc;

pub struct RecordingProcess {
    pub child_stdin: Mutex<Option<std::process::ChildStdin>>,
    pub child_handle: Mutex<Option<Child>>,
    pub latest_status: Arc<Mutex<Option<serde_json::Value>>>,
    pub done_result: Arc<Mutex<Option<serde_json::Value>>>,
}

impl Default for RecordingProcess {
    fn default() -> Self {
        Self {
            child_stdin: Mutex::new(None),
            child_handle: Mutex::new(None),
            latest_status: Arc::new(Mutex::new(None)),
            done_result: Arc::new(Mutex::new(None)),
        }
    }
}

#[tauri::command]
pub fn start_recording(
    config: serde_json::Value,
    state: State<RecordingProcess>,
) -> Result<String, String> {
    {
        let guard = state.child_stdin.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            return Err("recording already in progress".into());
        }
    }

    let root = project_root();
    let (cmd, cmd_args) = bridge_record_command();

    let mut child = Command::new(&cmd)
        .args(&cmd_args)
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("failed to spawn recording bridge: {}", e))?;

    let mut stdout = BufReader::new(child.stdout.take().ok_or("no stdout")?);
    let mut stdin = child.stdin.take().ok_or("no stdin")?;

    // Read "ready"
    {
        let mut line = String::new();
        stdout.read_line(&mut line).map_err(|e| e.to_string())?;
        let evt: serde_json::Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
        if evt.get("event").and_then(|v| v.as_str()) != Some("ready") {
            return Err(format!("expected 'ready', got: {}", line.trim()));
        }
    }

    // Send start command
    {
        let start_cmd = serde_json::json!({"cmd": "start", "target": config.get("target"), "exe_path": config.get("exe_path"), "log_dirs": config.get("log_dirs"), "max_fps": config.get("max_fps"), "audio": config.get("audio"), "input": config.get("input"), "metrics": config.get("metrics")});
        let line = serde_json::to_string(&start_cmd).map_err(|e| e.to_string())?;
        stdin.write_all(line.as_bytes()).map_err(|e| e.to_string())?;
        stdin.write_all(b"\n").map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())?;
    }

    // Read "started"
    let sid;
    {
        let mut line = String::new();
        stdout.read_line(&mut line).map_err(|e| e.to_string())?;
        let evt: serde_json::Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
        match evt.get("event").and_then(|v| v.as_str()) {
            Some("started") => {
                sid = evt.get("session_id").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
            }
            Some("error") => {
                let msg = evt.get("message").and_then(|v| v.as_str()).unwrap_or("unknown error");
                return Err(msg.to_string());
            }
            _ => return Err(format!("unexpected event: {}", line.trim())),
        }
    }

    // Store stdin for stop, child for wait
    *state.child_stdin.lock().map_err(|e| e.to_string())? = Some(stdin);
    *state.child_handle.lock().map_err(|e| e.to_string())? = Some(child);
    *state.latest_status.lock().map_err(|e| e.to_string())? = None;
    *state.done_result.lock().map_err(|e| e.to_string())? = None;

    // Background thread: read status lines from stdout
    let status_arc = Arc::clone(&state.latest_status);
    let done_arc = Arc::clone(&state.done_result);
    std::thread::spawn(move || {
        for line in stdout.lines() {
            let line = match line {
                Ok(l) => l,
                Err(_) => break,
            };
            if line.trim().is_empty() { continue; }
            let evt: serde_json::Value = match serde_json::from_str(&line) {
                Ok(v) => v,
                Err(_) => continue,
            };
            match evt.get("event").and_then(|v| v.as_str()) {
                Some("status") => {
                    if let Ok(mut s) = status_arc.lock() { *s = Some(evt); }
                }
                Some("done") => {
                    if let Ok(mut d) = done_arc.lock() { *d = Some(evt); }
                }
                Some("exit") => break,
                _ => {}
            }
        }
    });

    Ok(sid)
}

#[tauri::command]
pub fn stop_recording(state: State<RecordingProcess>) -> Result<serde_json::Value, String> {
    // Send stop command via stdin
    {
        let mut guard = state.child_stdin.lock().map_err(|e| e.to_string())?;
        let stdin = guard.as_mut().ok_or("no recording in progress")?;
        stdin.write_all(b"{\"cmd\":\"stop\"}\n").map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())?;
    }

    // Wait for the background reader to populate done_result
    let done_arc = Arc::clone(&state.done_result);
    for _ in 0..300 { // up to 30 seconds
        std::thread::sleep(std::time::Duration::from_millis(100));
        if let Ok(d) = done_arc.lock() {
            if d.is_some() { break; }
        }
    }

    // Collect result
    let result = state.done_result.lock().map_err(|e| e.to_string())?
        .take().unwrap_or(serde_json::Value::Null);

    // Clean up
    if let Ok(mut child) = state.child_handle.lock() {
        if let Some(mut c) = child.take() { let _ = c.wait(); }
    }
    *state.child_stdin.lock().map_err(|e| e.to_string())? = None;
    *state.latest_status.lock().map_err(|e| e.to_string())? = None;

    Ok(result)
}

#[tauri::command]
pub fn read_recording_status(state: State<RecordingProcess>) -> Result<Option<serde_json::Value>, String> {
    let guard = state.child_stdin.lock().map_err(|e| e.to_string())?;
    if guard.is_none() { return Ok(None); }
    let status = state.latest_status.lock().map_err(|e| e.to_string())?;
    Ok(status.clone())
}
