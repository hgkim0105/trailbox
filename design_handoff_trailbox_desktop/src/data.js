// ============================================================
// Mock data for Trailbox Hub prototype
// ============================================================

// Procedural pseudo-randomness so thumbnails/charts stay stable
function seedRand(seed) {
  let s = seed;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

function makeSparkline(seed, points = 40, range = [10, 90]) {
  const rand = seedRand(seed);
  const arr = [];
  let v = (range[0] + range[1]) / 2;
  for (let i = 0; i < points; i++) {
    v += (rand() - 0.5) * (range[1] - range[0]) * 0.18;
    v = Math.max(range[0], Math.min(range[1], v));
    arr.push(v);
  }
  return arr;
}

const CURRENT_USER = {
  id: 4,
  username: 'hyun',
  email: 'hyun@example.com',
  role: 'admin',
  status: 'active',
};

const SESSIONS = [
  {
    session_id: '20260520-184522-7af3',
    started_at: '2026-05-22 11:14:08',
    started_relative: '2시간 전',
    duration_seconds: 612.4,
    size_bytes: 247_834_112,
    log_lines: 8421,
    input_events: 1947,
    metric_samples: 612,
    exe_path: 'C:\\Games\\Aurora\\Aurora.exe',
    device: 'PC',
    device_label: 'Windows 11 · RTX 4070',
    owner: 'hyun',
    has_viewer: true,
    shares: [{ token: 'q9d2k8s1pa', created_at: '2026-05-22 11:30' }],
    tags: ['QA', 'aurora-build-412'],
    thumb_seed: 7,
    thumb_kind: 'game',
  },
  {
    session_id: '20260520-152217-92ee',
    started_at: '2026-05-22 09:48:01',
    started_relative: '3시간 전',
    duration_seconds: 1834.2,
    size_bytes: 612_201_344,
    log_lines: 21503,
    input_events: 4128,
    metric_samples: 1834,
    exe_path: 'com.acme.shopper',
    device: 'Android',
    device_label: 'Pixel 8 · Android 14',
    owner: 'mina',
    has_viewer: true,
    shares: [],
    tags: ['mobile-qa'],
    thumb_seed: 12,
    thumb_kind: 'mobile',
  },
  {
    session_id: '20260520-094501-3b1c',
    started_at: '2026-05-22 08:12:33',
    started_relative: '5시간 전',
    duration_seconds: 285.6,
    size_bytes: 84_226_048,
    log_lines: 1832,
    input_events: 412,
    metric_samples: 285,
    exe_path: 'C:\\Program Files\\Steam\\steamapps\\common\\Pulse\\Pulse.exe',
    device: 'PC',
    device_label: 'Windows 10 · GTX 1660',
    owner: 'hyun',
    has_viewer: true,
    shares: [
      { token: 'aax8slk2k1', created_at: '2026-05-22 08:30' },
      { token: 'kvb02fk2lc', created_at: '2026-05-22 09:10' },
    ],
    tags: ['repro', 'crash-2026-1142'],
    thumb_seed: 3,
    thumb_kind: 'game',
  },
  {
    session_id: '20260519-221008-d2f4',
    started_at: '2026-05-21 22:10:08',
    started_relative: '어제',
    duration_seconds: 4218.8,
    size_bytes: 1_847_205_888,
    log_lines: 58213,
    input_events: 9210,
    metric_samples: 4218,
    exe_path: 'C:\\AI\\claude-code\\bin\\claude.exe',
    device: 'PC',
    device_label: 'Windows 11 · RTX 4090',
    owner: 'hyun',
    has_viewer: true,
    shares: [],
    tags: ['session-replay', 'ai-coding'],
    thumb_seed: 21,
    thumb_kind: 'code',
  },
  {
    session_id: '20260519-141822-91aa',
    started_at: '2026-05-21 14:18:22',
    started_relative: '어제',
    duration_seconds: 942.1,
    size_bytes: 312_877_056,
    log_lines: 12842,
    input_events: 2188,
    metric_samples: 942,
    exe_path: 'com.acme.shopper',
    device: 'Android',
    device_label: 'Galaxy S24 · Android 14',
    owner: 'jihoon',
    has_viewer: true,
    shares: [{ token: 'd9d2lk22aa', created_at: '2026-05-21 14:40' }],
    tags: ['mobile-qa', 'checkout-flow'],
    thumb_seed: 5,
    thumb_kind: 'mobile',
  },
  {
    session_id: '20260519-082210-44b1',
    started_at: '2026-05-21 08:22:10',
    started_relative: '어제',
    duration_seconds: 188.0,
    size_bytes: 52_428_800,
    log_lines: 1102,
    input_events: 287,
    metric_samples: 188,
    exe_path: 'C:\\Program Files\\JetBrains\\IntelliJ\\bin\\idea64.exe',
    device: 'PC',
    device_label: 'Windows 11 · M3 Max',
    owner: 'soyoung',
    has_viewer: true,
    shares: [],
    tags: ['debug', 'pair-review'],
    thumb_seed: 17,
    thumb_kind: 'code',
  },
  {
    session_id: '20260518-203012-bb22',
    started_at: '2026-05-20 20:30:12',
    started_relative: '2일 전',
    duration_seconds: 2210.5,
    size_bytes: 824_180_736,
    log_lines: 32100,
    input_events: 5421,
    metric_samples: 2210,
    exe_path: 'C:\\Games\\Aurora\\Aurora.exe',
    device: 'PC',
    device_label: 'Windows 11 · RTX 4080',
    owner: 'mina',
    has_viewer: true,
    shares: [],
    tags: ['QA', 'aurora-build-411', 'fps-drop'],
    thumb_seed: 30,
    thumb_kind: 'game',
  },
  {
    session_id: '20260518-110042-c9d8',
    started_at: '2026-05-20 11:00:42',
    started_relative: '2일 전',
    duration_seconds: 728.3,
    size_bytes: 218_103_808,
    log_lines: 9821,
    input_events: 1832,
    metric_samples: 728,
    exe_path: 'com.acme.banking',
    device: 'Android',
    device_label: 'Pixel 7 · Android 14',
    owner: 'jihoon',
    has_viewer: true,
    shares: [{ token: 'b3k29slx1c', created_at: '2026-05-20 11:30' }],
    tags: ['mobile-qa', 'flag-secure'],
    thumb_seed: 9,
    thumb_kind: 'mobile',
  },
];

const USERS = [
  { id: 1, username: 'admin', email: 'admin@example.com', role: 'admin', status: 'active', created_at: '2025-12-01', approved_at: '2025-12-01' },
  { id: 2, username: 'mina', email: 'mina@example.com', role: 'user', status: 'active', created_at: '2026-01-12', approved_at: '2026-01-12' },
  { id: 3, username: 'jihoon', email: 'jihoon@example.com', role: 'user', status: 'active', created_at: '2026-02-03', approved_at: '2026-02-03' },
  { id: 4, username: 'hyun', email: 'hyun@example.com', role: 'admin', status: 'active', created_at: '2026-02-18', approved_at: '2026-02-19' },
  { id: 5, username: 'soyoung', email: 'soyoung@example.com', role: 'user', status: 'active', created_at: '2026-03-20', approved_at: '2026-03-20' },
  { id: 6, username: 'taeho', email: 'taeho@example.com', role: 'user', status: 'disabled', created_at: '2026-03-22', approved_at: '2026-03-22' },
];

const PENDING_USERS = [
  { id: 11, username: 'minji', email: 'minji@example.com', created_at: '오늘 09:42' },
  { id: 12, username: 'jaewon', email: null, created_at: '오늘 11:05' },
];

const TOKENS = [
  { id: 71, label: 'laptop-qa1', created_at: '2026-05-12 14:30', last_used: '12분 전', revoked_at: null },
  { id: 64, label: 'desktop-home', created_at: '2026-04-02 09:11', last_used: '2일 전', revoked_at: null },
  { id: 41, label: 'claude-mcp', created_at: '2026-03-15 22:00', last_used: '1주일 전', revoked_at: null },
  { id: 22, label: '(no label)', created_at: '2026-02-18 08:00', last_used: '2026-04-22', revoked_at: '2026-04-30' },
];

const AUDIT_ENTRIES = [
  { ts: '2026-05-22 13:42:11', actor: 'hyun', action: 'session.share.create', target: '20260520-184522-7af3', detail: 'token=q9d2…pa' },
  { ts: '2026-05-22 13:30:08', actor: 'hyun', action: 'session.upload',       target: '20260520-184522-7af3', detail: '247 MB · chunked' },
  { ts: '2026-05-22 12:14:55', actor: 'mina', action: 'session.upload',       target: '20260520-152217-92ee', detail: '612 MB · chunked' },
  { ts: '2026-05-22 11:48:22', actor: 'admin', action: 'user.approve',         target: 'soyoung',                detail: '' },
  { ts: '2026-05-22 11:30:00', actor: 'system', action: 'retention.purge',    target: '4 sessions',            detail: 'older than 30d' },
  { ts: '2026-05-22 10:12:01', actor: 'hyun', action: 'token.issue',          target: 'laptop-qa1',             detail: 'user.id=4' },
  { ts: '2026-05-22 09:18:44', actor: 'jihoon', action: 'session.share.revoke', target: '20260519-141822-91aa', detail: 'token=d9d2…aa' },
  { ts: '2026-05-22 08:30:00', actor: 'admin', action: 'settings.update',     target: 'auto_approve_registration', detail: '0 → 1' },
  { ts: '2026-05-21 22:00:11', actor: 'hyun', action: 'session.delete',       target: '20260519-040112-aa11', detail: '' },
  { ts: '2026-05-21 20:14:33', actor: 'taeho', action: 'auth.login.fail',     target: 'username=taeho',         detail: 'bad_password' },
  { ts: '2026-05-21 20:14:31', actor: 'taeho', action: 'auth.login.fail',     target: 'username=taeho',         detail: 'bad_password' },
  { ts: '2026-05-21 20:14:28', actor: 'taeho', action: 'auth.login.fail',     target: 'username=taeho',         detail: 'bad_password' },
  { ts: '2026-05-21 18:00:00', actor: 'admin', action: 'user.disable',        target: 'taeho',                  detail: 'lockout-policy' },
];

// Event timeline for session detail
const SAMPLE_EVENTS = [
  { t: 0.4,   kind: 'log',   msg: '[Aurora] Engine initialized · build 412' },
  { t: 1.2,   kind: 'log',   msg: '[Aurora] Loading scene: main_menu' },
  { t: 2.8,   kind: 'input', msg: 'click @ (924, 412) — "Start"' },
  { t: 4.1,   kind: 'log',   msg: '[Aurora] Loading scene: level_07' },
  { t: 6.5,   kind: 'log',   msg: '[Aurora] Streaming assets: 142 mb' },
  { t: 12.7,  kind: 'input', msg: 'key down: W' },
  { t: 14.3,  kind: 'input', msg: 'key down: Shift' },
  { t: 18.4,  kind: 'warn',  msg: '[render] Allocator pressure 82% — paged tier' },
  { t: 22.1,  kind: 'input', msg: 'mouse move (812, 304) → (240, 510)' },
  { t: 28.9,  kind: 'log',   msg: '[net] Heartbeat 32 ms · 14/14 lobby slots' },
  { t: 34.5,  kind: 'error', msg: '[gpu] device hung 1× — recovered, frame skipped' },
  { t: 38.2,  kind: 'input', msg: 'click @ (1140, 220) — "Inventory"' },
  { t: 42.0,  kind: 'log',   msg: '[Aurora] Quest accept: tutorial_03' },
  { t: 48.7,  kind: 'warn',  msg: '[audio] WASAPI loopback underflow · 12 ms' },
  { t: 55.3,  kind: 'input', msg: 'key down: Tab' },
  { t: 62.8,  kind: 'log',   msg: '[net] Player joined: alyc (rtt 28ms)' },
  { t: 71.4,  kind: 'log',   msg: '[Aurora] Autosave checkpoint 1' },
  { t: 79.9,  kind: 'input', msg: 'wheel +3 ticks' },
  { t: 88.6,  kind: 'error', msg: '[script] NaN in damage calc — clamped to 0' },
  { t: 92.1,  kind: 'log',   msg: '[Aurora] Combat begin: pack_alpha_03' },
];

// System spec for session detail
const SAMPLE_SYSTEM = {
  os: 'Windows 11 Pro · 23H2 · 22631.3737',
  cpu: 'AMD Ryzen 9 7950X (16C/32T) · 4.5GHz',
  ram: '64 GB DDR5-6000',
  gpu: 'NVIDIA GeForce RTX 4070 · driver 555.99',
  vram: '12 GB',
  display: '3840×2160 @ 144Hz · 27"',
  python: '3.11.7',
  trailbox: 'v0.4.2',
};

const HUB_SETTINGS = {
  auto_approve_registration: false,
  upload_chunk_mb: 8,
  retention_days: 30,
  max_session_mb: 4096,
  require_strong_password: true,
  allow_public_share: true,
  share_expiry_days: 14,
};

window.TrailboxData = {
  CURRENT_USER, SESSIONS, USERS, PENDING_USERS, TOKENS,
  AUDIT_ENTRIES, SAMPLE_EVENTS, SAMPLE_SYSTEM, HUB_SETTINGS,
  makeSparkline, seedRand,
};
