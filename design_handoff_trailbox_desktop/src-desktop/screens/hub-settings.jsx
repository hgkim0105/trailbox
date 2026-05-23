// ============================================================
// Hub settings screen — login / register / advanced + status
// ============================================================
const { useState: useStateHub } = React;

function TbdHubScreen({ hub, setHub }) {
  const I = window.Icons;
  const [tab, setTab] = useStateHub(hub.configured ? 'status' : 'login');
  const [url, setUrl] = useStateHub(hub.url);
  const [user, setUser] = useStateHub(hub.username);
  const [pw, setPw] = useStateHub('');
  const [status, setStatus] = useStateHub(null); // { tone, msg }
  const [loading, setLoading] = useStateHub(false);

  const login = () => {
    if (!url || !user || !pw) {
      setStatus({ tone: 'err', msg: '모든 항목을 입력하세요.' });
      return;
    }
    setLoading(true);
    setStatus({ tone: 'info', msg: '로그인 중…' });
    setTimeout(() => {
      setStatus({ tone: 'info', msg: '토큰 발급 중…' });
      setTimeout(() => {
        setLoading(false);
        setStatus({ tone: 'ok', msg: '토큰 발급 완료 — 저장됨' });
        setHub({ ...hub, configured: true, url, username: user });
        setTab('status');
      }, 700);
    }, 700);
  };

  const disconnect = () => {
    setHub({ ...hub, configured: false });
    setStatus(null);
    setPw('');
    setTab('login');
  };

  return (
    <>
      <div className="tbd-section-head">
        <h2>Trailbox Hub</h2>
        <span className="sub">팀 공유 / 자동 백업 / AI 분석을 위한 백엔드</span>
        {hub.configured && (
          <span className="tbd-badge tbd-badge--success" style={{ marginLeft: 'auto' }}>
            <span className="dot" /> 연결됨
          </span>
        )}
      </div>

      <div className="tbd-hub">
        {/* Left: forms */}
        <section className="tbd-card">
          <div className="tbd-card__body" style={{ padding: '14px 16px 16px' }}>
            <div className="tbd-hub-tabs">
              <button className={`tbd-hub-tabs__btn ${tab === 'status' ? 'active' : ''}`} onClick={() => setTab('status')} disabled={!hub.configured}>
                상태
              </button>
              <button className={`tbd-hub-tabs__btn ${tab === 'login' ? 'active' : ''}`} onClick={() => setTab('login')}>
                로그인
              </button>
              <button className={`tbd-hub-tabs__btn ${tab === 'register' ? 'active' : ''}`} onClick={() => setTab('register')}>
                회원가입
              </button>
              <button className={`tbd-hub-tabs__btn ${tab === 'advanced' ? 'active' : ''}`} onClick={() => setTab('advanced')}>
                고급 (수동 토큰)
              </button>
            </div>

            {/* URL is shared across all tabs */}
            <div className="tbd-form-row">
              <label>Hub URL</label>
              <input className="tbd-input mono" value={url} onChange={e => setUrl(e.target.value)} placeholder="http://hub.local:8765" />
            </div>

            {tab === 'status' && hub.configured && (
              <>
                <div className="tbd-status-text tbd-status-text--ok">
                  <I.Check />
                  <span>연결됨 · 사용자 <strong>{hub.username}</strong> · 토큰 active</span>
                </div>

                <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '8px 16px', fontSize: 12.5 }}>
                  <span style={{ color: 'var(--muted)' }}>Hub 버전</span>
                  <span className="tbd-mono">v0.4.2</span>
                  <span style={{ color: 'var(--muted)' }}>Trailbox 클라이언트</span>
                  <span className="tbd-mono">v0.4.2</span>
                  <span style={{ color: 'var(--muted)' }}>토큰 라벨</span>
                  <span className="tbd-mono">trailbox-DESKTOP-A8H2</span>
                  <span style={{ color: 'var(--muted)' }}>마지막 동기화</span>
                  <span className="tbd-mono">12분 전</span>
                  <span style={{ color: 'var(--muted)' }}>업로드 청크</span>
                  <span className="tbd-mono">8 MB · 재개 지원</span>
                </div>

                <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                  <a className="tbd-btn tbd-btn--sm" href="http://hub.team:8765/sessions" target="_blank" rel="noopener">
                    <I.Link /> 브라우저에서 열기
                  </a>
                  <button className="tbd-btn tbd-btn--sm tbd-btn--danger" onClick={disconnect}>
                    연결 해제
                  </button>
                </div>
              </>
            )}

            {tab === 'login' && (
              <>
                <div className="tbd-form-row">
                  <label>Username</label>
                  <input className="tbd-input" value={user} onChange={e => setUser(e.target.value)} autoFocus />
                </div>
                <div className="tbd-form-row">
                  <label>Password</label>
                  <input className="tbd-input" type="password" value={pw} onChange={e => setPw(e.target.value)} onKeyDown={e => e.key === 'Enter' && login()} />
                </div>
                <button className="tbd-btn tbd-btn--primary" onClick={login} disabled={loading} style={{ marginTop: 8 }}>
                  로그인 + 토큰 발급
                </button>
                {status && (
                  <div className={`tbd-status-text tbd-status-text--${status.tone === 'ok' ? 'ok' : status.tone === 'err' ? 'err' : 'info'}`}>
                    {status.tone === 'ok' && <I.Check />}
                    {status.tone === 'err' && <I.Close />}
                    <span>{status.msg}</span>
                  </div>
                )}
                <div style={{ marginTop: 14, padding: 10, background: 'var(--bg-2)', border: '1px solid var(--border-muted)', borderRadius: 6, fontSize: 11.5, color: 'var(--muted)' }}>
                  💡 데모 모드: 아무 username/password로 로그인하면 mock 토큰이 발급됩니다.
                </div>
              </>
            )}

            {tab === 'register' && (
              <>
                <div className="tbd-form-row">
                  <label>Username</label>
                  <input className="tbd-input" placeholder="ex. mina" />
                </div>
                <div className="tbd-form-row">
                  <label>Email</label>
                  <input className="tbd-input" placeholder="(선택) 운영자에게 전달용" />
                </div>
                <div className="tbd-form-row">
                  <label>Password</label>
                  <input className="tbd-input" type="password" placeholder="최소 12자" />
                </div>
                <button className="tbd-btn tbd-btn--primary" style={{ marginTop: 8 }}>
                  회원가입 신청
                </button>
                <div style={{ marginTop: 12, padding: 10, background: 'var(--warning-soft)', border: '1px solid color-mix(in oklch, var(--warning) 30%, transparent)', borderRadius: 6, fontSize: 11.5 }}>
                  ⏳ 관리자 승인 후 자동으로 로그인됩니다. 자동 승인이 켜져 있으면 즉시 활성화.
                </div>
              </>
            )}

            {tab === 'advanced' && (
              <>
                <div className="tbd-form-row">
                  <label>API Token</label>
                  <input className="tbd-input mono" type="password" placeholder="기존 토큰 또는 운영자 service-token" />
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                  <button className="tbd-btn">연결 테스트</button>
                  <button className="tbd-btn tbd-btn--primary">저장</button>
                </div>
                <div style={{ marginTop: 12, fontSize: 11.5, color: 'var(--muted)' }}>
                  로그인 흐름을 우회해 발급된 토큰을 직접 입력합니다. 운영자가 발급한 service-token도 사용 가능.
                </div>
              </>
            )}
          </div>
        </section>

        {/* Right: about Hub */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <section className="tbd-card">
            <div className="tbd-card__head"><h3>Hub로 할 수 있는 일</h3></div>
            <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Feature icon={<I.Share />} title="공유 링크" desc="브라우저로 viewer 바로 열기" />
              <Feature icon={<I.Download style={{ transform: 'rotate(180deg)' }} />} title="자동 백업" desc="녹화 종료 시 자동 업로드" />
              <Feature icon={<I.Robot />} title="AI 분석" desc="Claude Desktop MCP가 원격 세션 조회" />
              <Feature icon={<I.Users />} title="팀 협업" desc="다른 사람이 업로드한 세션 가져오기" />
            </div>
          </section>

          <section className="tbd-card">
            <div className="tbd-card__head"><h3>Hub 미설치?</h3></div>
            <div className="tbd-card__body" style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
              Hub 없이도 모든 로컬 캡처 기능은 그대로 동작합니다. Hub는 옵션이에요.
              <br /><br />
              운영자라면 Trailbox 인스톨러에서 <strong style={{ color: 'var(--fg)' }}>Full</strong> 설치를 선택해 같은 PC에 Hub를 띄울 수 있습니다.
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}

function Feature({ icon, title, desc }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
      <div style={{
        width: 26, height: 26, borderRadius: 6,
        background: 'var(--accent-soft)', color: 'var(--accent-fg)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>{icon}</div>
      <div>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>{desc}</div>
      </div>
    </div>
  );
}

window.TbdHubScreen = TbdHubScreen;
