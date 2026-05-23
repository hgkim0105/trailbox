// ============================================================
// Auth screens — Login / Register
// ============================================================
const { useState: useStateAuth } = React;

function AuthVisual() {
  const I = window.Icons;
  return (
    <div className="auth-shell__visual">
      <div className="auth-mock">
        {/* Floating session card preview */}
        <div style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: 14,
          boxShadow: 'var(--shadow-lg)',
          transform: 'rotate(-1.5deg)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <div className="badge badge--success"><span className="dot" />업로드 완료</div>
            <div className="badge badge--neutral">PC · Win 11</div>
            <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)', fontFamily: 'Geist Mono' }}>10:12</div>
          </div>
          <div style={{ fontFamily: 'Geist Mono', fontSize: 12, color: 'var(--fg)', marginBottom: 4, fontWeight: 600 }}>
            20260522-101245-9a2f
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>Aurora · build 412 · QA 빌드 리플레이</div>

          {/* Tiny chart preview */}
          <div style={{
            background: 'oklch(0.13 0.01 270)',
            borderRadius: 6,
            height: 110,
            position: 'relative',
            overflow: 'hidden',
          }}>
            <svg viewBox="0 0 200 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
              <defs>
                <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="oklch(0.7 0.18 282)" stopOpacity="0.6" />
                  <stop offset="1" stopColor="oklch(0.7 0.18 282)" stopOpacity="0" />
                </linearGradient>
              </defs>
              <polyline points="0,70 14,62 28,68 42,55 56,45 70,52 84,32 98,28 112,40 126,38 140,22 154,30 168,18 182,25 200,20"
                fill="none" stroke="oklch(0.7 0.18 282)" strokeWidth="1.4" />
              <polyline points="0,80 200,80" stroke="oklch(0.3 0.01 270)" strokeWidth="0.4" strokeDasharray="2 2" />
            </svg>
            <div style={{ position: 'absolute', top: 6, left: 8, color: 'white', fontSize: 9, opacity: 0.7, letterSpacing: '0.05em', textTransform: 'uppercase' }}>CPU · 612 samples</div>
          </div>

          <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
            {[
              { label: 'Logs', value: '8.4k' },
              { label: 'Inputs', value: '1.9k' },
              { label: 'Samples', value: '612' },
            ].map(m => (
              <div key={m.label} style={{ flex: 1, textAlign: 'center', padding: 6, background: 'var(--surface-2)', borderRadius: 6 }}>
                <div style={{ fontFamily: 'Geist Mono', fontWeight: 600, fontSize: 12 }}>{m.value}</div>
                <div style={{ fontSize: 9, color: 'var(--muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>{m.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Floating share link card */}
        <div style={{
          position: 'absolute',
          bottom: -40,
          right: -30,
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: '10px 14px',
          boxShadow: 'var(--shadow-md)',
          transform: 'rotate(3deg)',
          width: 240,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <I.Link width={14} height={14} style={{ color: 'var(--accent)' }} />
            <div style={{ fontSize: 12, fontWeight: 600 }}>공유 링크 발급</div>
          </div>
          <div className="code-block" style={{ fontSize: 10, padding: 6 }}>hub.team/v/q9d2k8s1pa/</div>
        </div>

        {/* Floating event card */}
        <div style={{
          position: 'absolute',
          top: -30,
          left: -40,
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: '8px 12px',
          boxShadow: 'var(--shadow-md)',
          transform: 'rotate(-4deg)',
          fontSize: 11,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--danger)' }} />
            <span style={{ fontFamily: 'Geist Mono' }}>00:34.5</span>
            <span style={{ color: 'var(--muted)' }}>· gpu device hung</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function LoginScreen({ setRoute, onLogin }) {
  const I = window.Icons;
  const [username, setUsername] = useStateAuth('hyun');
  const [password, setPassword] = useStateAuth('demo-password');
  const [error, setError] = useStateAuth(null);
  const [loading, setLoading] = useStateAuth(false);

  const submit = (e) => {
    e.preventDefault();
    if (!username || !password) { setError('username과 password를 입력하세요.'); return; }
    setLoading(true);
    setError(null);
    setTimeout(() => { setLoading(false); onLogin(); }, 350);
  };

  return (
    <div className="auth-shell">
      <div className="auth-shell__form">
        <a className="auth-shell__brand" href="#" onClick={(e) => e.preventDefault()}>
          <div className="sidebar__brand-mark" style={{ width: 24, height: 24 }} />
          <span>Trailbox <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Hub</span></span>
        </a>

        <div className="auth-shell__form-inner">
          <h1>다시 만나서 반가워요</h1>
          <p className="subtitle">Trailbox Hub에 로그인하고 팀이 캡처한 세션을 확인하세요.</p>

          {error && <window.Flash tone="error">{error}</window.Flash>}

          <form onSubmit={submit}>
            <window.Field label="Username">
              <input
                className="input input--lg"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                placeholder="hyun"
              />
            </window.Field>
            <window.Field
              label="Password"
              action={<a href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: 12 }}>잊으셨나요?</a>}
            >
              <input
                className="input input--lg"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </window.Field>
            <window.Button variant="primary" size="lg" type="submit" disabled={loading}>
              {loading ? '로그인 중…' : '로그인'}
            </window.Button>
          </form>

          <div className="auth-foot">
            계정이 없나요? <a href="#" onClick={(e) => { e.preventDefault(); setRoute('register'); }}>회원가입</a>
          </div>

          <div style={{
            marginTop: 32, padding: 12,
            background: 'var(--surface-2)', border: '1px solid var(--border-muted)',
            borderRadius: 8, fontSize: 12, color: 'var(--muted)',
            display: 'flex', alignItems: 'flex-start', gap: 8,
          }}>
            <I.Bolt width={14} height={14} style={{ color: 'var(--accent)', marginTop: 1 }} />
            <div>
              <strong style={{ color: 'var(--fg-2)' }}>데모 모드 ─</strong> 아무 값으로 로그인하면 mock 데이터로 Hub UI 둘러보기 가능
            </div>
          </div>
        </div>
      </div>
      <AuthVisual />
    </div>
  );
}

function RegisterScreen({ setRoute }) {
  const [pending, setPending] = useStateAuth(false);
  const [form, setForm] = useStateAuth({ username: '', email: '', password: '' });
  const update = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const submit = (e) => {
    e.preventDefault();
    setPending(true);
  };

  if (pending) {
    return (
      <div className="auth-shell">
        <div className="auth-shell__form">
          <a className="auth-shell__brand" href="#" onClick={(e) => e.preventDefault()}>
            <div className="sidebar__brand-mark" style={{ width: 24, height: 24 }} />
            <span>Trailbox <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Hub</span></span>
          </a>
          <div className="auth-shell__form-inner">
            <div style={{ textAlign: 'center', padding: '20px 0' }}>
              <div style={{
                width: 56, height: 56, margin: '0 auto 18px',
                borderRadius: 16, background: 'var(--success-soft)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'var(--success)',
              }}>
                <window.Icons.Check width={26} height={26} />
              </div>
              <h1>신청 접수됨</h1>
              <p className="subtitle">관리자 승인을 기다리고 있어요. 보통 영업일 기준 하루 안에 처리됩니다.</p>
              <div style={{ marginTop: 16 }}>
                <window.Button variant="primary" size="lg" onClick={() => setRoute('login')}>로그인 페이지로</window.Button>
              </div>
            </div>
          </div>
        </div>
        <AuthVisual />
      </div>
    );
  }

  return (
    <div className="auth-shell">
      <div className="auth-shell__form">
        <a className="auth-shell__brand" href="#" onClick={(e) => e.preventDefault()}>
          <div className="sidebar__brand-mark" style={{ width: 24, height: 24 }} />
          <span>Trailbox <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Hub</span></span>
        </a>
        <div className="auth-shell__form-inner">
          <h1>계정 만들기</h1>
          <p className="subtitle">팀의 Hub에 합류하세요. 관리자 승인 후 활성화됩니다.</p>
          <form onSubmit={submit}>
            <window.Field label="Username">
              <input className="input input--lg" value={form.username} onChange={update('username')} autoFocus placeholder="ex. mina" />
            </window.Field>
            <window.Field label="Email" helpInline="(선택)">
              <input className="input input--lg" type="email" value={form.email} onChange={update('email')} placeholder="you@team.com" />
            </window.Field>
            <window.Field label="Password" helpInline="(최소 8자)">
              <input className="input input--lg" type="password" value={form.password} onChange={update('password')} minLength={8} />
            </window.Field>
            <window.Button variant="primary" size="lg" type="submit">가입 신청</window.Button>
          </form>
          <div className="auth-foot">
            이미 계정이 있나요? <a href="#" onClick={(e) => { e.preventDefault(); setRoute('login'); }}>로그인</a>
          </div>
        </div>
      </div>
      <AuthVisual />
    </div>
  );
}

window.LoginScreen = LoginScreen;
window.RegisterScreen = RegisterScreen;
