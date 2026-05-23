import { useState } from 'react';
import { Icon } from '../components/Icon';
import { LOCAL_SESSIONS, REMOTE_SESSIONS, type HubState, type LocalSession, type RemoteSession } from '../data/mock';

type Source = 'local' | 'remote';
type Props = { hub: HubState };

function fmtDur(s: number) {
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}
function fmtSize(b: number) {
  if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`;
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  return `${(b / 1e3).toFixed(0)} KB`;
}
function fmtNum(n: number) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
}

export function SessionsScreen({ hub }: Props) {
  const [source, setSource] = useState<Source>('local');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [uploadProg, setUploadProg] = useState<{ sid: string; done: number; total: number } | null>(null);

  const localFiltered = LOCAL_SESSIONS.filter(s =>
    !query || s.session_id.toLowerCase().includes(query.toLowerCase()) || s.exe.toLowerCase().includes(query.toLowerCase())
  );
  const remoteFiltered = REMOTE_SESSIONS.filter(s =>
    !query || s.session_id.toLowerCase().includes(query.toLowerCase()) || s.owner.toLowerCase().includes(query.toLowerCase())
  );

  const selectedLocal = LOCAL_SESSIONS.find(s => s.session_id === selected);

  const simulateUpload = (sid: string) => {
    const total = 183;
    let done = 0;
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
        <div>
          <h1>세션</h1>
          <p>로컬 · Hub · 업로드 / 공유 / 뷰어</p>
        </div>
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <div className="tbd-radio-group" style={{ flex: 0 }}>
          <button className={`tbd-radio ${source === 'local' ? 'active' : ''}`} onClick={() => { setSource('local'); setSelected(null); }}>
            {Icon.PC()}로컬 · {LOCAL_SESSIONS.length}
          </button>
          <button className={`tbd-radio ${source === 'remote' ? 'active' : ''}`} onClick={() => { setSource('remote'); setSelected(null); }}>
            {Icon.Link()}Hub · {REMOTE_SESSIONS.length}
          </button>
        </div>
        <div style={{ position: 'relative', flex: 1, maxWidth: 220 }}>
          <span style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--subtle)' }}>
            {Icon.Search({ width: 12, height: 12 } as any)}
          </span>
          <input className="tbd-input" placeholder="session_id 검색…" value={query} onChange={e => setQuery(e.target.value)} style={{ paddingLeft: 26 }} />
        </div>
        <button className="tbd-btn tbd-btn--icon">{Icon.Refresh()}</button>
      </div>

      {/* Table */}
      <div className="tbd-session-table">
        <div className="tbd-session-table__head">
          <span></span>
          <span>Session ID</span>
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

        {/* Action bar */}
        {selected && (
          <div className="tbd-session-actions">
            <div className="tbd-session-actions__info">
              <span style={{ color: 'var(--muted)', fontSize: 12 }}>선택됨:</span>
              <span className="mono" style={{ fontSize: 12, fontWeight: 500 }}>{selected}</span>
              {source === 'local' && selectedLocal && (
                selectedLocal.uploaded
                  ? <span className="tbd-badge tbd-badge--success"><span className="dot" />업로드됨</span>
                  : <span className="tbd-badge tbd-badge--warning">로컬만</span>
              )}
            </div>
            {source === 'local' ? (
              <>
                <button className="tbd-btn" disabled={!hub.configured || (selectedLocal?.uploaded ?? false)} onClick={() => selected && simulateUpload(selected)}>
                  {Icon.Upload()}Hub 업로드
                </button>
                <button className="tbd-btn" disabled={!hub.configured}>{Icon.Share()}공유 링크</button>
                <button className="tbd-btn tbd-btn--danger">{Icon.Trash()}삭제</button>
                <button className="tbd-btn tbd-btn--primary">{Icon.Eye()}뷰어 열기</button>
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

      {/* Upload progress */}
      {uploadProg && (
        <div className="tbd-upload-pop">
          <div className="tbd-upload-pop__head">
            {Icon.Upload()}
            <span className="tbd-upload-pop__title">Hub 업로드 중…</span>
            <span className="tbd-upload-pop__size">{Math.round(uploadProg.done)} / {uploadProg.total} MB</span>
          </div>
          <div className="tbd-progress">
            <div className="tbd-progress__fill" style={{ width: `${(uploadProg.done / uploadProg.total) * 100}%` }} />
          </div>
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
      <div>
        <div className="tbd-session-row__id">{s.session_id}</div>
        <div className="tbd-session-row__sub">{s.started_rel}</div>
      </div>
      <span className="mono" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.exe}</span>
      <span className="tbd-session-row__num">{fmtDur(s.duration)}</span>
      <span className="tbd-session-row__num">{fmtSize(s.size)}</span>
      <span className="tbd-session-row__num">{fmtNum(s.frames)}</span>
      <span className="tbd-session-row__num">{fmtNum(s.input_events + s.log_lines)}</span>
      <span style={{ textAlign: 'right' }}>
        {s.shares > 0 && <span className="tbd-badge tbd-badge--accent">{s.shares}</span>}
      </span>
    </div>
  );
}

function RemoteRow({ s, selected, onClick }: { s: RemoteSession; selected: boolean; onClick: () => void }) {
  const time = s.started.split(' ')[1]?.slice(0, 5) ?? '';
  return (
    <div className={`tbd-session-row ${selected ? 'selected' : ''}`} onClick={onClick}>
      <span className="tbd-session-row__icon">{Icon.Link()}</span>
      <div>
        <div className="tbd-session-row__id">{s.session_id}</div>
        <div className="tbd-session-row__sub">{s.started.split(' ')[0]}</div>
      </div>
      <span style={{ fontSize: 12 }}>{s.owner}</span>
      <span className="tbd-session-row__num">{fmtDur(s.duration)}</span>
      <span className="tbd-session-row__num">{fmtSize(s.size)}</span>
      <span className="tbd-session-row__num">{time}</span>
      <span style={{ textAlign: 'right' }}>
        {s.has_viewer && <span className="tbd-badge tbd-badge--success">{Icon.Check({ width: 10, height: 10 } as any)}</span>}
      </span>
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
