// ============================================================
// Mock data for Trailbox Desktop UI
// ============================================================

// Windows enumerated by core.window_picker
const DESKTOP_WINDOWS = [
  { hwnd: 0x1102a, label: 'Aurora — build 412 (Aurora.exe)', exe: 'C:\\Games\\Aurora\\Aurora.exe', pid: 18432 },
  { hwnd: 0x21804, label: 'Visual Studio Code — trailbox', exe: 'C:\\Users\\hyun\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe', pid: 9112 },
  { hwnd: 0x22119, label: 'Slack — Trailbox Team', exe: 'C:\\Users\\hyun\\AppData\\Local\\slack\\slack.exe', pid: 11220 },
  { hwnd: 0x4581b, label: 'Discord', exe: 'C:\\Users\\hyun\\AppData\\Local\\Discord\\Discord.exe', pid: 14110 },
  { hwnd: 0x12244, label: 'Chrome — Trailbox Hub · 세션', exe: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', pid: 5210 },
  { hwnd: 0x18821, label: 'Pulse (Pulse.exe)', exe: 'C:\\Program Files\\Steam\\steamapps\\common\\Pulse\\Pulse.exe', pid: 22107 },
];

// adb devices
const DESKTOP_ANDROID = [
  { serial: 'R5CW7022XAB', label: 'Galaxy S24 · Android 14 · One UI 6.1', model: 'Galaxy S24', online: true, sdk: 34 },
  { serial: '8B312FX0H2', label: 'Pixel 8 · Android 14', model: 'Pixel 8', online: true, sdk: 34 },
];

// Local sessions (in output/)
const DESKTOP_SESSIONS = [
  {
    session_id: '20260523-114108-7af3',
    started: '2026-05-23 11:41:08',
    started_rel: '15분 전',
    duration: 612.4,
    size: 247_834_112,
    log_lines: 8421,
    input_events: 1947,
    metric_samples: 612,
    frames: 7349,
    exe: 'Aurora.exe',
    device: 'PC',
    uploaded: true,
    shares: 1,
  },
  {
    session_id: '20260523-091804-92ee',
    started: '2026-05-23 09:18:04',
    started_rel: '2시간 전',
    duration: 1834.2,
    size: 612_201_344,
    log_lines: 21503,
    input_events: 4128,
    metric_samples: 1834,
    frames: 22010,
    exe: 'com.acme.shopper',
    device: 'Android',
    uploaded: true,
    shares: 0,
  },
  {
    session_id: '20260522-220011-c2f1',
    started: '2026-05-22 22:00:11',
    started_rel: '어제',
    duration: 4218.8,
    size: 1_847_205_888,
    log_lines: 58213,
    input_events: 9210,
    metric_samples: 4218,
    frames: 50620,
    exe: 'claude.exe',
    device: 'PC',
    uploaded: false,
    shares: 0,
  },
  {
    session_id: '20260522-141822-91aa',
    started: '2026-05-22 14:18:22',
    started_rel: '어제',
    duration: 942.1,
    size: 312_877_056,
    log_lines: 12842,
    input_events: 2188,
    metric_samples: 942,
    frames: 11304,
    exe: 'com.acme.shopper',
    device: 'Android',
    uploaded: false,
    shares: 0,
  },
  {
    session_id: '20260522-094501-3b1c',
    started: '2026-05-22 09:45:01',
    started_rel: '어제',
    duration: 285.6,
    size: 84_226_048,
    log_lines: 1832,
    input_events: 412,
    metric_samples: 285,
    frames: 3424,
    exe: 'Pulse.exe',
    device: 'PC',
    uploaded: true,
    shares: 2,
  },
  {
    session_id: '20260521-080110-d2f4',
    started: '2026-05-21 08:01:10',
    started_rel: '2일 전',
    duration: 728.3,
    size: 218_103_808,
    log_lines: 9821,
    input_events: 1832,
    metric_samples: 728,
    frames: 8740,
    exe: 'idea64.exe',
    device: 'PC',
    uploaded: true,
    shares: 0,
  },
];

const DESKTOP_REMOTE_SESSIONS = [
  {
    session_id: '20260523-100024-mina',
    owner: 'mina',
    started: '2026-05-23 10:00:24',
    duration: 1102.0,
    size: 384_532_416,
    has_viewer: true,
  },
  {
    session_id: '20260523-082201-jihoon',
    owner: 'jihoon',
    started: '2026-05-23 08:22:01',
    duration: 542.8,
    size: 188_842_752,
    has_viewer: true,
  },
  {
    session_id: '20260522-181200-mina',
    owner: 'mina',
    started: '2026-05-22 18:12:00',
    duration: 2412.5,
    size: 824_180_736,
    has_viewer: true,
  },
];

const HUB_STATE = {
  url: 'http://hub.team:8765',
  username: 'hyun',
  configured: true,
  pending_share: null,
};

window.TrailboxDesktopData = {
  DESKTOP_WINDOWS, DESKTOP_ANDROID,
  DESKTOP_SESSIONS, DESKTOP_REMOTE_SESSIONS,
  HUB_STATE,
};
