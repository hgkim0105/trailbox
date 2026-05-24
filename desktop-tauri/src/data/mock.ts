export type WindowInfo = {
  hwnd: number;
  label: string;
  exe: string;
  exe_path?: string;
  title?: string;
  pid: number;
  process_name?: string;
};

export type AdbDevice = {
  serial: string;
  label: string;
  model: string;
  online: boolean;
  sdk: number;
};

export type LocalSession = {
  session_id: string;
  started: string;
  started_rel: string;
  duration: number;
  size: number;
  log_lines: number;
  input_events: number;
  metric_samples: number;
  frames: number;
  exe: string;
  device: 'PC' | 'Android';
  uploaded: boolean;
  shares: number;
};

export type RemoteSession = {
  session_id: string;
  owner: string;
  started: string;
  duration: number;
  size: number;
  has_viewer: boolean;
};

export type UnifiedSession = {
  session_id: string;
  local: boolean;
  remote: boolean;
  started: string;
  started_rel: string;
  duration: number;
  size: number;
  exe: string;
  device: 'PC' | 'Android';
  frames: number;
  events: number;
  owner: string;
  has_viewer: boolean;
};

export type CleanupPolicy = 'keep' | 'after7d' | 'after30d' | 'when_synced';

export type HubState = {
  url: string;
  username: string;
  token: string;
  configured: boolean;
  cleanupPolicy: CleanupPolicy;
};

export const WINDOWS: WindowInfo[] = [
  { hwnd: 0x0012_0a8e, label: 'Aurora — build 412 (Aurora.exe)', exe: 'C:\\Games\\Aurora\\Aurora.exe', pid: 12340 },
  { hwnd: 0x0004_1c22, label: 'Visual Studio Code (Code.exe)', exe: 'C:\\Users\\dev\\AppData\\Local\\Programs\\VSCode\\Code.exe', pid: 9876 },
  { hwnd: 0x0009_3d10, label: 'Slack — Trailbox팀 (slack.exe)', exe: 'C:\\Users\\dev\\AppData\\Local\\slack\\slack.exe', pid: 22018 },
  { hwnd: 0x0006_4a00, label: 'Discord (Discord.exe)', exe: 'C:\\Users\\dev\\AppData\\Local\\Discord\\app-1.0\\Discord.exe', pid: 31580 },
  { hwnd: 0x0007_bc80, label: 'Chrome — Trailbox Hub (chrome.exe)', exe: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', pid: 14920 },
  { hwnd: 0x0003_d0f0, label: 'Pulse — v2.8.1 (PulseClient.exe)', exe: 'D:\\Games\\Pulse\\PulseClient.exe', pid: 5520 },
];

export const ANDROID_DEVICES: AdbDevice[] = [
  { serial: 'R5CW7022XAB', label: 'Galaxy S24 · Android 14 · One UI 6.1', model: 'SM-S921N', online: true, sdk: 34 },
  { serial: '28241FDH200J8R', label: 'Pixel 8 · Android 15 · Stock', model: 'Pixel 8', online: true, sdk: 35 },
];

export const LOCAL_SESSIONS: LocalSession[] = [
  { session_id: 'aurora_20260523_114108', started: '2026-05-23 11:41:08', started_rel: '15분 전', duration: 487.2, size: 183_500_000, log_lines: 4281, input_events: 12840, metric_samples: 487, frames: 14610, exe: 'Aurora.exe', device: 'PC', uploaded: true, shares: 2 },
  { session_id: 'chrome_20260523_104522', started: '2026-05-23 10:45:22', started_rel: '1시간 전', duration: 124.8, size: 42_100_000, log_lines: 0, input_events: 2104, metric_samples: 124, frames: 3744, exe: 'chrome.exe', device: 'PC', uploaded: true, shares: 0 },
  { session_id: 'android_R5CW_com.game', started: '2026-05-23 09:30:11', started_rel: '3시간 전', duration: 312.0, size: 98_200_000, log_lines: 1520, input_events: 4200, metric_samples: 312, frames: 9360, exe: 'com.game.app', device: 'Android', uploaded: false, shares: 0 },
  { session_id: 'pulse_20260522_201845', started: '2026-05-22 20:18:45', started_rel: '어제', duration: 1842.5, size: 520_000_000, log_lines: 18420, input_events: 55260, metric_samples: 1842, frames: 55275, exe: 'PulseClient.exe', device: 'PC', uploaded: true, shares: 1 },
  { session_id: 'aurora_20260522_143200', started: '2026-05-22 14:32:00', started_rel: '어제', duration: 965.0, size: 312_000_000, log_lines: 8400, input_events: 28950, metric_samples: 965, frames: 28950, exe: 'Aurora.exe', device: 'PC', uploaded: false, shares: 0 },
  { session_id: 'discord_20260521_091012', started: '2026-05-21 09:10:12', started_rel: '2일 전', duration: 60.0, size: 18_400_000, log_lines: 0, input_events: 840, metric_samples: 60, frames: 1800, exe: 'Discord.exe', device: 'PC', uploaded: true, shares: 0 },
];

export const REMOTE_SESSIONS: RemoteSession[] = [
  { session_id: 'aurora_20260523_100024', owner: 'mina', started: '2026-05-23 10:00:24', duration: 622.0, size: 201_000_000, has_viewer: true },
  { session_id: 'pulse_20260522_183011', owner: 'jin', started: '2026-05-22 18:30:11', duration: 1200.0, size: 380_000_000, has_viewer: true },
  { session_id: 'chrome_20260522_091500', owner: 'mina', started: '2026-05-22 09:15:00', duration: 45.0, size: 12_800_000, has_viewer: false },
];

export const HUB_INITIAL: HubState = (() => {
  try {
    const saved = localStorage.getItem('trailbox_hub');
    if (saved) return JSON.parse(saved);
  } catch {}
  return { url: 'http://127.0.0.1:8765', username: '', token: '', configured: false, cleanupPolicy: 'keep' as CleanupPolicy };
})();
