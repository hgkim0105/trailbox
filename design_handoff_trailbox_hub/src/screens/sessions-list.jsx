// ============================================================
// Sessions list — Cards / Table / Compact layouts
// ============================================================
const { useState: useStateSL, useMemo: useMemoSL } = React;

function SessionsListScreen({ setRoute, openSession, layout, sessions, user }) {
  const I = window.Icons;
  const { formatDuration, formatSize, formatNumber, SessionThumb } = window;

  const [q, setQ] = useStateSL('');
  const [device, setDevice] = useStateSL('all'); // all | PC | Android
  const [scope, setScope] = useStateSL(user.role === 'admin' ? 'all' : 'mine');

  const filtered = useMemoSL(() => {
    return sessions.filter(s => {
      if (scope === 'mine' && s.owner !== user.username) return false;
      if (device !== 'all' && s.device !== device) return false;
      if (q && !(s.session_id.includes(q) || s.exe_path.toLowerCase().includes(q.toLowerCase())
        || (s.tags || []).some(t => t.toLowerCase().includes(q.toLowerCase())))) return false;
      return true;
    });
  }, [sessions, q, device, scope, user.username]);

  // ── Aggregate stats ──
  const stats = useMemoSL(() => {
    const total = filtered.length;
    const totalDur = filtered.reduce((a, s) => a + s.duration_seconds, 0);
    const totalSize = filtered.reduce((a, s) => a + s.size_bytes, 0);
    const shares = filtered.reduce((a, s) => a + (s.shares?.length || 0), 0);
    return { total, totalDur, totalSize, shares };
  }, [filtered]);

  return (
    <div className="content">
      <div className="page-header">
        <div>
          <h1>세션</h1>
          <p>{user.role === 'admin' ? '전체 사용자' : '본인'}의 캡처 세션 · 업로드, 공유, AI 분석</p>
        </div>
        <div className="page-header__actions">
          <window.Button icon={<I.Download />}>모두 zip</window.Button>
          <window.Button variant="primary" icon={<I.Plus />}>업로드</window.Button>
        </div>
      </div>

      <div className="stat-row">
        <div className="stat"><div className="stat__label">세션</div><div className="stat__value">{stats.total}</div><div className="stat__delta stat__delta--up">+3 이번 주</div></div>
        <div className="stat"><div className="stat__label">총 길이</div><div className="stat__value">{formatDuration(stats.totalDur)}</div><div className="stat__delta">평균 {formatDuration(stats.totalDur / Math.max(1, stats.total))}</div></div>
        <div className="stat"><div className="stat__label">스토리지</div><div className="stat__value">{formatSize(stats.totalSize)}</div><div className="stat__delta">{(stats.totalSize / 4_096 / 1024 / 1024 * 100).toFixed(0)}% / 4 GB quota</div></div>
        <div className="stat"><div className="stat__label">활성 공유</div><div className="stat__value">{stats.shares}</div><div className="stat__delta">14일 후 만료</div></div>
      </div>

      <div className="sessions-toolbar">
        <div className="input-wrap" style={{ flex: 1, maxWidth: 360 }}>
          <I.Search className="icon-left" />
          <input className="input" placeholder="세션 ID · 실행파일 · 태그 검색" value={q} onChange={e => setQ(e.target.value)} />
        </div>

        {user.role === 'admin' && (
          <window.Segmented
            value={scope}
            onChange={setScope}
            options={[
              { value: 'all', label: '전체' },
              { value: 'mine', label: '내 세션' },
            ]}
          />
        )}

        <window.Segmented
          value={device}
          onChange={setDevice}
          options={[
            { value: 'all', label: '모두' },
            { value: 'PC', label: 'PC', icon: <I.PC /> },
            { value: 'Android', label: 'Android', icon: <I.Phone /> },
          ]}
        />

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <window.Button icon={<I.Filter />} size="sm" variant="ghost">정렬: 최신순</window.Button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="empty">
          <I.Sessions width={32} height={32} style={{ opacity: 0.4 }} />
          <h3>표시할 세션이 없습니다</h3>
          <p>Trailbox 클라이언트에서 업로드하거나 필터를 조정해보세요.</p>
        </div>
      ) : layout === 'cards' ? (
        <div className="sessions-grid">
          {filtered.map(s => (
            <SessionCard key={s.session_id} session={s} onClick={() => openSession(s.session_id)} />
          ))}
        </div>
      ) : layout === 'table' ? (
        <SessionTable sessions={filtered} openSession={openSession} showOwner={user.role === 'admin' && scope === 'all'} />
      ) : (
        <SessionCompact sessions={filtered} openSession={openSession} />
      )}
    </div>
  );
}

// ── Card variant ──
function SessionCard({ session, onClick }) {
  const I = window.Icons;
  const { formatNumber, SessionThumb } = window;
  return (
    <a href="#" onClick={(e) => { e.preventDefault(); onClick(); }} className="session-card">
      <SessionThumb session={session} />
      <div className="session-card__body">
        <div className="session-card__title">
          <span style={{
            fontFamily: 'Geist Mono', fontSize: 12.5, fontWeight: 600,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
          }}>{session.session_id}</span>
          {session.shares.length > 0 && (
            <window.Badge tone="accent"><I.Link width={11} height={11} />{session.shares.length}</window.Badge>
          )}
        </div>
        <div className="session-card__meta">
          {session.device === 'PC' ? <I.PC width={12} height={12} /> : <I.Phone width={12} height={12} />}
          <span>{session.device_label}</span>
          <span className="sep">·</span>
          <span>{session.started_relative}</span>
        </div>
        {session.tags && session.tags.length > 0 && (
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {session.tags.slice(0, 3).map(t => (
              <window.Badge key={t} tone="outline">{t}</window.Badge>
            ))}
          </div>
        )}
        <div className="session-card__counts">
          <div className="metric-pill">
            <div className="metric-pill__value">{formatNumber(session.log_lines)}</div>
            <div className="metric-pill__label">Logs</div>
          </div>
          <div className="metric-pill">
            <div className="metric-pill__value">{formatNumber(session.input_events)}</div>
            <div className="metric-pill__label">Inputs</div>
          </div>
          <div className="metric-pill">
            <div className="metric-pill__value">{formatNumber(session.metric_samples)}</div>
            <div className="metric-pill__label">Samples</div>
          </div>
        </div>
      </div>
    </a>
  );
}

// ── Table variant ──
function SessionTable({ sessions, openSession, showOwner }) {
  const I = window.Icons;
  const { formatDuration, formatSize, formatNumber } = window;
  return (
    <div className="card card__body--compact">
      <table className="table">
        <thead>
          <tr>
            <th style={{ width: 50 }}></th>
            <th>Session</th>
            <th>시작</th>
            <th>길이</th>
            <th>크기</th>
            <th>이벤트</th>
            {showOwner && <th>소유자</th>}
            <th>공유</th>
            <th style={{ width: 1 }}></th>
          </tr>
        </thead>
        <tbody>
          {sessions.map(s => (
            <tr key={s.session_id} onClick={() => openSession(s.session_id)} style={{ cursor: 'pointer' }}>
              <td>
                <div style={{ width: 40, height: 26, borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
                  <div style={{
                    position: 'absolute', inset: 0,
                    background: `linear-gradient(135deg, oklch(0.35 0.14 ${s.thumb_kind === 'mobile' ? 150 : s.thumb_kind === 'code' ? 220 : 280}), oklch(0.22 0.08 200))`,
                  }} />
                  <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}>
                    {s.device === 'PC' ? <I.PC width={11} height={11} /> : <I.Phone width={11} height={11} />}
                  </div>
                </div>
              </td>
              <td>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <code style={{ fontWeight: 500 }}>{s.session_id}</code>
                  <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>{s.exe_path.split(/[\\/]/).pop()}</div>
                </div>
              </td>
              <td>
                <div style={{ display: 'flex', flexDirection: 'column', fontSize: 12 }}>
                  <span>{s.started_relative}</span>
                  <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{s.started_at}</span>
                </div>
              </td>
              <td><span className="mono">{formatDuration(s.duration_seconds)}</span></td>
              <td><span className="mono">{formatSize(s.size_bytes)}</span></td>
              <td>
                <div style={{ display: 'flex', gap: 6, fontSize: 11.5, color: 'var(--muted)' }}>
                  <span title="logs"><I.Document width={11} height={11} style={{ verticalAlign: -2 }} /> {formatNumber(s.log_lines)}</span>
                  <span title="inputs"><I.Mouse width={11} height={11} style={{ verticalAlign: -2 }} /> {formatNumber(s.input_events)}</span>
                  <span title="samples"><I.Cpu width={11} height={11} style={{ verticalAlign: -2 }} /> {formatNumber(s.metric_samples)}</span>
                </div>
              </td>
              {showOwner && (
                <td><div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><window.Avatar name={s.owner} size="sm" />{s.owner}</div></td>
              )}
              <td>
                {s.shares.length > 0
                  ? <window.Badge tone="accent"><I.Link width={11} height={11} />{s.shares.length}</window.Badge>
                  : <span style={{ color: 'var(--subtle)', fontSize: 12 }}>—</span>}
              </td>
              <td onClick={e => e.stopPropagation()}>
                <div className="row-actions">
                  <window.Button size="sm" variant="ghost" iconOnly icon={<I.Download />} title="zip" />
                  <window.Button size="sm" variant="ghost" iconOnly icon={<I.Trash />} title="삭제" className="btn--danger" />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Compact variant ──
function SessionCompact({ sessions, openSession }) {
  const I = window.Icons;
  const { formatDuration, formatNumber } = window;
  return (
    <div className="sessions-compact">
      {sessions.map(s => (
        <a key={s.session_id} href="#" onClick={(e) => { e.preventDefault(); openSession(s.session_id); }} className="sessions-compact__row">
          <div className="sessions-compact__thumb">
            <div style={{
              position: 'absolute', inset: 0,
              background: `linear-gradient(135deg, oklch(0.35 0.14 ${s.thumb_kind === 'mobile' ? 150 : s.thumb_kind === 'code' ? 220 : 280}), oklch(0.22 0.08 200))`,
            }} />
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', opacity: 0.85 }}>
              {s.device === 'PC' ? <I.PC width={9} height={9} /> : <I.Phone width={9} height={9} />}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
            <span className="sessions-compact__id">{s.session_id}</span>
            <span className="sessions-compact__meta">
              <span>{s.device_label}</span>
              <span className="sep">·</span>
              <span>{s.started_relative}</span>
              {s.tags?.[0] && (<><span className="sep">·</span><window.Badge tone="outline">{s.tags[0]}</window.Badge></>)}
            </span>
          </div>
          <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>{formatDuration(s.duration_seconds)}</span>
          <span style={{ display: 'flex', gap: 8, fontSize: 11, color: 'var(--muted)' }}>
            <span><I.Document width={10} height={10} style={{ verticalAlign: -1 }} /> {formatNumber(s.log_lines)}</span>
            <span><I.Mouse width={10} height={10} style={{ verticalAlign: -1 }} /> {formatNumber(s.input_events)}</span>
          </span>
          {s.shares.length > 0
            ? <window.Badge tone="accent"><I.Link width={11} height={11} />{s.shares.length}</window.Badge>
            : <span style={{ width: 28 }} />}
        </a>
      ))}
    </div>
  );
}

window.SessionsListScreen = SessionsListScreen;
