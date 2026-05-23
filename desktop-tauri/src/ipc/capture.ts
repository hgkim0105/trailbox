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
