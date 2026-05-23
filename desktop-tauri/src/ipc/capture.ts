import { invoke } from '@tauri-apps/api/core';

export type WindowInfo = {
  hwnd: number;
  title: string;
  pid: number;
  process_name: string;
  exe_path: string;
  label: string;
};

export type AdbDevice = {
  serial: string;
  state: string;
  model: string;
  online: boolean;
  label: string;
};

export async function enumerateWindows(): Promise<WindowInfo[]> {
  return invoke<WindowInfo[]>('enumerate_windows');
}

export async function listAndroidDevices(): Promise<AdbDevice[]> {
  return invoke<AdbDevice[]>('list_android_devices');
}

export async function getSystemInfo(): Promise<Record<string, unknown>> {
  return invoke<Record<string, unknown>>('get_system_info');
}

export type RecordingConfig = {
  target: { kind: 'window'; hwnd: number; title: string } | { kind: 'monitor'; index: number };
  exe_path?: string;
  log_dirs?: string[];
  max_fps?: number;
  audio?: boolean;
  input?: boolean;
  metrics?: boolean;
};

export type RecordingResult = {
  event: string;
  session_id?: string;
  duration?: number;
  frames?: number;
  log_lines?: number;
  input_events?: number;
};

export async function startRecording(config: RecordingConfig): Promise<string> {
  return invoke<string>('start_recording', { config });
}

export async function stopRecording(): Promise<RecordingResult> {
  return invoke<RecordingResult>('stop_recording');
}

export async function readRecordingStatus(): Promise<Record<string, unknown> | null> {
  return invoke<Record<string, unknown> | null>('read_recording_status');
}
