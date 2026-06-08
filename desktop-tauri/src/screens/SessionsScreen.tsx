import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { invoke, convertFileSrc } from '@tauri-apps/api/core';
import { confirm, message } from '@tauri-apps/plugin-dialog';
import { Icon } from '../components/Icon';
import { type HubState, type UnifiedSession } from '../data/mock';

type Props = {
  hub: HubState;
  localSessions: any[];
  remoteSessions: any[];
  sessionsLoading?: boolean;
  onRefresh?: () => void;
};

type Filter = 'all' | 'local' | 'synced' | 'cloud';

function fmtDur(s: number) { const m = Math.floor(s / 60), sec = Math.floor(s % 60); return `${m}:${String(sec).padStart(2, '0')}`; }
function fmtSize(b: number) { if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`; if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`; return `${(b / 1e3).toFixed(0)} KB`; }
function fmtNum(n: number) { if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`; if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`; return String(n); }
function relTime(s: string) {
  if (!s) return '';
  const d = Date.now() - new Date(s.replace(' ', 'T')).getTime();
  if (d < 60_000) return '방금 전';
  if (d < 3600_000) return `${Math.floor(d / 60_000)}분 전`;
  if (d < 86400_000) return `${Math.floor(d / 3600_000)}시간 전`;
  return `${Math.floor(d / 86400_000)}일 전`;
}

function LocationIcon({ local, remote }: { local: boolean; remote: boolean }) {
  if (local && remote) return <span title="로컬 + Hub 동기화됨" style={{ color: 'var(--success)' }}>{Icon.Check()}</span>;
  if (remote) return <span title="Hub에만 존재" style={{ color: 'var(--accent)' }}>{Icon.Link()}</span>;
  return <span title="로컬에만 존재" style={{ color: 'var(--muted)' }}>{Icon.PC()}</span>;
}

function LocationBadge({ local, remote }: { local: boolean; remote: boolean }) {
  if (local && remote) return <span className="tbd-badge tbd-badge--success"><span className="dot" />동기화됨</span>;
  if (remote) return <span className="tbd-badge tbd-badge--accent">클라우드</span>;
  return <span className="tbd-badge" style={{ color: 'var(--muted)' }}>로컬</span>;
}

export function SessionsScreen({ hub, localSessions: rawLocal, remoteSessions: rawRemote, sessionsLoading, onRefresh }: Props) {
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [uploadProg, setUploadProg] = useState<{ sid: string; done: number; total: number } | null>(null);
  const [trimSid, setTrimSid] = useState<string | null>(null);

  // Merge local + remote into unified list
  const sessions: UnifiedSession[] = useMemo(() => {
    const map = new Map<string, UnifiedSession>();

    // Local sessions first
    for (const s of rawLocal) {
      map.set(s.session_id, {
        session_id: s.session_id,
        local: true,
        remote: s.uploaded || false,
        started: s.started_at ?? '',
        started_rel: s.started_at ? relTime(s.started_at) : '',
        duration: s.duration_seconds ?? 0,
        size: s.size_bytes ?? 0,
        exe: s.exe_path?.split('\\').pop()?.split('/').pop() ?? '',
        device: (s.device as 'PC' | 'Android') ?? 'PC',
        frames: s.screen_frames ?? 0,
        events: (s.input_events ?? 0) + (s.log_lines ?? 0),
        owner: '',
        has_viewer: s.has_viewer ?? false,
      });
    }

    // Merge remote sessions
    for (const s of rawRemote) {
      const id = s.session_id ?? '';
      const existing = map.get(id);
      if (existing) {
        existing.remote = true;
        if (s.owner) existing.owner = s.owner;
      } else {
        map.set(id, {
          session_id: id,
          local: false,
          remote: true,
          started: s.started_at ?? s.started ?? '',
          started_rel: relTime(s.started_at ?? s.started ?? ''),
          duration: s.duration_seconds ?? s.duration ?? 0,
          size: s.size_bytes ?? s.size ?? 0,
          exe: '',
          device: 'PC',
          frames: 0,
          events: 0,
          owner: s.owner ?? '',
          has_viewer: s.has_viewer ?? false,
        });
      }
    }

    const list = Array.from(map.values());
    list.sort((a, b) => b.started.localeCompare(a.started));
    return list;
  }, [rawLocal, rawRemote]);

  // Filter + search
  const filtered = useMemo(() => {
    return sessions.filter(s => {
      if (filter === 'local' && !(s.local && !s.remote)) return false;
      if (filter === 'synced' && !(s.local && s.remote)) return false;
      if (filter === 'cloud' && !(!s.local && s.remote)) return false;
      if (query) {
        const q = query.toLowerCase();
        if (!s.session_id.toLowerCase().includes(q) && !s.exe.toLowerCase().includes(q) && !s.owner.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [sessions, filter, query]);

  const selectedSession = sessions.find(s => s.session_id === selected);

  // Counts
  const localOnly = sessions.filter(s => s.local && !s.remote).length;
  const synced = sessions.filter(s => s.local && s.remote).length;
  const cloudOnly = sessions.filter(s => !s.local && s.remote).length;

  const [downloadProg, setDownloadProg] = useState<string | null>(null);

  const doOpenViewer = async (sid: string) => {
    try { await invoke('open_viewer', { sessionId: sid }); } catch (e) { await message(`뷰어 열기 실패: ${e}`, { title: 'Trailbox', kind: 'error' }); }
  };
  const doOpenHubViewer = async (sid: string) => {
    if (!hub.configured) return;
    try { await invoke('open_url', { url: `${hub.url}/sessions/${sid}/v/` }); } catch (e) { await message(`Hub 뷰어 열기 실패: ${e}`, { title: 'Trailbox', kind: 'error' }); }
  };
  const doDelete = async (sid: string) => {
    const ok = await confirm(`세션 ${sid}을(를) 삭제하시겠습니까?`, { title: '세션 삭제', kind: 'warning' });
    if (!ok) return;
    try { await invoke('delete_session', { sessionId: sid }); setSelected(null); onRefresh?.(); } catch (e) { await message(`삭제 실패: ${e}`, { title: 'Trailbox', kind: 'error' }); }
  };
  const doUpload = async (sid: string) => {
    if (!hub.configured) return;
    setUploadProg({ sid, done: 0, total: 100 });
    try {
      await invoke('hub_upload', { url: hub.url, token: hub.token, sessionId: sid });
      setUploadProg({ sid, done: 100, total: 100 });
      setTimeout(() => setUploadProg(null), 800);
      onRefresh?.();
    } catch (e) { setUploadProg(null); await message(`업로드 실패: ${e}`, { title: 'Trailbox', kind: 'error' }); }
  };
  const doDownload = async (sid: string) => {
    if (!hub.configured) return;
    setDownloadProg(sid);
    try {
      await invoke('hub_download', { url: hub.url, token: hub.token, sessionId: sid });
      setDownloadProg(null);
      onRefresh?.();
    } catch (e) { setDownloadProg(null); await message(`다운로드 실패: ${e}`, { title: 'Trailbox', kind: 'error' }); }
  };

  return (
    <div>
      <div className="section-header">
        <div><h1>세션</h1><p>로컬 · Hub 통합 목록</p></div>
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <div className="tbd-radio-group" style={{ flex: 0 }}>
          <button className={`tbd-radio ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
            전체 · {sessions.length}
          </button>
          <button className={`tbd-radio ${filter === 'local' ? 'active' : ''}`} onClick={() => setFilter('local')}>
            {Icon.PC()}로컬 · {localOnly}
          </button>
          <button className={`tbd-radio ${filter === 'synced' ? 'active' : ''}`} onClick={() => setFilter('synced')}>
            {Icon.Check()}동기화 · {synced}
          </button>
          {cloudOnly > 0 && (
            <button className={`tbd-radio ${filter === 'cloud' ? 'active' : ''}`} onClick={() => setFilter('cloud')}>
              {Icon.Link()}클라우드 · {cloudOnly}
            </button>
          )}
        </div>
        <div style={{ position: 'relative', flex: 1, maxWidth: 220 }}>
          <span style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--subtle)' }}>
            {Icon.Search({ width: 12, height: 12 } as any)}
          </span>
          <input className="tbd-input" placeholder="검색…" value={query} onChange={e => setQuery(e.target.value)} style={{ paddingLeft: 26 }} />
        </div>
        <button className="tbd-btn tbd-btn--icon" onClick={() => onRefresh?.()} disabled={sessionsLoading}>{Icon.Refresh()}</button>
      </div>

      {/* Table */}
      <div className="tbd-session-table">
        <div className="tbd-session-table__head">
          <span></span>
          <span>Session ID</span>
          <span>EXE / 소유자</span>
          <span style={{ textAlign: 'right' }}>길이</span>
          <span style={{ textAlign: 'right' }}>크기</span>
          <span style={{ textAlign: 'right' }}>프레임</span>
          <span style={{ textAlign: 'right' }}>이벤트</span>
          <span></span>
        </div>
        <div className="tbd-session-table__body">
          {sessionsLoading ? <LoadingRows /> :
           filtered.length > 0 ? filtered.map(s => (
            <SessionRow key={s.session_id} s={s} selected={selected === s.session_id} onClick={() => setSelected(s.session_id)} />
          )) : <EmptyRows query={query} />}
        </div>

        {/* Action bar */}
        {selected && selectedSession && (
          <div className="tbd-session-actions">
            <div className="tbd-session-actions__info">
              <span style={{ color: 'var(--muted)', fontSize: 12 }}>선택됨:</span>
              <span className="mono" style={{ fontSize: 12, fontWeight: 500 }}>{selected}</span>
              <LocationBadge local={selectedSession.local} remote={selectedSession.remote} />
            </div>
            {selectedSession.local && (
              <>
                <button className="tbd-btn" disabled={!hub.configured || selectedSession.remote} onClick={() => doUpload(selected!)}>{Icon.Upload()}Hub 업로드</button>
                <button className="tbd-btn tbd-btn--danger" onClick={() => doDelete(selected!)}>{Icon.Trash()}삭제</button>
                {selectedSession.remote && selectedSession.has_viewer && (
                  <button className="tbd-btn" onClick={() => doOpenHubViewer(selected!)}>{Icon.Link()}Hub 뷰어</button>
                )}
                <button className="tbd-btn" onClick={() => setTrimSid(selected!)}>✂ 트리밍</button>
                <button className="tbd-btn tbd-btn--primary" onClick={() => doOpenViewer(selected!)}>{Icon.Eye()}뷰어 열기</button>
              </>
            )}
            {!selectedSession.local && selectedSession.remote && (
              <>
                <button className="tbd-btn" disabled={downloadProg === selected} onClick={() => doDownload(selected!)}>
                  {Icon.Download()}{downloadProg === selected ? '다운로드 중…' : '다운로드'}
                </button>
                {selectedSession.has_viewer && (
                  <button className="tbd-btn tbd-btn--primary" onClick={() => doOpenHubViewer(selected!)}>{Icon.Eye()}Hub 뷰어</button>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Trim modal */}
      {trimSid && (
        <TrimModal
          sessionId={trimSid}
          duration={sessions.find(s => s.session_id === trimSid)?.duration ?? 0}
          onClose={() => setTrimSid(null)}
          onDone={() => { setTrimSid(null); onRefresh?.(); }}
        />
      )}

      {/* Upload progress */}
      {uploadProg && (
        <div className="tbd-upload-pop">
          <div className="tbd-upload-pop__head">
            {Icon.Upload()}<span className="tbd-upload-pop__title">Hub 업로드 중…</span>
            <span className="tbd-upload-pop__size">{Math.round(uploadProg.done)} / {uploadProg.total} MB</span>
          </div>
          <div className="tbd-progress"><div className="tbd-progress__fill" style={{ width: `${(uploadProg.done / uploadProg.total) * 100}%` }} /></div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>{uploadProg.sid}</div>
        </div>
      )}
    </div>
  );
}

function SessionRow({ s, selected, onClick }: { s: UnifiedSession; selected: boolean; onClick: () => void }) {
  return (
    <div className={`tbd-session-row ${selected ? 'selected' : ''}`} onClick={onClick}>
      <span className="tbd-session-row__icon"><LocationIcon local={s.local} remote={s.remote} /></span>
      <div>
        <div className="tbd-session-row__id">{s.session_id}</div>
        <div className="tbd-session-row__sub">{s.started_rel}</div>
      </div>
      <span className="mono" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {s.exe || s.owner || '—'}
      </span>
      <span className="tbd-session-row__num">{fmtDur(s.duration)}</span>
      <span className="tbd-session-row__num">{fmtSize(s.size)}</span>
      <span className="tbd-session-row__num">{s.frames ? fmtNum(s.frames) : '—'}</span>
      <span className="tbd-session-row__num">{s.events ? fmtNum(s.events) : '—'}</span>
      <span />
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="tbd-empty">
      <div style={{ width: 28, height: 28, border: '2px solid var(--border)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'tbd-spin 1s linear infinite' }} />
      <p>로딩 중…</p>
    </div>
  );
}

function EmptyRows({ query }: { query: string }) {
  return (
    <div className="tbd-empty">
      {Icon.Sessions({ width: 28, height: 28, style: { opacity: 0.4 } } as any)}
      <h2>표시할 세션이 없습니다</h2>
      <p>{query ? '검색어를 조정해보세요' : '캡처를 시작하면 여기에 나타납니다'}</p>
    </div>
  );
}

// ── Trim modal ────────────────────────────────────────────────────────
// Watch the recorded video, mark in/out, save as a new session or
// overwrite. Backend is `invoke('trim_session', …)` → bridge.py
// → core/trim.py (same engine the Hub trim endpoint uses).

function fmtMs(t: number) {
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  const ms = Math.round((t - Math.floor(t)) * 1000);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function TrimModal({
  sessionId, duration, onClose, onDone,
}: {
  sessionId: string;
  duration: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [src, setSrc] = useState<string>('');
  const [srcErr, setSrcErr] = useState<string>('');
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(duration);
  const [tIn, setTIn] = useState<number | null>(null);
  const [tOut, setTOut] = useState<number | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>('');
  const [playing, setPlaying] = useState(false);

  // Resolve video path on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const path = await invoke<string>('get_session_video_path', { sessionId });
        if (!cancelled) setSrc(convertFileSrc(path));
      } catch (e) {
        if (!cancelled) setSrcErr(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  // Keep t in sync with the video element.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setT(v.currentTime);
    const onMeta = () => { if (v.duration && isFinite(v.duration)) setDur(v.duration); };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener('timeupdate', onTime);
    v.addEventListener('loadedmetadata', onMeta);
    v.addEventListener('play', onPlay);
    v.addEventListener('pause', onPause);
    return () => {
      v.removeEventListener('timeupdate', onTime);
      v.removeEventListener('loadedmetadata', onMeta);
      v.removeEventListener('play', onPlay);
      v.removeEventListener('pause', onPause);
    };
  }, [src]);

  const seek = useCallback((time: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.max(0, Math.min(dur, time));
  }, [dur]);

  // Don't nest setState calls inside an updater — React 18 batching makes
  // the order non-obvious and the closure capture trips us up. Just compute
  // both new values up front, then issue two normal setStates.
  const setIn = useCallback(() => {
    const newIn = t;
    if (tOut != null && tOut < newIn) {
      // New In is past current Out — swap so the canonical order holds.
      setTIn(tOut);
      setTOut(newIn);
    } else {
      setTIn(newIn);
    }
  }, [t, tOut]);

  const setOut = useCallback(() => {
    const newOut = t;
    if (tIn != null && newOut < tIn) {
      setTOut(tIn);
      setTIn(newOut);
    } else {
      setTOut(newOut);
    }
  }, [t, tIn]);

  // Keyboard shortcuts (I / O / Space / Backspace / Esc).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === 'i' || e.key === 'I') { e.preventDefault(); setIn(); }
      else if (e.key === 'o' || e.key === 'O') { e.preventDefault(); setOut(); }
      else if (e.key === 'Backspace') { e.preventDefault(); setTIn(null); setTOut(null); }
      else if (e.key === 'Escape') { e.preventDefault(); if (!saving) onClose(); }
      else if (e.key === ' ') {
        e.preventDefault();
        const v = videoRef.current; if (!v) return;
        if (v.paused) v.play().catch(() => {}); else v.pause();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setIn, setOut, onClose, saving]);

  const validRange = tIn != null && tOut != null && Math.abs(tOut - tIn) >= 0.1;
  const trimLen = (tIn != null && tOut != null) ? Math.abs(tOut - tIn) : null;
  const pctOf = (x: number) => dur > 0 ? Math.max(0, Math.min(100, (x / dur) * 100)) : 0;
  const playheadPct = pctOf(t);
  const inPct = tIn != null ? pctOf(tIn) : 0;
  const rangePct = (tIn != null && tOut != null) ? Math.max(0, pctOf(tOut) - pctOf(tIn)) : 0;

  const onScrubClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - r.left) / r.width;
    seek(pct * dur);
  };

  const save = async () => {
    if (!validRange || saving) return;
    // Belt-and-braces: regardless of which order the user marked them in,
    // send the lower as t_start and the higher as t_end. The backend rejects
    // inverted ranges, so the swap logic above is the primary fix — this
    // sort just makes sure a missed render can't blow up the call.
    const lo = Math.min(tIn!, tOut!);
    const hi = Math.max(tIn!, tOut!);
    setSaving(true);
    setError('');
    try {
      const res = await invoke<any>('trim_session', {
        sessionId, tStart: lo, tEnd: hi, overwrite,
      });
      console.log('trim_session result', res);
      onDone();
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
      }}
      onClick={() => { if (!saving) onClose(); }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(940px, 96vw)', maxHeight: '94vh',
          background: 'var(--surface)', color: 'var(--fg)',
          border: '1px solid var(--border)', borderRadius: 12,
          boxShadow: '0 18px 60px rgba(0,0,0,0.55)',
          padding: 18, display: 'grid', gap: 12,
          overflowY: 'auto',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>트림 — {sessionId}</h2>
          <span style={{ flex: 1 }} />
          <button className="tbd-btn" onClick={onClose} disabled={saving}>닫기</button>
        </div>

        {/* Video */}
        <div style={{ background: 'black', borderRadius: 8, overflow: 'hidden', aspectRatio: '16 / 9' }}>
          {srcErr ? (
            <div style={{ padding: 16, color: 'var(--danger)', fontSize: 13 }}>
              영상 경로를 찾지 못했습니다: {srcErr}
            </div>
          ) : src ? (
            <video
              ref={videoRef} src={src} controls={false} playsInline preload="metadata"
              style={{ width: '100%', height: '100%', display: 'block' }}
            />
          ) : (
            <div style={{ padding: 16, color: 'var(--muted)' }}>로딩 중…</div>
          )}
        </div>

        {/* Scrub bar */}
        <div
          onClick={onScrubClick}
          style={{
            position: 'relative', height: 22, cursor: 'pointer',
            background: 'oklch(0.22 0.01 270)', borderRadius: 11,
          }}
        >
          {/* range overlay */}
          {tIn != null && tOut != null && (
            <div style={{
              position: 'absolute', top: 0, bottom: 0,
              left: `${inPct}%`, width: `${rangePct}%`,
              background: 'var(--accent-soft)',
              borderLeft: '2px solid var(--accent)',
              borderRight: '2px solid var(--accent)',
              boxSizing: 'border-box',
              pointerEvents: 'none',
            }} />
          )}
          {/* playhead */}
          <div style={{
            position: 'absolute', top: '50%', left: `${playheadPct}%`,
            width: 12, height: 12, background: 'white', borderRadius: '50%',
            transform: 'translate(-50%, -50%)',
            boxShadow: '0 1px 4px rgba(0,0,0,0.5)',
            pointerEvents: 'none',
          }} />
        </div>

        {/* Controls row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            className="tbd-btn"
            onClick={() => {
              const v = videoRef.current; if (!v) return;
              if (v.paused) v.play().catch(() => {}); else v.pause();
            }}
          >
            {playing ? '일시정지' : '재생'}
          </button>
          <span className="mono" style={{ fontSize: 12, color: 'var(--muted)', minWidth: 140 }}>
            {fmtMs(t)} / {fmtMs(dur)}
          </span>
          <button className="tbd-btn" title="현재 시점을 시작점으로 (I)" onClick={setIn}>[ I 시작 ]</button>
          <button className="tbd-btn" title="현재 시점을 끝점으로 (O)" onClick={setOut}>[ O 끝 ]</button>
          <button className="tbd-btn" onClick={() => { setTIn(null); setTOut(null); }}>초기화</button>
          <span style={{ flex: 1 }} />
          <Readout label="in" v={tIn} />
          <Readout label="out" v={tOut} />
          <Readout label="길이" v={trimLen} />
        </div>

        {/* Save options */}
        <div style={{
          display: 'grid', gap: 8,
          padding: 12,
          background: 'var(--bg-2)', borderRadius: 8,
        }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
            <input type="radio" checked={!overwrite} onChange={() => setOverwrite(false)} />
            새 세션으로 저장 <span style={{ color: 'var(--muted)', fontSize: 11.5 }}>
              {sessionId}_trim_NNN/ 형태로 새 폴더 생성. 원본 유지.
            </span>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
            <input type="radio" checked={overwrite} onChange={() => setOverwrite(true)} />
            원본 덮어쓰기 <span style={{ color: 'var(--muted)', fontSize: 11.5 }}>
              디스크 절약. 되돌릴 수 없음.
            </span>
          </label>
        </div>

        {error && (
          <div style={{ color: 'var(--danger)', fontSize: 12.5 }}>저장 실패: {error}</div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="tbd-btn" onClick={onClose} disabled={saving}>취소</button>
          <button
            className="tbd-btn tbd-btn--primary"
            disabled={!validRange || saving || !src}
            onClick={save}
          >
            {saving ? '저장 중…' : '저장'}
          </button>
        </div>

        <div style={{ fontSize: 11, color: 'var(--muted)' }}>
          단축키 · 재생/일시정지 Space · 시작 마크 I · 끝 마크 O · 초기화 Backspace · 닫기 Esc
        </div>
      </div>
    </div>
  );
}

function Readout({ label, v }: { label: string; v: number | null }) {
  const unset = v == null;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'baseline', gap: 4,
      fontFamily: 'var(--mono, monospace)', fontSize: 12,
    }}>
      <span style={{
        color: 'var(--muted)', fontSize: 10.5, fontWeight: 600,
        textTransform: 'uppercase', letterSpacing: '0.04em',
      }}>{label}</span>
      <span style={{ color: unset ? 'var(--muted)' : 'var(--fg)' }}>
        {unset ? '—' : fmtMs(v!)}
      </span>
    </span>
  );
}
