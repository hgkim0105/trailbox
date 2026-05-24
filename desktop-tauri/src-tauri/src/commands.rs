use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader, Write as IoWrite};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, State};

fn output_root() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

    // Dev: project root's output/
    // Prod: next to the .exe
    let candidates = [
        exe_dir.join("output"),
        exe_dir.join("..").join("..").join("..").join("output"), // dev: src-tauri/target/debug -> project root
        PathBuf::from("output"),
    ];
    for c in &candidates {
        if c.is_dir() {
            return c.canonicalize().unwrap_or_else(|_| c.clone());
        }
    }
    candidates[0].clone()
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
        // Position at top-right of primary monitor
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

fn call_bridge(args: &[&str]) -> Result<serde_json::Value, String> {
    let root = project_root();
    let bridge = root.join("desktop-tauri").join("bridge.py");
    if !bridge.is_file() {
        return Err(format!("bridge.py not found at {}", bridge.display()));
    }
    let output = Command::new(python_exe())
        .arg(&bridge)
        .args(args)
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

pub struct RecordingProcess {
    pub child: Mutex<Option<Child>>,
}

impl Default for RecordingProcess {
    fn default() -> Self {
        Self { child: Mutex::new(None) }
    }
}

#[tauri::command]
pub fn start_recording(
    config: serde_json::Value,
    state: State<RecordingProcess>,
) -> Result<String, String> {
    let mut guard = state.child.lock().map_err(|e| e.to_string())?;
    if guard.is_some() {
        return Err("recording already in progress".into());
    }

    let root = project_root();
    let bridge = root.join("desktop-tauri").join("bridge_record.py");
    if !bridge.is_file() {
        return Err(format!("bridge_record.py not found at {}", bridge.display()));
    }

    let mut child = Command::new(python_exe())
        .arg(&bridge)
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("failed to spawn recording bridge: {}", e))?;

    // Read the "ready" event
    {
        let stdout = child.stdout.as_mut().ok_or("no stdout")?;
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader.read_line(&mut line).map_err(|e| e.to_string())?;
        let evt: serde_json::Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
        if evt.get("event").and_then(|v| v.as_str()) != Some("ready") {
            return Err(format!("expected 'ready', got: {}", line.trim()));
        }
    }

    // Send start command
    {
        let stdin = child.stdin.as_mut().ok_or("no stdin")?;
        let start_cmd = serde_json::json!({"cmd": "start", "target": config.get("target"), "exe_path": config.get("exe_path"), "log_dirs": config.get("log_dirs"), "max_fps": config.get("max_fps"), "audio": config.get("audio"), "input": config.get("input"), "metrics": config.get("metrics")});
        let line = serde_json::to_string(&start_cmd).map_err(|e| e.to_string())?;
        stdin.write_all(line.as_bytes()).map_err(|e| e.to_string())?;
        stdin.write_all(b"\n").map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())?;
    }

    // Read the "started" event
    {
        let stdout = child.stdout.as_mut().ok_or("no stdout")?;
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader.read_line(&mut line).map_err(|e| e.to_string())?;
        let evt: serde_json::Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
        match evt.get("event").and_then(|v| v.as_str()) {
            Some("started") => {
                let sid = evt.get("session_id").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
                *guard = Some(child);
                return Ok(sid);
            }
            Some("error") => {
                let msg = evt.get("message").and_then(|v| v.as_str()).unwrap_or("unknown error");
                return Err(msg.to_string());
            }
            _ => return Err(format!("unexpected event: {}", line.trim())),
        }
    }
}

#[tauri::command]
pub fn stop_recording(state: State<RecordingProcess>) -> Result<serde_json::Value, String> {
    let mut guard = state.child.lock().map_err(|e| e.to_string())?;
    let mut child = guard.take().ok_or("no recording in progress")?;

    // Send stop command
    {
        let stdin = child.stdin.as_mut().ok_or("no stdin")?;
        stdin.write_all(b"{\"cmd\":\"stop\"}\n").map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())?;
    }

    // Read events until "done" or "exit"
    let stdout = child.stdout.take().ok_or("no stdout")?;
    let reader = BufReader::new(stdout);
    let mut result = serde_json::Value::Null;
    for line in reader.lines() {
        let line = line.map_err(|e| e.to_string())?;
        if line.trim().is_empty() { continue; }
        let evt: serde_json::Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        match evt.get("event").and_then(|v| v.as_str()) {
            Some("done") => { result = evt; }
            Some("exit") => break,
            _ => {}
        }
    }

    let _ = child.wait();
    Ok(result)
}

#[tauri::command]
pub fn read_recording_status(state: State<RecordingProcess>) -> Result<Option<serde_json::Value>, String> {
    let guard = state.child.lock().map_err(|e| e.to_string())?;
    let child = match guard.as_ref() {
        Some(c) => c,
        None => return Ok(None),
    };
    // Non-blocking read of latest status from stdout
    // This is tricky with blocking stdio — for now return a simple "recording" flag
    let _ = child;
    Ok(Some(serde_json::json!({"recording": true})))
}
