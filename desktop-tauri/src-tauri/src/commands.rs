use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::process::Command;

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

fn call_bridge(subcommand: &str) -> Result<serde_json::Value, String> {
    let root = project_root();
    let bridge = root.join("desktop-tauri").join("bridge.py");
    if !bridge.is_file() {
        return Err(format!("bridge.py not found at {}", bridge.display()));
    }
    let output = Command::new(python_exe())
        .arg(&bridge)
        .arg(subcommand)
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
    call_bridge("enumerate-windows")
}

#[tauri::command]
pub fn list_android_devices() -> Result<serde_json::Value, String> {
    call_bridge("list-devices")
}

#[tauri::command]
pub fn get_system_info() -> Result<serde_json::Value, String> {
    call_bridge("system-info")
}
