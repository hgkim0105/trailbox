// ============================================================
// Sessions screen — local + remote tabs
// merges session_picker + remote_session_picker
// ============================================================
const { useState: useStateSes, useMemo: useMemoSes } = React;

function TbdSessionsScreen({ hub }) {
  const D = window.TrailboxDesktopData;
  const I = window.Icons;

  const [source, setSource] = useStateSes('local'); // local | remote
  const [q, setQ] = useStateSes('');
  const [selected, setSelected] = useStateSes(D.DESKTOP_SESSIONS[0].session_id);
  const [uploadProgress, setUploadProgress] = useStateSes(null); // { sid, done, total }

  const localSessions = useMemoSes(() => {
    return D.DESKTOP_SESSIONS.filter(s =>
      !q || s.session_id.includes(q) || s.exe.toLowerCase().includes(q.toLowerCase())
    );
  }, [q]);

  const remoteSessions = useMemoSes(() => {
    return D.DESKTOP_REMOTE_SESSIONS.filter(s =>
      !q || s.session_id.includes(q) || (s.owner && s.owner.includes(q))
    );
  }, [q]);

  const sessions = source === 'local' ? localSessions : remoteSessions;
  const selectedSession = sessions.find(s => s.session_id === selected) || sessions[0];

  const startUpload = (sid) => {
    const total = D.DESKTOP_SESSIONS.find(s => s.session_id === sid)?.size || 100_000_000;
    setUploadProgress({ sid, done: 0, total });
    const step = () => {
      setUploadProgress(p => {
        if (!p) return null;
        const next = p.done + Math.min(total / 30, total - p.done);
        if (next >= total) {
          setTimeout(() => setUploadProgress(null), 500);
          return { ...p, done: total };
        }
        setTimeout(step, 120);
        return { ...p, done: next };
      });
    };
    setTimeout(step, 200);
  };

  return (
    <>
      <div className="tbd-section-head">
        <h2>세션</h2>
        <div className="tbd-radio-group" style={{ marginLeft: 16, marginBottom: 0 }}>
          <button className={`tbd-radio ${source === 'local' ? 'active' : ''}`} onClick={() => setSource('local')}>
            <I.PC /> 로컬 · {D.DESKTOP_SESSIONS.length}
          </button>
          <button className={`tbd-radio ${source === 'remote' ? 'active' : ''}`} onClick={() => setSource('remote')}>
            <I.Link /> Hub · {D.DESKTOP_REMOTE_SESSIONS.length}
          </button>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ position: 'relative' }}>
            <I.Search width={12} height={12} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--subtle)' }} />
            <input className="tbd-input" placeholder="session_id 검색…" value={q} onChange={e => setQ(e.target.value)} style={{ paddingLeft: 24, width: 220 }} />
          </div>
          <button className="tbd-btn tbd-btn--sm"><I.Search /> 새로고침</button>
        </div>
      </div>

      <div className="tbd-sessions">
        <div className="tbd-session-table">
          <div className="tbd-session-table__head">
            <div></div>
            <div>Session ID</div>
            <div>{source === 'local' ? 'EXE' : '소유자'}</div>
            <div style={{ textAlign: 'right' }}>길이</div>
            <div style={{ textAlign: 'right' }}>크기</div>
            <div style={{ textAlign: 'right' }}>{source === 'local' ? '프레임' : '시작'}</div>
            <div style={{ textAlign: 'right' }}>{source === 'local' ? '이벤트' : '뷰어'}</div>
            <div></div>
          </div>
          <div className="tbd-session-table__body">
            {sessions.map(s => (
              <SessionRow key={s.session_id} session={s} source={source} selected={selected === s.session_id} onClick={() => setSelected(s.session_id)} />
            ))}
            {sessions.length === 0 && (
              <div className="tbd-empty">
                <I.Sessions width={28} height={28} style={{ opacity: 0.4 }} />
                <div style={{ marginTop: 10, fontWeight: 500 }}>표시할 세션이 없습니다</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>{q ? '검색어를 조정해보세요' : '캡처를 시작하면 여기에 나타납니다'}</div>
              </div>
            )}
          </div>

          {/* Bottom action bar */}
          <div className="tbd-session-actions">
            {selectedSession ? (
              <>
                <div className="tbd-session-actions__info">
                  선택됨: <strong className="tbd-mono">{selectedSession.session_id}</strong>
                  {source === 'local' && selectedSession.uploaded && (
                    <span className="tbd-badge tbd-badge--success" style={{ marginLeft: 8 }}><span className="dot" />업로드됨</span>
                  )}
                  {source === 'local' && !selectedSession.uploaded && (
                    <span className="tbd-badge tbd-badge--warning" style={{ marginLeft: 8 }}><span className="dot" />로컬만</span>
                  )}
                </div>
                {source === 'local' ? (
                  <>
                    <button className="tbd-btn tbd-btn--sm" disabled={!hub.configured || selectedSession.uploaded} onClick={() => startUpload(selectedSession.session_id)}>
                      <I.Download style={{ transform: 'rotate(180deg)' }} /> Hub 업로드
                    </button>
                    <button className="tbd-btn tbd-btn--sm" disabled={!hub.configured}>
                      <I.Share /> 공유 링크
                    </button>
                    <button className="tbd-btn tbd-btn--sm tbd-btn--danger"><I.Trash /> 삭제</button>
                    <a className="tbd-btn tbd-btn--sm tbd-btn--primary" href="Session Viewer.html" target="_top" rel="noopener">
                      <I.Eye /> 뷰어 열기
                    </a>
                  </>
                ) : (
                  <>
                    <button className="tbd-btn tbd-btn--sm">
                      <I.Download /> 다운로드
                    </button>
                    <button className="tbd-btn tbd-btn--sm tbd-btn--primary">
                      <I.Eye /> 다운로드 + 뷰어 열기
                    </button>
                  </>
                )}
              </>
            ) : (
              <div className="tbd-session-actions__info">세션을 선택하세요</div>
            )}
          </div>
        </div>
      </div>

      {/* Upload progress popover */}
      {uploadProgress && (
        <div style={{
          position: 'absolute',
          bottom: 16, right: 20,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 8, boxShadow: 'var(--shadow-pop)',
          padding: 12, width: 320, zIndex: 30,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <I.Download style={{ transform: 'rotate(180deg)', color: 'var(--accent)' }} />
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>Hub 업로드 중…</span>
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)', fontFamily: 'Geist Mono' }}>
              {(uploadProgress.done / (1024*1024)).toFixed(1)} / {(uploadProgress.total / (1024*1024)).toFixed(1)} MB
            </span>
          </div>
          <div className="tbd-progress">
            <div className="tbd-progress__fill" style={{ width: `${(uploadProgress.done / uploadProgress.total) * 100}%` }} />
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'Geist Mono', marginTop: 4 }}>
            {uploadProgress.sid}
          </div>
        </div>
      )}
    </>
  );
}

function SessionRow({ session, source, selected, onClick }) {
  const I = window.Icons;
  return (
    <div className={`tbd-session-row ${selected ? 'selected' : ''}`} onClick={onClick}>
      <div className="tbd-session-row__dev">
        {source === 'local' ? (session.device === 'PC' ? <I.PC width={12} height={12} /> : <I.Phone width={12} height={12} />) : <I.Link width={12} height={12} />}
      </div>
      <div>
        <div className="tbd-session-row__id">{session.session_id}</div>
        <div className="tbd-session-row__exe">{session.started_rel || session.started}</div>
      </div>
      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>
        {source === 'local'
          ? <span className="tbd-mono" style={{ color: 'var(--fg-2)', fontSize: 11.5 }}>{session.exe}</span>
          : <span style={{ color: 'var(--fg-2)' }}>{session.owner}</span>}
      </div>
      <div className="tbd-session-row__num">{formatDur(session.duration)}</div>
      <div className="tbd-session-row__num">{formatSize(session.size)}</div>
      <div className="tbd-session-row__num">
        {source === 'local'
          ? session.frames?.toLocaleString()
          : <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>{(session.started || '').slice(11, 16)}</span>}
      </div>
      <div className="tbd-session-row__num">
        {source === 'local'
          ? <>
              <span>{((session.log_lines || 0) + (session.input_events || 0)).toLocaleString()}</span>
            </>
          : (session.has_viewer ? <I.Check width={14} height={14} style={{ color: 'var(--success)' }} /> : '—')}
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        {source === 'local' && session.shares > 0 && (
          <span className="tbd-badge tbd-badge--accent"><I.Link width={10} height={10} />{session.shares}</span>
        )}
        {source === 'local' && session.uploaded && session.shares === 0 && (
          <I.Check width={12} height={12} style={{ color: 'var(--muted)' }} />
        )}
      </div>
    </div>
  );
}

function formatDur(s) {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function formatSize(bytes) {
  if (!bytes) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(0)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

window.TbdSessionsScreen = TbdSessionsScreen;
