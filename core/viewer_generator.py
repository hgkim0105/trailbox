"""Generate a self-contained ``viewer.html`` for a finished session.

v0.9.1+ ships the redesigned viewer (OKLCH tokens, Geist typography,
top-bar stats + 2-column main grid + metrics/events side panel) matching
``design_handoff_trailbox_desktop/Session Viewer.html``. The earlier
dark-grey layout is gone; if you ship a release that bundles this file,
new sessions get the new look. Existing sessions stay frozen with whatever
viewer.html was generated at recording-finish time — use the
``tools/regenerate_viewers.py`` helper to backfill.

The viewer still works under file:// (browsers block fetch() to local
files but inline JSON parses fine). Event / metric / frame data is
inlined as ``<script type="application/json">`` payloads; the
``<video>`` element and any ``<track>`` siblings reference relative
paths under the session dir.

Token substitution uses ``str.replace`` rather than format strings
because the embedded JS / CSS contains many ``{}`` characters that
would collide with .format(). Keep it that way.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# Classification regexes shared between the loader and a brief
# explanation when no level field is present in the log record.
_ERR_RE = re.compile(r"\b(error|fatal|exception|traceback)\b", re.IGNORECASE)
_WARN_RE = re.compile(r"\b(warn(ing)?|deprecat)\b", re.IGNORECASE)


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__SESSION_ID__ · Trailbox Viewer</title>
<script>
  // FOUC-safe theme init. Default dark to match the prototype; honor
  // localStorage('trailbox_viewer_theme') when present.
  (function () {
    try {
      var t = localStorage.getItem('trailbox_viewer_theme');
      if (t === 'light' || t === 'dark') {
        document.documentElement.setAttribute('data-theme', t);
      }
    } catch (e) {}
  })();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root, [data-theme="light"] {
    --bg: oklch(0.985 0.003 270);
    --bg-2: oklch(0.97 0.005 270);
    --surface: oklch(1 0 0);
    --surface-2: oklch(0.97 0.005 270);
    --surface-hover: oklch(0.95 0.006 270);
    --border: oklch(0.91 0.006 270);
    --border-muted: oklch(0.94 0.005 270);
    --fg: oklch(0.22 0.018 275);
    --fg-2: oklch(0.4 0.015 275);
    --muted: oklch(0.55 0.014 275);
    --subtle: oklch(0.7 0.012 275);
    --accent: oklch(0.55 0.18 282);
    --accent-soft: oklch(0.96 0.035 282);
    --success: oklch(0.55 0.14 150);
    --danger: oklch(0.55 0.19 25);
    --warning: oklch(0.7 0.16 75);
    --info: oklch(0.55 0.14 240);
    color-scheme: light;
  }
  [data-theme="dark"] {
    --bg: oklch(0.155 0.012 275);
    --bg-2: oklch(0.18 0.013 275);
    --surface: oklch(0.21 0.014 275);
    --surface-2: oklch(0.245 0.014 275);
    --surface-hover: oklch(0.27 0.015 275);
    --border: oklch(0.3 0.016 275);
    --border-muted: oklch(0.255 0.014 275);
    --fg: oklch(0.96 0.006 275);
    --fg-2: oklch(0.85 0.008 275);
    --muted: oklch(0.65 0.012 275);
    --subtle: oklch(0.5 0.012 275);
    --accent: oklch(0.7 0.17 282);
    --accent-soft: oklch(0.3 0.08 282);
    --success: oklch(0.72 0.14 150);
    --danger: oklch(0.72 0.18 25);
    --warning: oklch(0.8 0.14 75);
    --info: oklch(0.7 0.13 240);
    color-scheme: dark;
  }

  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); height: 100%; font-family: 'Geist', system-ui, sans-serif; font-size: 13px; line-height: 1.45; -webkit-font-smoothing: antialiased; }
  .mono, code, kbd { font-family: 'Geist Mono', ui-monospace, monospace; }
  button { font: inherit; cursor: pointer; }
  button:focus { outline: none; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 999px; border: 2px solid var(--bg); }
  ::-webkit-scrollbar-thumb:hover { background: var(--muted); }

  .app { display: grid; grid-template-rows: 48px 1fr; height: 100vh; }
  .top {
    display: flex; align-items: center; gap: 14px;
    padding: 0 18px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-2);
    overflow: hidden;
  }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 600; text-decoration: none; color: inherit; flex-shrink: 0; }
  .brand-mark {
    width: 22px; height: 22px; border-radius: 6px;
    background: linear-gradient(135deg, var(--accent), oklch(0.45 0.2 240));
    position: relative; flex-shrink: 0;
  }
  .brand-mark::before {
    content: '';
    position: absolute;
    inset: 5px 4px;
    background: white;
    clip-path: polygon(0 30%, 40% 30%, 40% 0, 60% 0, 60% 30%, 100% 30%, 100% 70%, 60% 70%, 60% 100%, 40% 100%, 40% 70%, 0 70%);
  }
  .session-id {
    font-family: 'Geist Mono'; font-size: 13px;
    font-weight: 600; color: var(--fg);
    padding: 4px 10px; background: var(--surface-2);
    border-radius: 6px; border: 1px solid var(--border);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    max-width: 320px;
  }
  .top-stats { display: flex; gap: 14px; font-size: 12px; color: var(--muted); flex-shrink: 0; overflow: hidden; }
  .top-stat { display: flex; flex-direction: column; line-height: 1.2; }
  .top-stat .v { font-family: 'Geist Mono'; font-size: 12.5px; font-weight: 600; color: var(--fg); font-variant-numeric: tabular-nums; }
  .top-stat .l { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--subtle); margin-top: 1px; }
  .top-right { margin-left: auto; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  @media (max-width: 980px) {
    .top-stats { display: none; }
  }

  .btn {
    display: inline-flex; align-items: center; gap: 5px; height: 28px;
    padding: 0 11px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface);
    color: var(--fg); font-size: 12.5px; font-weight: 500;
  }
  .btn:hover { background: var(--surface-hover); }
  .btn--icon { width: 28px; padding: 0; justify-content: center; }
  .btn svg { width: 13px; height: 13px; }

  .main { display: grid; grid-template-columns: minmax(0, 1fr) 420px; min-height: 0; }
  @media (max-width: 1100px) { .main { grid-template-columns: 1fr; } }

  .video-pane { display: flex; flex-direction: column; background: oklch(0.05 0.01 270); min-height: 0; }
  .video-stage {
    flex: 1; min-height: 0;
    position: relative;
    overflow: hidden;
    display: flex; align-items: center; justify-content: center;
  }
  .video-stage video {
    max-width: 100%; max-height: 100%;
    width: 100%; height: 100%;
    object-fit: contain;
    background: black;
  }
  /* Hide native subtitle overlay — we render the side panel from the
     inlined jsonl. Browsers under file:// silently fail on <track> anyway. */
  .video-stage video::cue { display: none; }

  .video-controls {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px;
    background: oklch(0.1 0.01 270);
    border-top: 1px solid oklch(0.2 0.01 270);
    flex-wrap: wrap;
  }
  .ctl-btn {
    width: 32px; height: 32px;
    display: inline-flex; align-items: center; justify-content: center;
    border: 1px solid oklch(0.25 0.01 270);
    background: transparent; color: white; border-radius: 6px;
  }
  .ctl-btn:hover { background: oklch(0.2 0.01 270); }
  .ctl-time { font-family: 'Geist Mono'; font-size: 12px; color: oklch(0.85 0.01 270); font-variant-numeric: tabular-nums; min-width: 110px; }
  .scrub {
    flex: 1; height: 24px;
    position: relative; cursor: pointer;
    display: flex; align-items: center;
    min-width: 200px;
  }
  .scrub-track { width: 100%; height: 5px; background: oklch(0.22 0.01 270); border-radius: 999px; position: relative; }
  .scrub-fill { position: absolute; left: 0; top: 0; bottom: 0; background: var(--accent); border-radius: 999px; }
  .scrub-marker { position: absolute; top: -3px; bottom: -3px; width: 2px; pointer-events: none; opacity: 0.7; }
  .scrub-handle {
    position: absolute; top: 50%;
    width: 14px; height: 14px; background: white;
    border-radius: 50%; transform: translate(-50%, -50%);
    box-shadow: 0 1px 4px oklch(0 0 0 / 0.5);
  }
  .speed {
    display: inline-flex; height: 28px; align-items: center;
    gap: 1px; padding: 2px;
    border: 1px solid oklch(0.25 0.01 270); border-radius: 6px;
  }
  .speed button {
    height: 22px; padding: 0 7px;
    background: transparent; border: 0;
    color: oklch(0.75 0.01 270); font-size: 11px; font-weight: 500;
    border-radius: 3px;
  }
  .speed button.active { background: oklch(0.25 0.01 270); color: white; }

  .side {
    display: grid;
    grid-template-rows: auto 1fr;
    border-left: 1px solid var(--border);
    background: var(--bg);
    min-height: 0;
  }
  @media (max-width: 1100px) {
    .side { border-left: 0; border-top: 1px solid var(--border); }
  }
  .metrics {
    border-bottom: 1px solid var(--border);
    background: var(--bg-2);
    padding: 4px 0;
  }
  .metrics-head { padding: 8px 14px 4px; display: flex; align-items: center; gap: 8px; }
  .metrics-head h3 {
    margin: 0; font-size: 10.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted);
  }
  .metrics-head .sample-count { margin-left: auto; font-size: 10.5px; color: var(--muted); font-family: 'Geist Mono'; }
  .metric-row {
    display: grid; grid-template-columns: 48px 1fr 78px;
    align-items: center; gap: 10px;
    padding: 5px 14px;
    font-size: 11.5px;
  }
  .metric-row__label {
    font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--muted);
  }
  .metric-row__chart { height: 28px; width: 100%; }
  .metric-row__value {
    text-align: right;
    font-family: 'Geist Mono';
    font-size: 12px; font-weight: 600;
    color: var(--fg);
    font-variant-numeric: tabular-nums;
  }
  .metric-row__value small { color: var(--muted); margin-left: 2px; font-size: 9.5px; font-weight: 400; }
  .metrics.empty .metric-row { display: none; }
  .metrics.empty::after {
    content: '메트릭 없음 — process telemetry off';
    display: block; padding: 10px 14px;
    font-size: 11.5px; color: var(--muted);
  }

  .events { min-height: 0; display: flex; flex-direction: column; }
  .tabs { display: flex; gap: 0; padding: 0 8px; border-bottom: 1px solid var(--border); background: var(--bg-2); }
  .tab {
    padding: 8px 12px; font-size: 12.5px; font-weight: 500;
    color: var(--muted); border: 0; background: transparent;
    border-bottom: 2px solid transparent; margin-bottom: -1px; cursor: pointer;
    display: inline-flex; align-items: center; gap: 5px;
  }
  .tab:hover { color: var(--fg); }
  .tab.active { color: var(--fg); border-bottom-color: var(--accent); }
  .tab .count {
    background: var(--surface-2); color: var(--muted);
    padding: 0 6px; border-radius: 999px;
    font-size: 10.5px; font-weight: 600;
    font-family: 'Geist Mono';
  }
  .tab.active .count { background: var(--accent-soft); color: var(--accent); }

  .events-toolbar {
    padding: 8px 12px;
    display: flex; align-items: center; gap: 6px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-2);
    flex-wrap: wrap;
  }
  .search-wrap { position: relative; flex: 1; min-width: 160px; }
  .search-wrap svg {
    position: absolute; left: 8px; top: 50%; transform: translateY(-50%);
    width: 12px; height: 12px; color: var(--subtle); pointer-events: none;
  }
  .events-search {
    width: 100%; height: 26px; padding: 0 10px 0 26px;
    border: 1px solid var(--border); border-radius: 5px;
    background: var(--surface); color: var(--fg);
    font-family: inherit; font-size: 12px;
  }
  .events-search:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
  .filter-btn {
    height: 26px; padding: 0 8px;
    font-size: 11.5px; font-weight: 500;
    border: 1px solid var(--border); border-radius: 5px;
    background: var(--surface); color: var(--muted);
    display: inline-flex; align-items: center; gap: 4px;
  }
  .filter-btn:hover { color: var(--fg); }
  .filter-btn.active { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
  .filter-btn .dot { width: 6px; height: 6px; border-radius: 50%; }
  .filter-btn.log .dot { background: var(--info); }
  .filter-btn.input .dot { background: var(--accent); }
  .filter-btn.warn .dot { background: var(--warning); }
  .filter-btn.error .dot { background: var(--danger); }
  .filter-btn.all .dot { background: var(--muted); }

  .events-list {
    flex: 1; overflow-y: auto;
    font-family: 'Geist Mono';
    font-size: 11.5px;
    min-height: 80px;
  }
  .event-row {
    display: grid; grid-template-columns: 60px 1fr;
    gap: 8px;
    padding: 4px 12px;
    border-bottom: 1px solid var(--border-muted);
    cursor: pointer;
    align-items: baseline;
  }
  .event-row:hover { background: var(--surface-2); }
  .event-row.active { background: var(--accent-soft); }
  .event-row__t { color: var(--muted); white-space: nowrap; font-size: 10.5px; }
  .event-row__t::before {
    content: '';
    display: inline-block;
    width: 5px; height: 5px;
    border-radius: 50%;
    margin-right: 5px;
    vertical-align: middle;
  }
  .event-row[data-kind="log"] .event-row__t::before { background: var(--info); }
  .event-row[data-kind="input"] .event-row__t::before { background: var(--accent); }
  .event-row[data-kind="warn"] .event-row__t::before { background: var(--warning); }
  .event-row[data-kind="error"] .event-row__t::before { background: var(--danger); }
  .event-row__msg {
    color: var(--fg-2);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .event-row[data-kind="error"] .event-row__msg { color: var(--danger); }
  .event-row[data-kind="warn"] .event-row__msg { color: oklch(0.7 0.14 75); }
  [data-theme="light"] .event-row[data-kind="warn"] .event-row__msg { color: oklch(0.45 0.13 75); }
  .event-row__msg .src { color: var(--accent); margin-right: 6px; }

  .events-empty {
    padding: 24px 14px; text-align: center;
    color: var(--muted); font-size: 12px;
  }

  .spec {
    padding: 10px 14px;
    border-top: 1px solid var(--border);
    background: var(--bg-2);
    font-size: 11.5px;
  }
  .spec-head {
    display: flex; align-items: center; gap: 6px;
    cursor: pointer; user-select: none;
    color: var(--fg-2); font-weight: 500;
  }
  .spec-head .chev { transition: transform 0.15s; }
  .spec[open] .spec-head .chev { transform: rotate(90deg); }
  .spec-body { display: none; margin-top: 8px; }
  .spec[open] .spec-body { display: grid; grid-template-columns: 80px 1fr; gap: 4px 12px; font-size: 11.5px; }
  .spec-body dt { color: var(--muted); }
  .spec-body dd { margin: 0; font-family: 'Geist Mono'; color: var(--fg); word-break: break-all; }
</style>
</head>
<body>
<div class="app">
  <header class="top">
    <a class="brand" href="#">
      <div class="brand-mark"></div>
      <span>Trailbox</span>
      <span style="color: var(--muted); font-weight: 500;">Viewer</span>
    </a>
    <div class="session-id" title="__SESSION_ID__">__SESSION_ID__</div>
    <div class="top-stats" id="top-stats"></div>
    <div class="top-right">
      <button class="btn btn--icon" id="theme-toggle" title="테마 전환" aria-label="테마 전환">
        <svg id="theme-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"></svg>
      </button>
    </div>
  </header>

  <div class="main">
    <div class="video-pane">
      <div class="video-stage">
        <video id="video" src="screen.mp4" preload="metadata" playsinline>
__TRACKS_HTML__
        </video>
      </div>
      <div class="video-controls">
        <button class="ctl-btn" id="prev" title="이전 이벤트 (←)">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 3.5v9"/><path d="M13 3.5v9L5.5 8z" fill="currentColor"/></svg>
        </button>
        <button class="ctl-btn" id="play" title="재생/일시정지 (space)">
          <svg viewBox="0 0 16 16" fill="currentColor" id="play-icon"><path d="M5 3.5v9l7-4.5z"/></svg>
        </button>
        <button class="ctl-btn" id="next" title="다음 이벤트 (→)">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 3.5v9"/><path d="M3 3.5v9L10.5 8z" fill="currentColor"/></svg>
        </button>
        <span class="ctl-time" id="ctl-time">00:00.0 / 00:00.0</span>
        <div class="scrub" id="scrub">
          <div class="scrub-track">
            <div class="scrub-fill" id="scrub-fill" style="width: 0%"></div>
            <div class="scrub-handle" id="scrub-handle" style="left: 0%"></div>
            <div id="scrub-markers"></div>
          </div>
        </div>
        <div class="speed" id="speed">
          <button data-rate="0.5">0.5×</button>
          <button data-rate="1" class="active">1×</button>
          <button data-rate="2">2×</button>
          <button data-rate="4">4×</button>
        </div>
      </div>
    </div>

    <aside class="side">
      <div class="metrics" id="metrics-pane">
        <div class="metrics-head">
          <h3>메트릭 · t=<span id="metric-t" class="mono">00:00.0</span></h3>
          <span class="sample-count" id="metric-sample-count"></span>
        </div>
        <div id="metrics-rows"></div>
      </div>

      <div class="events">
        <div class="tabs" id="event-tabs">
          <button class="tab active" data-tab="all">이벤트 <span class="count" id="count-all">0</span></button>
          <button class="tab" data-tab="log">로그만 <span class="count" id="count-log">0</span></button>
          <button class="tab" data-tab="input">입력만 <span class="count" id="count-input">0</span></button>
        </div>

        <div class="events-toolbar">
          <div class="search-wrap">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14"/></svg>
            <input class="events-search" id="search" placeholder="메시지·소스명 검색…" autocomplete="off">
          </div>
          <button class="filter-btn all active" data-kind="all">전체</button>
          <button class="filter-btn log" data-kind="log"><span class="dot"></span>log</button>
          <button class="filter-btn input" data-kind="input"><span class="dot"></span>in</button>
          <button class="filter-btn warn" data-kind="warn"><span class="dot"></span>warn</button>
          <button class="filter-btn error" data-kind="error"><span class="dot"></span>err</button>
        </div>

        <div class="events-list" id="events-list"></div>

        <details class="spec" id="spec">
          <summary class="spec-head" style="list-style: none;">
            <svg class="chev" width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6 3.5 10.5 8 6 12.5"/></svg>
            사양
          </summary>
          <dl class="spec-body" id="spec-body"></dl>
        </details>
      </div>
    </aside>
  </div>
</div>

<script id="events-data" type="application/json">__EVENTS_JSON__</script>
<script id="meta-data" type="application/json">__META_JSON__</script>
<script id="metrics-data" type="application/json">__METRICS_JSON__</script>
<script id="frames-data" type="application/json">__FRAMES_JSON__</script>

<script>
(function () {
  const EVENTS = JSON.parse(document.getElementById('events-data').textContent);
  const META = JSON.parse(document.getElementById('meta-data').textContent);
  const METRIC_SAMPLES = JSON.parse(document.getElementById('metrics-data').textContent);
  const FRAMES = JSON.parse(document.getElementById('frames-data').textContent);

  // ── State ─────────────────────────────────────────────────
  const video = document.getElementById('video');
  let DURATION = parseFloat(META.duration_seconds) || 0;
  const state = { t: 0, tab: 'all', filter: 'all', query: '' };

  function fmtT(t) {
    if (!isFinite(t) || t < 0) t = 0;
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    const d = Math.floor((t - Math.floor(t)) * 10);
    if (m >= 60) {
      const h = Math.floor(m / 60);
      const mm = m % 60;
      return `${String(h)}:${String(mm).padStart(2,'0')}:${String(s).padStart(2,'0')}.${d}`;
    }
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${d}`;
  }
  function fmtNum(n) {
    if (n == null) return '—';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
    return String(Math.round(n));
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  // ── Top stats (duration / frames / logs / inputs / Δ p99 / cpu cores) ──
  function renderTopStats() {
    const root = document.getElementById('top-stats');
    const logCount = EVENTS.filter(e => e.kind === 'log' || e.kind === 'warn' || e.kind === 'error').length;
    const inputCount = EVENTS.filter(e => e.kind === 'input').length;
    const sys = META.system || {};
    const fs = META.frame_stats || {};
    const p99 = fs.delta_ms_p99 != null ? `${Math.round(fs.delta_ms_p99)} ms` : (fs.p99_ms != null ? `${Math.round(fs.p99_ms)} ms` : null);
    const cores = sys.cpu_cores || sys.cpu_logical_cores;
    const stats = [
      { v: fmtT(DURATION), l: 'Duration' },
      { v: fmtNum(META.screen_frames || 0), l: 'Frames' },
      { v: fmtNum(logCount), l: 'Logs' },
      { v: fmtNum(inputCount), l: 'Inputs' },
    ];
    if (p99) stats.push({ v: p99, l: 'Δ p99' });
    if (cores) stats.push({ v: `${cores} cores`, l: 'CPU' });
    root.innerHTML = stats.map(s => `<div class="top-stat"><span class="v">${escapeHtml(s.v)}</span><span class="l">${escapeHtml(s.l)}</span></div>`).join('');
  }

  // ── Spec (system block) ─────────────────────────────────
  function renderSpec() {
    const body = document.getElementById('spec-body');
    const sys = META.system || {};
    const rows = [
      ['OS', sys.platform || sys.os],
      ['CPU', sys.cpu],
      ['RAM', sys.ram_gb ? `${sys.ram_gb} GB` : null],
      ['GPU', sys.gpu],
      ['VRAM', sys.vram_gb ? `${sys.vram_gb} GB` : null],
      ['Display', sys.display],
      ['Python', sys.python_version],
      ['Trailbox', sys.trailbox_version],
      ['EXE', META.exe_path],
    ].filter(([, v]) => v);
    body.innerHTML = rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('');
    if (!rows.length) body.innerHTML = '<dt style="grid-column: 1 / -1; color: var(--muted)">system 정보 없음</dt>';
  }

  // ── Metrics: resample real samples into uniform arrays for sparklines ──
  // METRIC_SAMPLES is the raw process.jsonl rows: [{t, cpu_pct, rss_mb, threads, gpu_pct, gpu_vram_mb, ...}, ...]
  // We build a fixed-length array per metric so the sparkline path stays smooth
  // regardless of sample density.
  const SPARK_N = 160;

  function resample(samples, field, transform) {
    if (!samples || !samples.length || !DURATION) return null;
    const out = new Array(SPARK_N);
    let si = 0;
    let last = null;
    for (let i = 0; i < SPARK_N; i++) {
      const t = (i / (SPARK_N - 1)) * DURATION;
      while (si < samples.length - 1 && samples[si + 1].t <= t) si++;
      const v = samples[si] ? samples[si][field] : null;
      if (v != null && isFinite(v)) {
        last = transform ? transform(v) : v;
      }
      out[i] = last;
    }
    // Drop the series entirely if every value is null.
    if (out.every(x => x == null)) return null;
    // Forward-fill leading nulls with the first real value, otherwise the
    // sparkline shows a hard zero at t=0.
    let firstReal = out.find(x => x != null);
    for (let i = 0; i < SPARK_N && out[i] == null; i++) out[i] = firstReal;
    return out;
  }

  function resampleFps(frames) {
    if (!frames || !frames.length || !DURATION) return null;
    const out = new Array(SPARK_N).fill(null);
    // bin frames by t window; each output bin gets median fps of frames in that window
    const bin = DURATION / SPARK_N;
    const buckets = Array.from({ length: SPARK_N }, () => []);
    for (const f of frames) {
      const idx = Math.min(SPARK_N - 1, Math.max(0, Math.floor(f.t / bin)));
      buckets[idx].push(f.fps);
    }
    let last = null;
    for (let i = 0; i < SPARK_N; i++) {
      if (buckets[i].length) {
        buckets[i].sort((a, b) => a - b);
        last = buckets[i][Math.floor(buckets[i].length / 2)];
      }
      out[i] = last;
    }
    if (out.every(x => x == null)) return null;
    let firstReal = out.find(x => x != null);
    for (let i = 0; i < SPARK_N && out[i] == null; i++) out[i] = firstReal;
    return out;
  }

  const METRIC_SERIES = [];
  function buildMetrics() {
    const cpu = resample(METRIC_SAMPLES, 'cpu_pct');
    const gpu = resample(METRIC_SAMPLES, 'gpu_pct');
    const ram = resample(METRIC_SAMPLES, 'rss_mb', mb => mb / 1024);
    const vram = resample(METRIC_SAMPLES, 'gpu_vram_mb', mb => mb / 1024);
    const fps = resampleFps(FRAMES);
    if (cpu)  METRIC_SERIES.push({ id: 'cpu',  label: 'CPU',  data: cpu,  unit: '%',  color: 'oklch(0.65 0.18 25)' });
    if (gpu)  METRIC_SERIES.push({ id: 'gpu',  label: 'GPU',  data: gpu,  unit: '%',  color: 'oklch(0.65 0.18 280)' });
    if (ram)  METRIC_SERIES.push({ id: 'ram',  label: 'RAM',  data: ram,  unit: 'GB', color: 'oklch(0.65 0.18 150)' });
    if (vram) METRIC_SERIES.push({ id: 'vram', label: 'VRAM', data: vram, unit: 'GB', color: 'oklch(0.65 0.18 60)' });
    if (fps)  METRIC_SERIES.push({ id: 'fps',  label: 'FPS',  data: fps,  unit: '',   color: 'oklch(0.65 0.18 200)' });
    document.getElementById('metric-sample-count').textContent = `${METRIC_SAMPLES.length} samples`;
    if (!METRIC_SERIES.length) document.getElementById('metrics-pane').classList.add('empty');
  }

  function renderSpark(data, color, t) {
    const w = 200, h = 28;
    let min = Infinity, max = -Infinity;
    for (const v of data) { if (v < min) min = v; if (v > max) max = v; }
    const range = (max - min) || 1;
    const pts = data.map((v, i) => [
      (i / (data.length - 1)) * w,
      h - ((v - min) / range) * (h - 4) - 2,
    ]);
    let d = '';
    pts.forEach(([x, y], i) => {
      if (i === 0) d += `M${x},${y}`;
      else {
        const [px, py] = pts[i - 1];
        const cx = px + (x - px) / 2;
        d += ` C${cx},${py} ${cx},${y} ${x},${y}`;
      }
    });
    const idx = DURATION ? Math.min(data.length - 1, Math.floor((t / DURATION) * data.length)) : 0;
    const [cx, cy] = pts[idx];
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="metric-row__chart" style="overflow: visible;">
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.3" opacity="0.85" />
      <line x1="${cx}" y1="0" x2="${cx}" y2="${h}" stroke="var(--accent)" stroke-width="1" opacity="0.5" />
      <circle cx="${cx}" cy="${cy}" r="2.4" fill="${color}" />
    </svg>`;
  }

  function renderMetrics() {
    document.getElementById('metric-t').textContent = fmtT(state.t);
    if (!METRIC_SERIES.length) return;
    const root = document.getElementById('metrics-rows');
    const idx = DURATION ? Math.min(METRIC_SERIES[0].data.length - 1, Math.floor((state.t / DURATION) * METRIC_SERIES[0].data.length)) : 0;
    root.innerHTML = METRIC_SERIES.map(m => {
      const v = m.data[idx];
      const display = m.unit === 'GB' ? v.toFixed(1) : Math.round(v);
      return `<div class="metric-row">
        <span class="metric-row__label">${m.label}</span>
        ${renderSpark(m.data, m.color, state.t)}
        <span class="metric-row__value">${display}<small>${m.unit}</small></span>
      </div>`;
    }).join('');
  }

  // ── Event counts + tabs + list ─────────────────────────
  function getKindFilter() {
    // tab acts as a coarse filter, the chip filter is the finer one
    if (state.tab === 'log') return e => (e.kind === 'log' || e.kind === 'warn' || e.kind === 'error');
    if (state.tab === 'input') return e => e.kind === 'input';
    return () => true;
  }

  function updateCounts() {
    const total = EVENTS.length;
    const logCount = EVENTS.filter(e => e.kind === 'log' || e.kind === 'warn' || e.kind === 'error').length;
    const inputCount = EVENTS.filter(e => e.kind === 'input').length;
    document.getElementById('count-all').textContent = fmtNum(total);
    document.getElementById('count-log').textContent = fmtNum(logCount);
    document.getElementById('count-input').textContent = fmtNum(inputCount);
  }

  let _filteredEvents = [];
  const MAX_VISIBLE = 500;  // window to render; active row always included

  function recomputeFiltered() {
    const tabFn = getKindFilter();
    const q = state.query.toLowerCase().trim();
    _filteredEvents = EVENTS.filter(e => {
      if (!tabFn(e)) return false;
      if (state.filter !== 'all' && e.kind !== state.filter) return false;
      if (q) {
        const hay = (e.msg + ' ' + (e.src || '')).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function findActiveIdx(arr, t) {
    let lo = 0, hi = arr.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid].t <= t) { ans = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    return ans;
  }

  function renderEvents() {
    const list = document.getElementById('events-list');
    if (!_filteredEvents.length) {
      list.innerHTML = '<div class="events-empty">일치하는 이벤트 없음</div>';
      return;
    }
    const activeIdx = findActiveIdx(_filteredEvents, state.t);
    // Window around active or top of list
    let start, end;
    if (_filteredEvents.length <= MAX_VISIBLE) {
      start = 0; end = _filteredEvents.length;
    } else {
      // Center on active (or stay at top if no active yet)
      const half = MAX_VISIBLE >> 1;
      const center = activeIdx >= 0 ? activeIdx : 0;
      start = Math.max(0, center - half);
      end = Math.min(_filteredEvents.length, start + MAX_VISIBLE);
      start = Math.max(0, end - MAX_VISIBLE);
    }
    let html = '';
    for (let i = start; i < end; i++) {
      const e = _filteredEvents[i];
      const cls = i === activeIdx ? 'event-row active' : 'event-row';
      const srcHtml = e.src ? `<span class="src">${escapeHtml(e.src)}</span>` : '';
      html += `<div class="${cls}" data-kind="${escapeHtml(e.kind)}" data-t="${e.t}">
        <span class="event-row__t">${fmtT(e.t)}</span>
        <span class="event-row__msg">${srcHtml}${escapeHtml(e.msg)}</span>
      </div>`;
    }
    list.innerHTML = html;
    list.querySelectorAll('.event-row').forEach(row => {
      row.addEventListener('click', () => {
        const t = parseFloat(row.dataset.t);
        if (isFinite(t)) seekVideo(t);
      });
    });
    if (activeIdx >= 0) {
      const active = list.querySelector('.event-row.active');
      if (active) {
        const r = active.getBoundingClientRect();
        const p = list.getBoundingClientRect();
        if (r.top < p.top + 20 || r.bottom > p.bottom - 20) {
          active.scrollIntoView({ block: 'nearest', behavior: 'instant' });
        }
      }
    }
  }

  // ── Scrub + time display ──────────────────────────────
  function renderScrub() {
    const pct = DURATION ? Math.max(0, Math.min(1, state.t / DURATION)) * 100 : 0;
    document.getElementById('scrub-fill').style.width = pct + '%';
    document.getElementById('scrub-handle').style.left = pct + '%';
    document.getElementById('ctl-time').textContent = `${fmtT(state.t)} / ${fmtT(DURATION)}`;
  }

  function renderMarkers() {
    const c = document.getElementById('scrub-markers');
    if (!DURATION) { c.innerHTML = ''; return; }
    const errors = EVENTS.filter(e => e.kind === 'error');
    const warns  = EVENTS.filter(e => e.kind === 'warn');
    c.innerHTML =
      errors.map(e => `<div class="scrub-marker" style="left:${(e.t / DURATION) * 100}%; background:var(--danger);"></div>`).join('') +
      warns.map(e => `<div class="scrub-marker" style="left:${(e.t / DURATION) * 100}%; background:var(--warning); opacity:0.5;"></div>`).join('');
  }

  // ── Play / seek wiring ────────────────────────────────
  function seekVideo(t) {
    if (!DURATION) return;
    t = Math.max(0, Math.min(DURATION, t));
    try { video.currentTime = t; } catch (e) {}
    state.t = t;
    renderScrub();
    renderMetrics();
    renderEvents();
  }

  function updatePlayIcon() {
    const ic = document.getElementById('play-icon');
    if (!video.paused) {
      ic.innerHTML = '<rect x="4.5" y="3" width="2.5" height="10" rx="0.5"/><rect x="9" y="3" width="2.5" height="10" rx="0.5"/>';
    } else {
      ic.innerHTML = '<path d="M5 3.5v9l7-4.5z"/>';
    }
  }

  // ── Theme toggle ──────────────────────────────────────
  function paintThemeIcon() {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    const ic = document.getElementById('theme-icon');
    ic.innerHTML = cur === 'dark'
      ? '<circle cx="8" cy="8" r="2.5"/><path d="M8 1.5V3M8 13v1.5M14.5 8H13M3 8H1.5M3.6 3.6l1 1M11.4 11.4l1 1M11.4 4.6l1-1M3.6 12.4l1-1"/>'
      : '<path d="M13.5 9.5A6 6 0 0 1 6.5 2.5 6 6 0 1 0 13.5 9.5Z"/>';
  }
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('trailbox_viewer_theme', next); } catch (e) {}
    paintThemeIcon();
  });

  // ── Video → state sync ────────────────────────────────
  video.addEventListener('loadedmetadata', () => {
    if (video.duration && (!DURATION || Math.abs(video.duration - DURATION) > 0.5)) {
      DURATION = video.duration;
    }
    renderScrub();
    renderMarkers();
    renderMetrics();
    renderEvents();
    renderTopStats();
    forceHideOverlayTracks();
  });
  video.addEventListener('timeupdate', () => {
    state.t = video.currentTime;
    renderScrub();
    renderMetrics();
    renderEvents();
  });
  video.addEventListener('play', updatePlayIcon);
  video.addEventListener('pause', updatePlayIcon);

  // Browser-toggled subtitle overlays cover the playback area; we render
  // the same data in the events list so force them hidden on every load.
  // (Native player can still un-hide them via the kebab menu.)
  function forceHideOverlayTracks() {
    const tracks = video.textTracks;
    for (let i = 0; i < tracks.length; i++) tracks[i].mode = 'hidden';
  }

  // ── Controls wiring ───────────────────────────────────
  document.getElementById('play').addEventListener('click', () => {
    if (video.paused) video.play().catch(() => {});
    else video.pause();
  });
  document.getElementById('prev').addEventListener('click', () => {
    const earlier = EVENTS.filter(e => e.t < state.t - 0.5).sort((a, b) => b.t - a.t)[0];
    if (earlier) seekVideo(earlier.t);
  });
  document.getElementById('next').addEventListener('click', () => {
    const later = EVENTS.find(e => e.t > state.t + 0.5);
    if (later) seekVideo(later.t);
  });
  document.getElementById('scrub').addEventListener('click', e => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    seekVideo(pct * DURATION);
  });
  document.getElementById('speed').querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      const rate = parseFloat(btn.dataset.rate);
      video.playbackRate = rate;
      document.querySelectorAll('.speed button').forEach(b => b.classList.toggle('active', b === btn));
    });
  });
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      state.filter = btn.dataset.kind;
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b === btn));
      recomputeFiltered();
      renderEvents();
    });
  });
  document.getElementById('event-tabs').querySelectorAll('.tab').forEach(t => {
    t.addEventListener('click', () => {
      state.tab = t.dataset.tab;
      document.querySelectorAll('#event-tabs .tab').forEach(b => b.classList.toggle('active', b === t));
      recomputeFiltered();
      renderEvents();
    });
  });
  document.getElementById('search').addEventListener('input', e => {
    state.query = e.target.value;
    recomputeFiltered();
    renderEvents();
  });
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === ' ')        { e.preventDefault(); document.getElementById('play').click(); }
    else if (e.key === 'ArrowLeft')  document.getElementById('prev').click();
    else if (e.key === 'ArrowRight') document.getElementById('next').click();
  });

  // ── Listen for seek requests from the embedding Hub detail page. ──
  // The Hub's events tab postMessages { type: 'trailbox.seek', t_video_s }
  // and our owner-auth viewer iframe is same-origin so this just works.
  window.addEventListener('message', ev => {
    if (!ev.data || ev.data.type !== 'trailbox.seek') return;
    const t = parseFloat(ev.data.t_video_s);
    if (isFinite(t)) seekVideo(t);
  });

  // ── Init ──────────────────────────────────────────────
  buildMetrics();
  recomputeFiltered();
  updateCounts();
  renderTopStats();
  renderSpec();
  renderScrub();
  renderMarkers();
  renderMetrics();
  renderEvents();
  paintThemeIcon();
})();
</script>
</body>
</html>
"""


# ────────────────────────────────────────────────────────────────────────
# Loaders
# ────────────────────────────────────────────────────────────────────────


def _classify_log(message: str) -> str:
    if not message:
        return "log"
    if _ERR_RE.search(message):
        return "error"
    if _WARN_RE.search(message):
        return "warn"
    return "log"


def _format_input(inp: dict[str, Any]) -> str:
    """Synthesize a human-readable line from an input payload."""
    kind = inp.get("type") or inp.get("kind") or "input"
    if kind == "key":
        action = inp.get("action", "press")
        key = inp.get("key", "?")
        return f"key {action} · {key}"
    if kind in ("mouse", "click"):
        btn = inp.get("button", "?")
        act = "press" if inp.get("pressed") else "release"
        x, y = inp.get("x"), inp.get("y")
        if x is not None and y is not None:
            return f"mouse {btn} {act} @ ({x},{y})"
        return f"mouse {btn} {act}"
    if kind == "scroll":
        dx, dy = inp.get("dx", 0), inp.get("dy", 0)
        return f"scroll dx={dx} dy={dy}"
    if kind == "move":
        x, y = inp.get("x"), inp.get("y")
        return f"move @ ({x},{y})"
    return str(kind)


def _load_frames(session_dir: Path) -> list[dict[str, Any]]:
    """Per-frame interval data, converted to instantaneous fps for plotting."""
    path = session_dir / "metrics" / "frames.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        delta = rec.get("frame", {}).get("delta_ms")
        if delta is None or delta <= 0:
            continue
        out.append({
            "t": float(rec.get("t_video_s", 0.0)),
            "fps": round(1000.0 / float(delta), 2),
        })
    return out


def _load_metrics(session_dir: Path) -> list[dict[str, Any]]:
    """Load metrics/process.jsonl samples; empty list if file missing."""
    path = session_dir / "metrics" / "process.jsonl"
    if not path.exists():
        return []
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        proc = rec.get("process", {})
        samples.append(
            {
                "t": float(rec.get("t_video_s", 0.0)),
                "cpu_pct": proc.get("cpu_pct"),
                "rss_mb": proc.get("rss_mb"),
                "threads": proc.get("threads"),
                "handles": proc.get("handles"),
                "gpu_pct": proc.get("gpu_pct"),
                "gpu_vram_mb": proc.get("gpu_vram_mb"),
            }
        )
    samples.sort(key=lambda s: s["t"])
    return samples


def _load_events(session_dir: Path) -> list[dict[str, Any]]:
    """Merge inputs.jsonl + every logs/*.jsonl into a single timeline.

    Returns ``[{"t", "kind", "src", "msg"}, ...]`` sorted by t. Log
    records are classified as 'warn' / 'error' by substring match against
    the message so the viewer can highlight them without needing a
    structured level field in the JSON.
    """
    events: list[dict[str, Any]] = []

    inputs_path = session_dir / "inputs" / "inputs.jsonl"
    if inputs_path.exists():
        for line in inputs_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            inp = rec.get("input") or {}
            events.append({
                "t": float(rec.get("t_video_s", 0.0)),
                "kind": "input",
                "src": inp.get("type") or "input",
                "msg": _format_input(inp),
            })

    logs_dir = session_dir / "logs"
    if logs_dir.is_dir():
        for logs_path in sorted(logs_dir.glob("*.jsonl")):
            for line in logs_path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                log_rec = rec.get("log") or {}
                src = (log_rec.get("source") or {}).get("name") or logs_path.stem
                msg = rec.get("message", "")
                events.append({
                    "t": float(rec.get("t_video_s", 0.0)),
                    "kind": _classify_log(msg),
                    "src": src,
                    "msg": msg,
                })

    events.sort(key=lambda e: e["t"])
    return events


def _safe_inline_json(payload: Any) -> str:
    """JSON-encode for embedding in ``<script type="application/json">``.

    Escapes ``</`` (would otherwise terminate the script tag in some parsers).
    """
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
    )


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────


def generate_viewer(session_dir: Path, meta: dict[str, Any]) -> Path:
    session_dir = Path(session_dir)
    events = _load_events(session_dir)

    tracks_html_lines: list[str] = []
    logs_dir = session_dir / "logs"
    inputs_vtt = session_dir / "inputs" / "inputs.vtt"
    # NB: never use the `default` attribute on these tracks. Under file://
    # Chromium silently refuses to load `<track>` files so the overlay never
    # appears — but over HTTP (Hub viewer) `default` tells the browser to
    # render the cues on top of the video, which clutters the playback area.
    # The side panel (built from the inlined jsonl) is the canonical view;
    # the VTT tracks are kept only for users who want native browser-toggled
    # captions. The forceHideOverlayTracks() JS in the template also pins
    # them hidden on load.
    if logs_dir.is_dir():
        for vtt_path in sorted(logs_dir.glob("*.vtt")):
            if vtt_path.stat().st_size <= 10:
                continue
            label = vtt_path.stem
            tracks_html_lines.append(
                f'      <track src="logs/{vtt_path.name}" kind="subtitles" srclang="en" label="{label}">'
            )
    if inputs_vtt.exists() and inputs_vtt.stat().st_size > 10:
        tracks_html_lines.append(
            '      <track src="inputs/inputs.vtt" kind="subtitles" srclang="en" label="inputs">'
        )

    metrics = _load_metrics(session_dir)
    frames = _load_frames(session_dir)

    html = (
        _HTML_TEMPLATE
        .replace("__SESSION_ID__", meta.get("session_id", session_dir.name))
        .replace("__TRACKS_HTML__", "\n".join(tracks_html_lines))
        .replace("__EVENTS_JSON__", _safe_inline_json(events))
        .replace("__META_JSON__", _safe_inline_json(meta))
        .replace("__METRICS_JSON__", _safe_inline_json(metrics))
        .replace("__FRAMES_JSON__", _safe_inline_json(frames))
    )
    out = session_dir / "viewer.html"
    out.write_text(html, encoding="utf-8")
    return out
