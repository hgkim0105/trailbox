import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Icon } from '../components/Icon';
import { LOCAL_SESSIONS, REMOTE_SESSIONS, type HubState, type LocalSession, type RemoteSession } from '../data/mock';

type Source = 'local' | 'remote';
type Props = { hub: HubState; active?: boolean; refreshKey?: number };

function fmtDur(s: number) { const m = Math.floor(s / 60), sec = Math.floor(s % 60); return `${m}:${String(sec).padStart(2, '0')}`; }
function fmtSize(b: number) { if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`; if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`; return `${(b / 1e3).toFixed(0)} KB`; }
function fmtNum(n: number) { if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`; if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`; return String(n); }
function relTime(s: string) {
  const d = Date.now() - new Date(s.replace(' ', 'T')).getTime();
  if (d < 60_000) return '방금 전';
  if (d < 3600_000) return `${Math.floor(d / 60_000)}분 전`;
  if (d < 86400_000) return `${Math.floor(d / 3600_000)}시간 전`;
  return `${Math.floor(d / 86400_000)}일 전`;
}

export function SessionsScreen({ hub, active, refreshKey }: Props) {
  const [source, setSource] = useState<Source>('local');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [uploadProg, setUploadProg] = useState<{ sid: string; done: number; total: number } | null>(null);
  const [localSessions, setLocalSessions] = useState<LocalSession[]>(LOCAL_SESSIONS);
  const [remoteSessions, setRemoteSessions] = useState<RemoteSession[]>(REMOTE_SESSIONS);
  const [loading, setLoading] = useState(false);

  const fetchLocal = useCallback(async () => {
    setLoading(true);
    try {
      const list = await invoke<any[]>('list_local_sessions');
      if (Array.isArray(list) && list.length > 0) {
        setLocalSessions(list.map(s => ({
          session_id: s.session_id,
          started: s.started_at ?? '',
          started_rel: s.started_at ? relTime(s.started_at) : '',
          duration: s.duration_seconds ?? 0,
          size: s.size_bytes ?? 0,
          log_lines: s.log_lines ?? 0,
          input_events: s.input_events ?? 0,
          metric_samples: s.metric_samples ?? 0,
          frames: s.screen_frames ?? 0,
          exe: s.exe_path?.split('\\').pop()?.split('/').pop() ?? '',
          device: (s.device as 'PC' | 'Android') ?? 'PC',
          uploaded: false,
          shares: 0,
        })));
      }
    } catch { /* keep mock */ }
    setLoading(false);
  }, []);

  const fetchRemote = useCallback(async () => {
    if (!hub.configured) return;
    setLoading(true);
    try {
      const list = await invoke<any[]>('hub_list_sessions', { url: hub.url, token: '' });
      if (Array.isArray(list) && list.length > 0) {
        setRemoteSessions(list.map(s => ({
          session_id: s.session_id ?? '',
          owner: s.owner ?? '',
          started: s.started_at ?? '',
          duration: s.duration_seconds ?? 0,
          size: s.size_bytes ?? 0,
          has_viewer: s.has_viewer ?? false,
        })));
      }
    } catch { /* keep mock */ }
    setLoading(false);
  }, [hub]);

  useEffect(() => { if (active !== false) fetchLocal(); }, [active, refreshKey]);

  const refresh = () => { if (source === 'local') fetchLocal(); else fetchRemote(); };

  const localFiltered = localSessions.filter(s =>
    !query || s.session_id.toLowerCase().includes(query.toLowerCase()) || s.exe.toLowerCase().includes(query.toLowerCase())
  );
  const remoteFiltered = remoteSessions.filter(s =>
    !query || s.session_id.toLowerCase().includes(query.toLowerCase()) || s.owner.toLowerCase().includes(query.toLowerCase())
  );
  const selectedLocal = localSessions.find(s => s.session_id === selected);

  const doOpenViewer = async (sid: string) => { try { await invoke('open_viewer', { sessionId: sid }); } catch (e) { alert(`뷰어 열기 실패: ${e}`); } };
  const doDelete = async (sid: string) => {
    if (!confirm(`세션 ${sid}을(를) 삭제하시겠습니까?`)) return;
    try { await invoke('delete_session', { sessionId: sid }); setSelected(null); fetchLocal(); } catch (e) { alert(`삭제 실패: ${e}`); }
  };
  const doUpload = (sid: string) => {
    const total = 183; let done = 0;
    setUploadProg({ sid, done, total });
    const iv = setInterval(() => {
      done += 12 + Math.random() * 8;
      if (done >= total) { done = total; clearInterval(iv); setTimeout(() => setUploadProg(null), 800); }
      setUploadProg({ sid, done: Math.min(done, total), total });
    }, 120);
  };

  return (
    <div>
      <div className="section-header">
        <div><h1>세션</h1><p>로컬 · Hub · 업로드 / 공유 / 뷰어</p></div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <div className="tbd-radio-group" style={{ flex: 0 }}>
          <button className={`tbd-radio ${source === 'local' ? 'active' : ''}`} onClick={() => { setSource('local'); setSelected(null); fetchLocal(); }}>
            {Icon.PC()}로컬 · {localSessions.length}
          </button>
          <button className={`tbd-radio ${source === 'remote' ? 'active' : ''}`} onClick={() => { setSource('remote'); setSelected(null); fetchRemote(); }}>
            {Icon.Link()}Hub · {remoteSessions.length}
          </button>
        </div>
        <div style={{ position: 'relative', flex: 1, maxWidth: 220 }}>
          <span style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--subtle)' }}>
            {Icon.Search({ width: 12, height: 12 } as any)}
          </span>
          <input className="tbd-input" placeholder="session_id 검색…" value={query} onChange={e => setQuery(e.target.value)} style={{ paddingLeft: 26 }} />
        </div>
        <button className="tbd-btn tbd-btn--icon" onClick={refresh} disabled={loading}>{Icon.Refresh()}</button>
      </div>

      <div className="tbd-session-table">
        <div className="tbd-session-table__head">
          <span></span><span>Session ID</span>
          <span>{source === 'local' ? 'EXE' : '소유자'}</span>
          <span style={{ textAlign: 'right' }}>길이</span>
          <span style={{ textAlign: 'right' }}>크기</span>
          <span style={{ textAlign: 'right' }}>{source === 'local' ? '프레임' : '시작'}</span>
          <span style={{ textAlign: 'right' }}>{source === 'local' ? '이벤트' : '뷰어'}</span>
          <span></span>
        </div>
        <div className="tbd-session-table__body">
          {source === 'local' ? (
            localFiltered.length > 0 ? localFiltered.map(s => (
              <LocalRow key={s.session_id} s={s} selected={selected === s.session_id} onClick={() => setSelected(s.session_id)} />
            )) : <EmptyRows query={query} source={source} />
          ) : (
            remoteFiltered.length > 0 ? remoteFiltered.map(s => (
              <RemoteRow key={s.session_id} s={s} selected={selected === s.session_id} onClick={() => setSelected(s.session_id)} />
            )) : <EmptyRows query={query} source={source} />
          )}
        </div>
        {selected && (
          <div className="tbd-session-actions">
            <div className="tbd-session-actions__info">
              <span style={{ color: 'var(--muted)', fontSize: 12 }}>선택됨:</span>
              <span className="mono" style={{ fontSize: 12, fontWeight: 500 }}>{selected}</span>
              {source === 'local' && selectedLocal && (
                selectedLocal.uploaded ? <span className="tbd-badge tbd-badge--success"><span className="dot" />업로드됨</span>
                  : <span className="tbd-badge tbd-badge--warning">로컬만</span>
              )}
            </div>
            {source === 'local' ? (
              <>
                <button className="tbd-btn" disabled={!hub.configured || (selectedLocal?.uploaded ?? false)} onClick={() => selected && doUpload(selected)}>{Icon.Upload()}Hub 업로드</button>
                <button className="tbd-btn" disabled={!hub.configured}>{Icon.Share()}공유 링크</button>
                <button className="tbd-btn tbd-btn--danger" onClick={() => selected && doDelete(selected)}>{Icon.Trash()}삭제</button>
                <button className="tbd-btn tbd-btn--primary" onClick={() => selected && doOpenViewer(selected)}>{Icon.Eye()}뷰어 열기</button>
              </>
            ) : (
              <>
                <button className="tbd-btn">{Icon.Download()}다운로드</button>
                <button className="tbd-btn tbd-btn--primary">{Icon.Download()}다운로드 + 뷰어</button>
              </>
            )}
          </div>
        )}
      </div>

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

function LocalRow({ s, selected, onClick }: { s: LocalSession; selected: boolean; onClick: () => void }) {
  return (
    <div className={`tbd-session-row ${selected ? 'selected' : ''}`} onClick={onClick}>
      <span className="tbd-session-row__icon">{s.device === 'Android' ? Icon.Phone() : Icon.PC()}</span>
      <div><div className="tbd-session-row__id">{s.session_id}</div><div className="tbd-session-row__sub">{s.started_rel}</div></div>
      <span className="mono" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.exe}</span>
      <span className="tbd-session-row__num">{fmtDur(s.duration)}</span>
      <span className="tbd-session-row__num">{fmtSize(s.size)}</span>
      <span className="tbd-session-row__num">{fmtNum(s.frames)}</span>
      <span className="tbd-session-row__num">{fmtNum(s.input_events + s.log_lines)}</span>
      <span style={{ textAlign: 'right' }}>{s.shares > 0 && <span className="tbd-badge tbd-badge--accent">{s.shares}</span>}</span>
    </div>
  );
}

function RemoteRow({ s, selected, onClick }: { s: RemoteSession; selected: boolean; onClick: () => void }) {
  const time = s.started.split(' ')[1]?.slice(0, 5) ?? '';
  return (
    <div className={`tbd-session-row ${selected ? 'selected' : ''}`} onClick={onClick}>
      <span className="tbd-session-row__icon">{Icon.Link()}</span>
      <div><div className="tbd-session-row__id">{s.session_id}</div><div className="tbd-session-row__sub">{s.started.split(' ')[0]}</div></div>
      <span style={{ fontSize: 12 }}>{s.owner}</span>
      <span className="tbd-session-row__num">{fmtDur(s.duration)}</span>
      <span className="tbd-session-row__num">{fmtSize(s.size)}</span>
      <span className="tbd-session-row__num">{time}</span>
      <span style={{ textAlign: 'right' }}>{s.has_viewer && <span className="tbd-badge tbd-badge--success">{Icon.Check({ width: 10, height: 10 } as any)}</span>}</span>
      <span />
    </div>
  );
}

function EmptyRows({ query, source }: { query: string; source: Source }) {
  return (
    <div className="tbd-empty">
      {Icon.Sessions({ width: 28, height: 28, style: { opacity: 0.4 } } as any)}
      <h2>표시할 세션이 없습니다</h2>
      <p>{query ? '검색어를 조정해보세요' : source === 'local' ? '캡처를 시작하면 여기에 나타납니다' : 'Hub에 업로드된 세션이 없습니다'}</p>
    </div>
  );
}
