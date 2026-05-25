import { useState, useMemo } from 'react';
import { invoke } from '@tauri-apps/api/core';
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
    try { await invoke('open_viewer', { sessionId: sid }); } catch (e) { alert(`뷰어 열기 실패: ${e}`); }
  };
  const doOpenHubViewer = async (sid: string) => {
    if (!hub.configured) return;
    try { await invoke('open_url', { url: `${hub.url}/sessions/${sid}/v/` }); } catch (e) { alert(`Hub 뷰어 열기 실패: ${e}`); }
  };
  const doDelete = async (sid: string) => {
    if (!confirm(`세션 ${sid}을(를) 삭제하시겠습니까?`)) return;
    try { await invoke('delete_session', { sessionId: sid }); setSelected(null); onRefresh?.(); } catch (e) { alert(`삭제 실패: ${e}`); }
  };
  const doUpload = async (sid: string) => {
    if (!hub.configured) return;
    setUploadProg({ sid, done: 0, total: 100 });
    try {
      await invoke('hub_upload', { url: hub.url, token: hub.token, sessionId: sid });
      setUploadProg({ sid, done: 100, total: 100 });
      setTimeout(() => setUploadProg(null), 800);
      onRefresh?.();
    } catch (e) { setUploadProg(null); alert(`업로드 실패: ${e}`); }
  };
  const doDownload = async (sid: string) => {
    if (!hub.configured) return;
    setDownloadProg(sid);
    try {
      await invoke('hub_download', { url: hub.url, token: hub.token, sessionId: sid });
      setDownloadProg(null);
      onRefresh?.();
    } catch (e) { setDownloadProg(null); alert(`다운로드 실패: ${e}`); }
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
