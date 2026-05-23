// ============================================================
// Account screen — Profile + API tokens
// ============================================================
const { useState: useStateAcct } = React;

function AccountScreen({ user }) {
  const I = window.Icons;
  const T = window.TrailboxData;
  const [tokens, setTokens] = useStateAcct(T.TOKENS);
  const [newLabel, setNewLabel] = useStateAcct('');
  const [newToken, setNewToken] = useStateAcct(null);
  const [showPwForm, setShowPwForm] = useStateAcct(false);
  const [copied, copy] = window.useCopy();

  const generate = (e) => {
    e.preventDefault();
    const token = 'tb_' + Math.random().toString(36).slice(2, 26);
    setNewToken({ token, label: newLabel || '(no label)' });
    setTokens([
      { id: Math.floor(Math.random() * 100), label: newLabel || '(no label)', created_at: '방금', last_used: '—', revoked_at: null },
      ...tokens,
    ]);
    setNewLabel('');
  };
  const revoke = (id) => setTokens(tokens.map(t => t.id === id ? { ...t, revoked_at: '방금' } : t));

  return (
    <div className="content">
      <div className="page-header">
        <div>
          <h1>내 계정</h1>
          <p>프로필 · 비밀번호 · API 토큰 관리</p>
        </div>
      </div>

      {/* Profile card */}
      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card__body" style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <window.Avatar name={user.username} size="lg" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>{user.username}</div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
              <window.Badge tone={user.role === 'admin' ? 'accent' : 'neutral'}>{user.role}</window.Badge>
              <window.Badge tone="success" dot>{user.status}</window.Badge>
              <span style={{ color: 'var(--muted)', fontSize: 12.5 }}>· {user.email}</span>
            </div>
          </div>
          <window.Button icon={<I.Key />} onClick={() => setShowPwForm(p => !p)}>비밀번호 변경</window.Button>
        </div>
        {showPwForm && (
          <div style={{ padding: 18, borderTop: '1px solid var(--border)', background: 'var(--bg-2)' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, maxWidth: 720 }}>
              <window.Field label="현재 비밀번호"><input className="input" type="password" /></window.Field>
              <window.Field label="새 비밀번호" helpInline="(최소 8자)"><input className="input" type="password" /></window.Field>
              <window.Field label="확인"><input className="input" type="password" /></window.Field>
            </div>
            <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
              <window.Button variant="primary">변경</window.Button>
              <window.Button variant="ghost" onClick={() => setShowPwForm(false)}>취소</window.Button>
            </div>
          </div>
        )}
      </div>

      {/* Tokens card */}
      <div className="card">
        <div className="card__header">
          <div>
            <h3 className="card__title">API 토큰</h3>
            <div className="card__subtitle">Trailbox 클라이언트/MCP 백엔드가 <code>X-Trailbox-Token</code> 헤더에 실어 보냅니다.</div>
          </div>
        </div>
        <div className="card__body">
          {newToken && (
            <window.Flash tone="success" icon={<I.Check />} title="새 토큰 발급 완료">
              아래 값은 <strong>다시 표시되지 않습니다</strong> — 지금 복사해두세요.
              <div className="code-block" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ flex: 1 }}>{newToken.token}</span>
                <window.Button size="sm" variant="ghost" icon={<I.Copy />} onClick={() => copy(newToken.token, 'new')}>
                  {copied === 'new' ? '복사됨' : '복사'}
                </window.Button>
              </div>
            </window.Flash>
          )}

          <form onSubmit={generate} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <input className="input" placeholder="라벨 (예: laptop-qa1, claude-mcp)" value={newLabel} onChange={e => setNewLabel(e.target.value)} style={{ maxWidth: 320 }} />
            <window.Button variant="primary" icon={<I.Plus />} type="submit">새 토큰 발급</window.Button>
          </form>

          <table className="table">
            <thead>
              <tr><th>ID</th><th>라벨</th><th>발급</th><th>마지막 사용</th><th>상태</th><th></th></tr>
            </thead>
            <tbody>
              {tokens.map(t => (
                <tr key={t.id}>
                  <td className="mono" style={{ color: 'var(--muted)' }}>#{t.id}</td>
                  <td>{t.label}</td>
                  <td className="mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>{t.created_at}</td>
                  <td style={{ fontSize: 12 }}>{t.last_used}</td>
                  <td>
                    {t.revoked_at
                      ? <window.Badge tone="neutral">revoked</window.Badge>
                      : <window.Badge tone="success" dot>active</window.Badge>}
                  </td>
                  <td className="row-actions">
                    {!t.revoked_at && (
                      <window.Button size="sm" variant="ghost" className="btn--danger" onClick={() => revoke(t.id)}>
                        revoke
                      </window.Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* MCP setup hint */}
      <div className="card" style={{ marginTop: 18 }}>
        <div className="card__header">
          <div>
            <h3 className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <I.Robot width={14} height={14} style={{ color: 'var(--accent)' }} /> Claude Desktop MCP 연동
            </h3>
            <div className="card__subtitle">아래 설정을 <code>claude_desktop_config.json</code>에 추가하세요.</div>
          </div>
        </div>
        <div className="card__body">
          <pre className="code-block" style={{ margin: 0, lineHeight: 1.5 }}>{`{
  "mcpServers": {
    "trailbox": {
      "command": "C:\\\\Program Files\\\\Trailbox\\\\Trailbox-mcp.exe",
      "env": {
        "TRAILBOX_HUB_URL": "http://hub.team:8765",
        "TRAILBOX_HUB_TOKEN": "<위에서 발급한 토큰>"
      }
    }
  }
}`}</pre>
        </div>
      </div>
    </div>
  );
}

window.AccountScreen = AccountScreen;
