// ============================================================
// Admin screens — Users, Settings, Audit
// ============================================================
const { useState: useStateAdm } = React;

// ── Users ──
function AdminUsersScreen() {
  const I = window.Icons;
  const T = window.TrailboxData;
  const [users, setUsers] = useStateAdm(T.USERS);
  const [pending, setPending] = useStateAdm(T.PENDING_USERS);
  const [tempPw, setTempPw] = useStateAdm(null);
  const [copied, copy] = window.useCopy();

  const approve = (id) => {
    const u = pending.find(x => x.id === id);
    setPending(pending.filter(x => x.id !== id));
    setUsers([...users, { ...u, role: 'user', status: 'active', approved_at: '방금' }]);
  };
  const disable = (id) => setUsers(users.map(u => u.id === id ? { ...u, status: 'disabled' } : u));
  const enable = (id) => setUsers(users.map(u => u.id === id ? { ...u, status: 'active' } : u));
  const reject = (id) => setPending(pending.filter(x => x.id !== id));
  const togglRole = (id) => setUsers(users.map(u => u.id === id ? { ...u, role: u.role === 'admin' ? 'user' : 'admin' } : u));
  const resetPw = (username) => {
    const pw = Math.random().toString(36).slice(2, 14);
    setTempPw({ user: username, pw });
  };

  return (
    <div className="content">
      <div className="page-header">
        <div>
          <h1>사용자 관리</h1>
          <p>승인 대기 · 권한 · 상태 · 토큰</p>
        </div>
        <div className="page-header__actions">
          <window.Button icon={<I.Plus />}>사용자 초대</window.Button>
        </div>
      </div>

      {tempPw && (
        <window.Flash tone="success" icon={<I.Key />} title={`임시 비밀번호 발급됨 — ${tempPw.user}`}>
          아래 값은 <strong>이 페이지에서만 한 번 표시</strong>됩니다. 안전한 채널로 본인에게 전달하세요.
          <div className="code-block" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ flex: 1 }}>{tempPw.pw}</span>
            <window.Button size="sm" variant="ghost" icon={<I.Copy />} onClick={() => copy(tempPw.pw, 'pw')}>
              {copied === 'pw' ? '복사됨' : '복사'}
            </window.Button>
          </div>
        </window.Flash>
      )}

      {pending.length > 0 && (
        <div className="card" style={{ marginBottom: 18, borderColor: 'color-mix(in oklch, var(--warning) 30%, var(--border))' }}>
          <div className="card__header" style={{ background: 'var(--warning-soft)' }}>
            <h3 className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <I.Clock width={14} height={14} /> 승인 대기 ({pending.length})
            </h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
              <span>자동 승인 OFF</span>
              <window.Button size="sm" variant="ghost">설정 변경</window.Button>
            </div>
          </div>
          <table className="table">
            <thead><tr><th>Username</th><th>Email</th><th>가입 시각</th><th></th></tr></thead>
            <tbody>
              {pending.map(u => (
                <tr key={u.id}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <window.Avatar name={u.username} size="sm" />{u.username}
                    </div>
                  </td>
                  <td>{u.email || <span style={{ color: 'var(--subtle)' }}>—</span>}</td>
                  <td className="mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>{u.created_at}</td>
                  <td className="row-actions">
                    <window.Button size="sm" variant="primary" icon={<I.Check />} onClick={() => approve(u.id)}>승인</window.Button>
                    <window.Button size="sm" variant="ghost" className="btn--danger" onClick={() => reject(u.id)}>거절</window.Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <div className="card__header">
          <h3 className="card__title">전체 사용자 ({users.length})</h3>
          <div className="input-wrap" style={{ maxWidth: 240 }}>
            <I.Search className="icon-left" />
            <input className="input" placeholder="username 검색" />
          </div>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Status</th>
              <th>가입</th>
              <th>승인</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id}>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <window.Avatar name={u.username} size="sm" />
                    <div>
                      <div style={{ fontWeight: 500 }}>{u.username} {u.username === 'hyun' && <span style={{ color: 'var(--muted)', fontWeight: 400 }}>· 나</span>}</div>
                      <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>{u.email || '—'}</div>
                    </div>
                  </div>
                </td>
                <td>
                  {u.role === 'admin'
                    ? <window.Badge tone="accent">admin</window.Badge>
                    : <window.Badge tone="neutral">user</window.Badge>}
                </td>
                <td>
                  {u.status === 'active'
                    ? <window.Badge tone="success" dot>active</window.Badge>
                    : <window.Badge tone="danger" dot>disabled</window.Badge>}
                </td>
                <td className="mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>{u.created_at}</td>
                <td className="mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>{u.approved_at || '—'}</td>
                <td className="row-actions">
                  {u.username !== 'hyun' && (
                    <>
                      {u.status === 'active'
                        ? <window.Button size="sm" variant="ghost" className="btn--danger" onClick={() => disable(u.id)}>disable</window.Button>
                        : <window.Button size="sm" variant="ghost" onClick={() => enable(u.id)}>enable</window.Button>}
                      <window.Button size="sm" variant="ghost" onClick={() => togglRole(u.id)}>
                        {u.role === 'admin' ? 'demote' : 'promote'}
                      </window.Button>
                      <window.Button size="sm" variant="ghost" onClick={() => resetPw(u.username)}>reset pw</window.Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Settings ──
function AdminSettingsScreen() {
  const I = window.Icons;
  const T = window.TrailboxData;
  const [settings, setSettings] = useStateAdm(T.HUB_SETTINGS);
  const [saved, setSaved] = useStateAdm(false);

  const update = (k, v) => {
    setSettings(s => ({ ...s, [k]: v }));
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  };

  const Toggle = ({ k, title, desc }) => (
    <div className="toggle-row">
      <div className="toggle-row__main">
        <div className="toggle-row__title">{title}</div>
        <div className="toggle-row__desc">{desc}</div>
      </div>
      <div className={`toggle ${settings[k] ? 'on' : ''}`} onClick={() => update(k, !settings[k])} role="switch" aria-checked={settings[k]} />
    </div>
  );

  const Numeric = ({ k, title, desc, unit }) => (
    <div className="toggle-row">
      <div className="toggle-row__main">
        <div className="toggle-row__title">{title}</div>
        <div className="toggle-row__desc">{desc}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <input
          className="input"
          type="number"
          value={settings[k]}
          onChange={e => update(k, Number(e.target.value))}
          style={{ width: 90, textAlign: 'right' }}
        />
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>{unit}</span>
      </div>
    </div>
  );

  return (
    <div className="content">
      <div className="page-header">
        <div>
          <h1>시스템 설정</h1>
          <p>Hub 동작 정책 — 변경은 즉시 반영됩니다</p>
        </div>
        {saved && <window.Badge tone="success" dot>저장됨</window.Badge>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'flex-start' }}>
        <div className="card">
          <div className="card__header"><h3 className="card__title">계정 정책</h3></div>
          <div className="card__body" style={{ paddingTop: 0 }}>
            <Toggle k="auto_approve_registration"
              title="회원가입 자동 승인"
              desc="신규 가입자가 곧바로 active 상태가 됩니다. 끄면 관리자 승인이 필요합니다." />
            <Toggle k="require_strong_password"
              title="강한 비밀번호 요구"
              desc="최소 12자, 대소문자·숫자·특수문자 1개 이상." />
          </div>
        </div>

        <div className="card">
          <div className="card__header"><h3 className="card__title">공유 정책</h3></div>
          <div className="card__body" style={{ paddingTop: 0 }}>
            <Toggle k="allow_public_share"
              title="공개 공유 링크 허용"
              desc="끄면 모든 공유 링크가 로그인 사용자만 볼 수 있게 됩니다." />
            <Numeric k="share_expiry_days"
              title="공유 링크 기본 만료"
              desc="발급 시 기본 적용되는 TTL. 발급 시점에 개별 변경 가능."
              unit="일" />
          </div>
        </div>

        <div className="card">
          <div className="card__header"><h3 className="card__title">저장 · 보관</h3></div>
          <div className="card__body" style={{ paddingTop: 0 }}>
            <Numeric k="retention_days"
              title="세션 자동 보관 기간"
              desc="이 기간보다 오래된 세션은 자동 삭제됩니다. 0이면 비활성화."
              unit="일" />
            <Numeric k="max_session_mb"
              title="세션 최대 크기"
              desc="이 크기를 초과하면 업로드 거부."
              unit="MB" />
            <Numeric k="upload_chunk_mb"
              title="업로드 청크 크기"
              desc="64MB 이상 파일은 청크 업로드(재개 지원)를 사용합니다."
              unit="MB" />
          </div>
        </div>

        <div className="card">
          <div className="card__header"><h3 className="card__title">현재 환경값 (read-only)</h3></div>
          <div className="card__body">
            <dl className="kv" style={{ gridTemplateColumns: '180px 1fr', fontSize: 12.5 }}>
              <dt>Hub 버전</dt><dd className="mono">v0.4.2</dd>
              <dt>DB</dt><dd className="mono">SQLite · 14.2 MB · WAL</dd>
              <dt>Storage</dt><dd className="mono">/data/sessions · 18.4 GB free</dd>
              <dt>Bind</dt><dd className="mono">0.0.0.0:8765</dd>
              <dt>TLS</dt><dd>Caddy reverse proxy</dd>
              <dt>Python</dt><dd className="mono">3.12.3</dd>
              <dt>Uptime</dt><dd>14d 6h 22m</dd>
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Audit ──
function AdminAuditScreen() {
  const I = window.Icons;
  const T = window.TrailboxData;
  const [filter, setFilter] = useStateAdm('all');
  const [q, setQ] = useStateAdm('');

  const filtered = T.AUDIT_ENTRIES.filter(e => {
    if (filter === 'auth' && !e.action.startsWith('auth.')) return false;
    if (filter === 'session' && !e.action.startsWith('session.')) return false;
    if (filter === 'user' && !e.action.startsWith('user.')) return false;
    if (filter === 'settings' && !e.action.startsWith('settings.')) return false;
    if (q) {
      const s = `${e.actor} ${e.action} ${e.target} ${e.detail}`.toLowerCase();
      if (!s.includes(q.toLowerCase())) return false;
    }
    return true;
  });

  const actionTone = (action) => {
    if (action.startsWith('auth.login.fail')) return 'danger';
    if (action.startsWith('session.delete') || action.includes('.disable') || action.includes('.revoke')) return 'warning';
    if (action.startsWith('user.approve') || action.startsWith('session.upload')) return 'success';
    if (action.startsWith('session.share')) return 'accent';
    return 'neutral';
  };

  return (
    <div className="content">
      <div className="page-header">
        <div>
          <h1>감사 로그</h1>
          <p>모든 보안·관리 이벤트 기록</p>
        </div>
        <div className="page-header__actions">
          <window.Button icon={<I.Download />}>CSV 내보내기</window.Button>
        </div>
      </div>

      <div className="sessions-toolbar">
        <div className="input-wrap" style={{ flex: 1, maxWidth: 360 }}>
          <I.Search className="icon-left" />
          <input className="input" placeholder="actor · action · target 검색" value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <window.Segmented value={filter} onChange={setFilter} options={[
          { value: 'all', label: `전체 · ${T.AUDIT_ENTRIES.length}` },
          { value: 'auth', label: 'Auth' },
          { value: 'session', label: 'Session' },
          { value: 'user', label: 'User' },
          { value: 'settings', label: 'Settings' },
        ]} />
      </div>

      <div className="card card__body--compact">
        <table className="table">
          <thead>
            <tr>
              <th>시각</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Target</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e, i) => (
              <tr key={i}>
                <td className="mono" style={{ fontSize: 11.5, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{e.ts}</td>
                <td>
                  {e.actor === 'system'
                    ? <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 22, height: 22, borderRadius: 6, background: 'var(--surface-2)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                          <I.Bolt width={11} height={11} />
                        </span>
                        <span style={{ fontSize: 12, color: 'var(--muted)' }}>system</span>
                      </span>
                    : <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><window.Avatar name={e.actor} size="sm" />{e.actor}</span>}
                </td>
                <td><window.Badge tone={actionTone(e.action)}>{e.action}</window.Badge></td>
                <td className="mono" style={{ fontSize: 12 }}>{e.target}</td>
                <td className="mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>{e.detail || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && (
        <div className="empty">
          <I.Search width={28} height={28} style={{ opacity: 0.4 }} />
          <h3>일치하는 감사 로그가 없습니다</h3>
        </div>
      )}
    </div>
  );
}

window.AdminUsersScreen = AdminUsersScreen;
window.AdminSettingsScreen = AdminSettingsScreen;
window.AdminAuditScreen = AdminAuditScreen;
