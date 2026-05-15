"""Generate a self-contained ``viewer.html`` for a finished session.

The viewer is opened directly from the filesystem (file://). It plays
``screen.mp4`` and shows ``logs.vtt`` / ``inputs.vtt`` as native subtitle
tracks (optional toggle in the browser's player). A side panel lists every
log + input event from ``logs.jsonl`` and ``inputs.jsonl``, sorted by
``t_video_s``, with filter checkboxes, free-text search, and click-to-seek.

Event data is inlined as JSON in a ``<script type="application/json">`` tag
so the viewer works under file:// without any local server (browsers block
fetch() to local files but inline JSON parses fine).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Trailbox Viewer — __SESSION_ID__</title>
<style>
  :root {
    --bg: #1e1e1e;
    --panel: #252526;
    --border: #3e3e42;
    --text: #d4d4d4;
    --text-dim: #969696;
    --log: #4ec9b0;
    --input: #ce9178;
    --highlight: #094771;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, "Segoe UI", "Malgun Gothic", Helvetica, sans-serif;
    background: var(--bg); color: var(--text);
    height: 100vh; overflow: hidden;
    display: flex; flex-direction: column;
  }
  header {
    padding: 8px 16px; border-bottom: 1px solid var(--border);
    background: var(--panel);
    display: flex; align-items: center; gap: 16px;
  }
  header h1 { font-size: 14px; margin: 0; font-weight: 500; }
  header .meta { color: var(--text-dim); font-size: 12px; }
  header details { font-size: 11px; color: var(--text-dim); }
  header details summary { cursor: pointer; user-select: none; }
  header details[open] summary { color: var(--text); }
  header details .specs {
    display: grid; grid-template-columns: auto 1fr;
    gap: 2px 12px; margin-top: 6px;
    font-family: ui-monospace, Consolas, monospace;
  }
  header details .specs .k { color: var(--text-dim); }
  header details .specs .v { color: var(--text); white-space: pre-wrap; }
  main { display: flex; flex: 1; overflow: hidden; }
  .video-pane {
    flex: 1.6; padding: 12px; background: black;
    display: flex; align-items: center; justify-content: center;
  }
  .video-pane video { max-width: 100%; max-height: 100%; }
  aside {
    width: 520px; min-width: 320px;
    border-left: 1px solid var(--border);
    display: flex; flex-direction: column;
    background: var(--panel);
  }
  .metrics-pane {
    padding: 8px 12px; border-bottom: 1px solid var(--border);
    background: #1d1d1d;
  }
  .metrics-pane .legend {
    font-size: 11px; color: var(--text-dim);
    display: flex; gap: 12px; margin-bottom: 4px;
    font-family: ui-monospace, Consolas, monospace;
  }
  .metrics-pane .legend .cpu { color: #f48771; }
  .metrics-pane .legend .rss { color: #7cb7ff; }
  .metrics-pane .legend .threads { color: #c8c8c8; }
  .metrics-pane canvas { display: block; width: 100%; height: 90px; }
  .metrics-pane.empty { display: none; }
  .filters {
    padding: 8px 12px; border-bottom: 1px solid var(--border);
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    font-size: 12px;
  }
  .filters label { user-select: none; cursor: pointer; }
  .filters input[type=checkbox] { vertical-align: middle; margin-right: 4px; }
  .filters input[type=search] {
    flex: 1; min-width: 100px;
    background: #1e1e1e; color: var(--text);
    border: 1px solid var(--border); padding: 4px 8px; font: inherit;
  }
  #timeline {
    flex: 1; overflow-y: auto;
    margin: 0; padding: 0; list-style: none; font-size: 12px;
  }
  #timeline li {
    display: flex; gap: 8px; padding: 4px 12px;
    border-bottom: 1px solid #2a2a2a; cursor: pointer;
  }
  #timeline li:hover { background: #2a2d2e; }
  #timeline li.current { background: var(--highlight); }
  #timeline li.input .kind { color: var(--input); }
  #timeline li.log .kind { color: var(--log); }
  #timeline li .t {
    flex: 0 0 64px; color: var(--text-dim);
    font-variant-numeric: tabular-nums; font-family: ui-monospace, Consolas, monospace;
  }
  #timeline li .kind {
    flex: 0 0 110px; font-size: 10px; padding-top: 2px;
    font-family: ui-monospace, Consolas, monospace;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  #timeline li .body { flex: 1; word-break: break-word; }
  footer {
    padding: 4px 12px; border-top: 1px solid var(--border);
    font-size: 11px; color: var(--text-dim);
  }
</style>
</head>
<body>
<header>
  <h1>__SESSION_ID__</h1>
  <span class="meta" id="meta-summary"></span>
  <details id="specs-details"><summary>PC 사양</summary><div class="specs" id="specs-grid"></div></details>
</header>
<main>
  <div class="video-pane">
    <video id="player" controls preload="metadata">
      <source src="screen.mp4" type="video/mp4">
__TRACKS_HTML__
    </video>
  </div>
  <aside>
    <div class="metrics-pane" id="metrics-pane">
      <div class="legend">
        <span class="cpu">CPU <span id="cur-cpu">--</span>%</span>
        <span class="rss">RSS <span id="cur-rss">--</span> MB</span>
        <span class="threads">threads <span id="cur-threads">--</span></span>
      </div>
      <canvas id="metrics-chart"></canvas>
    </div>
    <div class="filters">
      <label><input type="checkbox" data-filter="input" checked> 입력</label>
      <label><input type="checkbox" data-filter="log" checked> 로그</label>
      <label><input type="checkbox" data-filter="mouse" checked> 마우스</label>
      <label><input type="checkbox" data-filter="key" checked> 키</label>
      <input type="search" id="q" placeholder="검색…">
    </div>
    <ul id="timeline"></ul>
    <footer><span id="counts"></span></footer>
  </aside>
</main>

<script id="events-data" type="application/json">__EVENTS_JSON__</script>
<script id="meta-data" type="application/json">__META_JSON__</script>
<script id="metrics-data" type="application/json">__METRICS_JSON__</script>
<script>
  const events = JSON.parse(document.getElementById('events-data').textContent);
  const meta = JSON.parse(document.getElementById('meta-data').textContent);
  const metrics = JSON.parse(document.getElementById('metrics-data').textContent);
  const video = document.getElementById('player');
  const timeline = document.getElementById('timeline');
  const counts = document.getElementById('counts');
  const metaSummary = document.getElementById('meta-summary');
  const searchInput = document.getElementById('q');
  const filterChecks = Array.from(document.querySelectorAll('.filters input[type=checkbox]'));

  const fs = meta.frame_stats || {};
  metaSummary.textContent = [
    events.length + ' events',
    (meta.duration_seconds || 0).toFixed(1) + 's',
    (meta.screen_frames || 0) + ' frames',
    (meta.effective_fps || 0).toFixed(1) + ' fps',
    (fs.avg_ms != null
      ? `Δ avg ${fs.avg_ms.toFixed(1)}ms / p99 ${(fs.p99_ms || 0).toFixed(1)}ms`
      : null),
    (meta.audio_enabled ? '오디오' : '오디오 없음'),
    (meta.log_lines || 0) + '라인',
    (meta.input_events || 0) + '입력',
    (meta.cpu_cores ? meta.cpu_cores + ' cores' : '? cores')
  ].filter(Boolean).join('  ·  ');

  // ---- PC specs panel ---------------------------------------------------

  const specsGrid = document.getElementById('specs-grid');
  const specsDetails = document.getElementById('specs-details');
  const sys = meta.system || {};
  if (!Object.keys(sys).length) {
    specsDetails.style.display = 'none';
  } else {
    function addSpec(label, value) {
      if (!value && value !== 0) return;
      const k = document.createElement('span'); k.className = 'k'; k.textContent = label;
      const v = document.createElement('span'); v.className = 'v'; v.textContent = String(value);
      specsGrid.appendChild(k); specsGrid.appendChild(v);
    }
    if (sys.os) {
      const o = sys.os;
      addSpec('OS', `${o.release || ''} (build ${o.build || '?'})`.trim());
    }
    if (sys.cpu) {
      const c = sys.cpu;
      const cores = `${c.physical_cores || '?'}P / ${c.logical_cores || '?'}L`;
      const mhz = c.max_mhz ? ` @ ${(c.max_mhz / 1000).toFixed(2)} GHz` : '';
      addSpec('CPU', `${c.name || '?'} — ${cores}${mhz}`);
    }
    if (sys.ram) {
      const r = sys.ram;
      addSpec('RAM', `${((r.total_mb || 0) / 1024).toFixed(1)} GB total · ${((r.available_mb_at_start || 0) / 1024).toFixed(1)} GB free at start`);
    }
    if (sys.gpus && sys.gpus.length) {
      addSpec('GPU', sys.gpus.join(' / '));
    }
    if (sys.displays && sys.displays.length) {
      const d = sys.displays.map(s => {
        const nw = s.native_width || s.width;
        const nh = s.native_height || s.height;
        const scale = s.device_pixel_ratio && s.device_pixel_ratio !== 1
          ? ` (${Math.round(s.device_pixel_ratio * 100)}% scale)` : '';
        return `${nw}×${nh}@${s.refresh_hz}Hz${scale}${s.primary ? ' (primary)' : ''}`;
      }).join(' · ');
      addSpec('Display', d);
    }
    if (sys.trailbox_version) addSpec('Trailbox', `v${sys.trailbox_version}`);
    if (sys.python) addSpec('Python', sys.python);
  }

  function fmtTime(t) {
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return m + ':' + s.toFixed(3).padStart(6, '0');
  }

  function passesFilter(ev) {
    const srcCheck = filterChecks.find(c => c.dataset.filter === ev.kind);
    if (srcCheck && !srcCheck.checked) return false;
    if (ev.kind === 'input') {
      if (ev.subtype.startsWith('mouse/')) {
        const c = filterChecks.find(c => c.dataset.filter === 'mouse');
        if (c && !c.checked) return false;
      } else if (ev.subtype.startsWith('key/')) {
        const c = filterChecks.find(c => c.dataset.filter === 'key');
        if (c && !c.checked) return false;
      }
    }
    const q = searchInput.value.trim().toLowerCase();
    if (q && !ev.text.toLowerCase().includes(q) && !ev.subtype.toLowerCase().includes(q)) {
      return false;
    }
    return true;
  }

  let currentEventIdx = -1;

  function render() {
    const frag = document.createDocumentFragment();
    let visible = 0;
    events.forEach((ev, i) => {
      if (!passesFilter(ev)) return;
      visible++;
      const li = document.createElement('li');
      li.className = ev.kind;
      li.dataset.idx = String(i);
      const t = document.createElement('span'); t.className = 't'; t.textContent = fmtTime(ev.t);
      const k = document.createElement('span'); k.className = 'kind'; k.textContent = ev.subtype;
      const b = document.createElement('span'); b.className = 'body'; b.textContent = ev.text;
      li.appendChild(t); li.appendChild(k); li.appendChild(b);
      li.addEventListener('click', () => {
        video.currentTime = ev.t;
        video.play().catch(() => {});
      });
      frag.appendChild(li);
    });
    timeline.replaceChildren(frag);
    counts.textContent = visible + ' / ' + events.length + ' visible';
    currentEventIdx = -1;
    highlightCurrent();
  }

  function highlightCurrent() {
    const t = video.currentTime;
    let idx = -1;
    // Linear search is fine for thousands of events.
    for (let i = 0; i < events.length; i++) {
      if (events[i].t > t) break;
      idx = i;
    }
    if (idx === currentEventIdx) return;
    currentEventIdx = idx;
    const prev = timeline.querySelector('li.current');
    if (prev) prev.classList.remove('current');
    if (idx >= 0) {
      const cur = timeline.querySelector('li[data-idx="' + idx + '"]');
      if (cur) {
        cur.classList.add('current');
        cur.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }

  // ---- Metrics chart -----------------------------------------------------

  const metricsPane = document.getElementById('metrics-pane');
  const chartCanvas = document.getElementById('metrics-chart');
  const curCpu = document.getElementById('cur-cpu');
  const curRss = document.getElementById('cur-rss');
  const curThreads = document.getElementById('cur-threads');

  if (!metrics.length) {
    metricsPane.classList.add('empty');
  }

  const cpuMax = Math.max(100, ...metrics.map(s => s.cpu_pct || 0));
  const rssMax = Math.max(1, ...metrics.map(s => s.rss_mb || 0));
  const tMax = Math.max(
    meta.duration_seconds || 0,
    ...metrics.map(s => s.t),
  ) || 1;

  function drawChart() {
    if (!metrics.length) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = chartCanvas.clientWidth;
    const cssH = chartCanvas.clientHeight;
    chartCanvas.width = cssW * dpr;
    chartCanvas.height = cssH * dpr;
    const ctx = chartCanvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, cssW, cssH);

    const padL = 0, padR = 0, padT = 4, padB = 4;
    const plotW = cssW - padL - padR;
    const plotH = cssH - padT - padB;

    function tx(t) { return padL + (t / tMax) * plotW; }
    function yCpu(v) { return padT + plotH - (v / cpuMax) * plotH; }
    function yRss(v) { return padT + plotH - (v / rssMax) * plotH; }

    // Grid: 25/50/75 lines (faint).
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;
    for (let i = 1; i <= 3; i++) {
      const y = padT + (plotH * i / 4);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
    }

    // CPU line.
    ctx.strokeStyle = '#f48771';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    metrics.forEach((s, i) => {
      const x = tx(s.t);
      const y = yCpu(s.cpu_pct || 0);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // RSS line.
    ctx.strokeStyle = '#7cb7ff';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    metrics.forEach((s, i) => {
      const x = tx(s.t);
      const y = yRss(s.rss_mb || 0);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Playhead line.
    const t = video.currentTime;
    const px = tx(t);
    ctx.strokeStyle = '#ffffff80';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(px, padT); ctx.lineTo(px, padT + plotH); ctx.stroke();
  }

  function currentMetric() {
    if (!metrics.length) return null;
    const t = video.currentTime;
    let cur = metrics[0];
    for (const s of metrics) {
      if (s.t > t) break;
      cur = s;
    }
    return cur;
  }

  function updateMetricsLegend() {
    const cur = currentMetric();
    if (!cur) {
      curCpu.textContent = '--';
      curRss.textContent = '--';
      curThreads.textContent = '--';
      return;
    }
    curCpu.textContent = (cur.cpu_pct ?? 0).toFixed(1);
    curRss.textContent = (cur.rss_mb ?? 0).toFixed(0);
    curThreads.textContent = String(cur.threads ?? '?');
  }

  video.addEventListener('timeupdate', () => { highlightCurrent(); updateMetricsLegend(); drawChart(); });
  window.addEventListener('resize', drawChart);
  filterChecks.forEach(c => c.addEventListener('change', render));
  searchInput.addEventListener('input', render);
  render();
  updateMetricsLegend();
  drawChart();
</script>
</body>
</html>
"""


def _format_input(inp: dict[str, Any]) -> str:
    t = inp.get("type")
    a = inp.get("action")
    if t == "key":
        k = inp.get("key", "?")
        prefix = "⌨" if a == "press" else "⌨↑"
        return f"{prefix} {k}"
    if t == "mouse":
        if a == "click":
            btn = inp.get("button", "?")
            press = "press" if inp.get("pressed") else "release"
            return f"🖱 {btn} {press} @ ({inp.get('x', 0)},{inp.get('y', 0)})"
        if a == "scroll":
            return f"🖱 scroll ({inp.get('dx', 0)},{inp.get('dy', 0)})"
        if a == "move":
            return f"🖱 move @ ({inp.get('x', 0)},{inp.get('y', 0)})"
    return json.dumps(inp, ensure_ascii=False)


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
            }
        )
    samples.sort(key=lambda s: s["t"])
    return samples


def _load_events(session_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    inputs_path = session_dir / "inputs" / "inputs.jsonl"
    if inputs_path.exists():
        for line in inputs_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            inp = rec.get("input", {})
            events.append(
                {
                    "t": float(rec.get("t_video_s", 0.0)),
                    "kind": "input",
                    "subtype": f"{inp.get('type', '?')}/{inp.get('action', '?')}",
                    "text": _format_input(inp),
                }
            )

    logs_path = session_dir / "logs" / "logs.jsonl"
    if logs_path.exists():
        for line in logs_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            log_file = rec.get("log", {}).get("file", {}).get("path", "?")
            events.append(
                {
                    "t": float(rec.get("t_video_s", 0.0)),
                    "kind": "log",
                    "subtype": log_file,
                    "text": rec.get("message", ""),
                }
            )

    events.sort(key=lambda e: e["t"])
    return events


def _safe_inline_json(payload: Any) -> str:
    """JSON-encode for embedding in <script type=application/json>.

    Escapes ``</`` (would otherwise terminate the script tag in some parsers).
    """
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
    )


def generate_viewer(session_dir: Path, meta: dict[str, Any]) -> Path:
    session_dir = Path(session_dir)
    events = _load_events(session_dir)

    tracks_html_lines: list[str] = []
    logs_vtt = session_dir / "logs" / "logs.vtt"
    inputs_vtt = session_dir / "inputs" / "inputs.vtt"
    if logs_vtt.exists() and logs_vtt.stat().st_size > 10:
        tracks_html_lines.append(
            '      <track src="logs/logs.vtt" kind="subtitles" srclang="en" label="logs">'
        )
    if inputs_vtt.exists() and inputs_vtt.stat().st_size > 10:
        tracks_html_lines.append(
            '      <track src="inputs/inputs.vtt" kind="subtitles" srclang="en" label="inputs" default>'
        )

    metrics = _load_metrics(session_dir)

    html = (
        _HTML_TEMPLATE
        .replace("__SESSION_ID__", meta.get("session_id", session_dir.name))
        .replace("__TRACKS_HTML__", "\n".join(tracks_html_lines))
        .replace("__EVENTS_JSON__", _safe_inline_json(events))
        .replace("__META_JSON__", _safe_inline_json(meta))
        .replace("__METRICS_JSON__", _safe_inline_json(metrics))
    )
    out = session_dir / "viewer.html"
    out.write_text(html, encoding="utf-8")
    return out
