import { invoke } from '@tauri-apps/api/core';

export type SessionSummary = {
  session_id: string;
  exe_path: string | null;
  started_at: string | null;
  duration_seconds: number;
  size_bytes: number;
  screen_frames: number;
  log_lines: number;
  input_events: number;
  metric_samples: number;
  has_viewer: boolean;
  device: string;
};

export async function listLocalSessions(): Promise<SessionSummary[]> {
  return invoke<SessionSummary[]>('list_local_sessions');
}

export async function openViewer(sessionId: string): Promise<void> {
  return invoke('open_viewer', { sessionId });
}

export async function deleteSession(sessionId: string): Promise<void> {
  return invoke('delete_session', { sessionId });
}

export async function getOutputRoot(): Promise<string> {
  return invoke<string>('get_output_root');
}
