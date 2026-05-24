import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Icon } from '../components/Icon';
import type { HubState } from '../data/mock';

type Tab = 'status' | 'login' | 'register' | 'advanced';
type Props = { hub: HubState; setHub: (h: HubState) => void };

export function HubSettingsScreen({ hub, setHub }: Props) {
  const [tab, setTab] = useState<Tab>(hub.configured ? 'status' : 'login');
  const [url, setUrl] = useState(hub.url);
  const [user, setUser] = useState('');
  const [pw, setPw] = useState('');
  const [email, setEmail] = useState('');
  const [token, setToken] = useState(hub.token || '');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<{ tone: 'ok' | 'err' | 'info'; msg: string } | null>(null);
  const [hubOnline, setHubOnline] = useState<boolean | null>(null);

  // Check actual Hub connectivity on mount and when tab switches to status
  useEffect(() => {
    if (!hub.configured) { setHubOnline(null); return; }
    setHubOnline(null);
    invoke('hub_healthz', { url: hub.url, token: hub.token })
      .then(() => setHubOnline(true))
      .catch(() => {
        setHubOnline(false);
        setStatus({ tone: 'err', msg: 'Hub 서버에 연결할 수 없습니다' });
      });
  }, [hub.configured, hub.url, tab]);

  const doLogin = async () => {
    if (!user || !pw) return;
    setLoading(true);
    setStatus({ tone: 'info', msg: '로그인 중…' });
    try {
      const result = await invoke<{ user: any; token: any }>('hub_login', { url, username: user, password: pw });
      const issuedToken = result.token?.token ?? '';
      setToken(issuedToken);
      setStatus({ tone: 'ok', msg: `토큰 발급 완료 — ${result.token?.label ?? '저장됨'}` });
      setHub({ url, username: user, token: issuedToken, configured: true });
      setTab('status');
    } catch (e) {
      setStatus({ tone: 'err', msg: `로그인 실패: ${e}` });
    }
    setLoading(false);
  };

  const disconnect = () => {
    setHub({ ...hub, configured: false, username: '', token: '' });
    setPw('');
    setTab('login');
    setStatus(null);
  };

  return (
    <div>
      <div className="section-header">
        <div>
          <h1>Hub 설정</h1>
          <p>URL · 로그인 · 토큰 발급</p>
        </div>
      </div>

      <div className="tbd-hub">
        {/* Left: form card */}
        <div className="tbd-card">
          <div className="tbd-hub-tabs">
            <button className={`tbd-hub-tabs__btn ${tab === 'status' ? 'active' : ''}`} disabled={!hub.configured} onClick={() => setTab('status')}>상태</button>
            <button className={`tbd-hub-tabs__btn ${tab === 'login' ? 'active' : ''}`} onClick={() => setTab('login')}>로그인</button>
            <button className={`tbd-hub-tabs__btn ${tab === 'register' ? 'active' : ''}`} onClick={() => setTab('register')}>회원가입</button>
            <button className={`tbd-hub-tabs__btn ${tab === 'advanced' ? 'active' : ''}`} onClick={() => setTab('advanced')}>고급</button>
          </div>

          <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* Shared URL row */}
            <div className="tbd-form-row">
              <label>Hub URL</label>
              <input className="tbd-input mono" placeholder="http://hub.local:8765" value={url} onChange={e => setUrl(e.target.value)} />
            </div>

            {/* ── Status tab ── */}
            {tab === 'status' && hub.configured && (
              <>
                {hubOnline === null && (
                  <div className="tbd-status tbd-status--info" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    연결 확인 중…
                  </div>
                )}
                {hubOnline === true && (
                  <div className="tbd-status tbd-status--ok" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {Icon.Check()}연결됨 · 사용자 <strong>{hub.username}</strong> · 토큰 active
                  </div>
                )}
                {hubOnline === false && (
                  <div className="tbd-status tbd-status--err" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {Icon.Close()}Hub 서버에 연결할 수 없습니다 · 설정된 사용자: <strong>{hub.username}</strong>
                  </div>
                )}
                <dl className="tbd-meta-list" style={{ padding: '4px 0' }}>
                  <dt>Hub 버전</dt><dd>0.9.3</dd>
                  <dt>클라이언트</dt><dd>0.9.3</dd>
                  <dt>토큰 라벨</dt><dd>trailbox-DESKTOP</dd>
                  <dt>마지막 동기화</dt><dd>방금 전</dd>
                  <dt>청크 크기</dt><dd>64 MB</dd>
                </dl>
                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                  <button className="tbd-btn" onClick={() => invoke('open_url', { url })}>{Icon.Eye()}브라우저에서 열기</button>
                  <button className="tbd-btn tbd-btn--danger" onClick={disconnect}>연결 해제</button>
                </div>
              </>
            )}

            {/* ── Login tab ── */}
            {tab === 'login' && (
              <>
                <div className="tbd-form-row">
                  <label>사용자명</label>
                  <input className="tbd-input" placeholder="username" value={user} onChange={e => setUser(e.target.value)} autoFocus />
                </div>
                <div className="tbd-form-row">
                  <label>비밀번호</label>
                  <input className="tbd-input" type="password" placeholder="••••••••" value={pw} onChange={e => setPw(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && doLogin()} />
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                  <button className="tbd-btn tbd-btn--primary" onClick={doLogin} disabled={loading || !user || !pw}>
                    {Icon.Key()}로그인 + 토큰 발급
                  </button>
                </div>
                {status && (
                  <div className={`tbd-status tbd-status--${status.tone}`} style={{ marginTop: 4 }}>
                    {status.msg}
                  </div>
                )}
              </>
            )}

            {/* ── Register tab ── */}
            {tab === 'register' && (
              <>
                <div className="tbd-form-row">
                  <label>사용자명</label>
                  <input className="tbd-input" placeholder="ex. mina" value={user} onChange={e => setUser(e.target.value)} />
                </div>
                <div className="tbd-form-row">
                  <label>이메일</label>
                  <input className="tbd-input" placeholder="(선택) 운영자에게 전달용" value={email} onChange={e => setEmail(e.target.value)} />
                </div>
                <div className="tbd-form-row">
                  <label>비밀번호</label>
                  <input className="tbd-input" type="password" placeholder="최소 12자" value={pw} onChange={e => setPw(e.target.value)} />
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                  <button className="tbd-btn tbd-btn--primary" disabled={!user || !pw}>회원가입 신청</button>
                </div>
                <div style={{ marginTop: 8, padding: '8px 10px', background: 'var(--warning-soft)', borderRadius: 6, fontSize: 11.5, color: 'oklch(0.45 0.14 75)' }}>
                  ⏳ 관리자 승인 후 자동으로 로그인됩니다.
                </div>
              </>
            )}

            {/* ── Advanced tab ── */}
            {tab === 'advanced' && (
              <>
                <div className="tbd-form-row">
                  <label>API Token</label>
                  <input className="tbd-input mono" type="password" placeholder="기존 토큰 또는 운영자 service-token" value={token} onChange={e => setToken(e.target.value)} />
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                  <button className="tbd-btn">연결 테스트</button>
                  <button className="tbd-btn tbd-btn--primary" disabled={!token}>저장</button>
                </div>
                <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--muted)' }}>
                  로그인 흐름을 우회해 발급된 토큰을 직접 입력합니다.
                </div>
              </>
            )}
          </div>
        </div>

        {/* Right: info panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="tbd-card">
            <div className="tbd-card__head"><h3>Hub로 할 수 있는 일</h3></div>
            <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Feature icon={Icon.Share} title="공유 링크" desc="브라우저로 viewer 바로 열기" />
              <Feature icon={Icon.Upload} title="자동 백업" desc="녹화 종료 시 자동 업로드" />
              <Feature icon={Icon.Robot} title="AI 분석" desc="Claude Desktop MCP가 원격 세션 조회" />
              <Feature icon={Icon.Link} title="팀 협업" desc="다른 사람이 업로드한 세션 가져오기" />
            </div>
          </div>

          <div className="tbd-card">
            <div className="tbd-card__head"><h3>Hub 미설치?</h3></div>
            <div className="tbd-card__body" style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
              Hub 없이도 모든 로컬 캡처 기능은 그대로 동작합니다. Hub는 옵션이에요.
              <div style={{ marginTop: 6 }}>
                <a href="#" style={{ fontSize: 11.5 }}>Full 설치를 선택해 같은 PC에 Hub를 띄울 수 있습니다 →</a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Feature({ icon, title, desc }: { icon: (p?: any) => React.ReactNode; title: string; desc: string }) {
  return (
    <div className="tbd-hub-feature">
      <div className="tbd-hub-feature__icon">{icon()}</div>
      <div className="tbd-hub-feature__text">
        <h4>{title}</h4>
        <p>{desc}</p>
      </div>
    </div>
  );
}
