import { useState, useEffect, useRef } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Icon } from '../components/Icon';
import type { HubState } from '../data/mock';

type Tab = 'status' | 'login' | 'register' | 'advanced';
type Props = { hub: HubState; setHub: (h: HubState) => void; active: boolean };

export function HubSettingsScreen({ hub, setHub, active }: Props) {
  const [tab, setTab] = useState<Tab>(hub.configured ? 'status' : 'login');
  const [url, setUrl] = useState(hub.url);
  const [user, setUser] = useState('');
  const [pw, setPw] = useState('');
  const [email, setEmail] = useState('');
  const [token, setToken] = useState(hub.token || '');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<{ tone: 'ok' | 'err' | 'info'; msg: string } | null>(null);
  const [hubOnline, setHubOnline] = useState<boolean | null>(null);
  const checkedRef = useRef(false);

  // Check connectivity only when Hub tab is visible
  useEffect(() => {
    if (!active || checkedRef.current || !hub.configured) return;
    checkedRef.current = true;
    setHubOnline(null);
    invoke('hub_healthz', { url: hub.url, token: hub.token })
      .then(() => setHubOnline(true))
      .catch(() => setHubOnline(false));
  }, [active, hub.configured, hub.url]);

  // If configured, auto-switch to status tab
  useEffect(() => {
    if (hub.configured && tab === 'login') setTab('status');
  }, [hub.configured]);

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
      setHubOnline(true);
      setTab('status');
    } catch (e) {
      setStatus({ tone: 'err', msg: `로그인 실패: ${e}` });
    }
    setLoading(false);
  };

  const doTestConnection = async () => {
    setLoading(true);
    setStatus({ tone: 'info', msg: '연결 테스트 중…' });
    try {
      await invoke('hub_healthz', { url, token });
      setStatus({ tone: 'ok', msg: '연결 성공' });
    } catch (e) {
      setStatus({ tone: 'err', msg: `연결 실패: ${e}` });
    }
    setLoading(false);
  };

  const doSaveToken = () => {
    setHub({ url, username: hub.username || 'manual', token, configured: true });
    setHubOnline(null);
    checkedRef.current = false;
    setTab('status');
  };

  const disconnect = () => {
    setHub({ url: hub.url, username: '', token: '', configured: false });
    setHubOnline(null);
    checkedRef.current = false;
    setPw('');
    setToken('');
    setStatus(null);
    setTab('login');
  };

  return (
    <div>
      <div className="section-header">
        <div><h1>Hub 설정</h1><p>URL · 로그인 · 토큰 발급</p></div>
      </div>

      <div className="tbd-hub">
        <div className="tbd-card">
          <div className="tbd-hub-tabs">
            <button className={`tbd-hub-tabs__btn ${tab === 'status' ? 'active' : ''}`} disabled={!hub.configured} onClick={() => setTab('status')}>상태</button>
            <button className={`tbd-hub-tabs__btn ${tab === 'login' ? 'active' : ''}`} onClick={() => setTab('login')}>{hub.configured ? '재로그인' : '로그인'}</button>
            <button className={`tbd-hub-tabs__btn ${tab === 'register' ? 'active' : ''}`} onClick={() => setTab('register')}>회원가입</button>
            <button className={`tbd-hub-tabs__btn ${tab === 'advanced' ? 'active' : ''}`} onClick={() => setTab('advanced')}>고급</button>
          </div>

          <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="tbd-form-row">
              <label>Hub URL</label>
              <input className="tbd-input mono" placeholder="http://hub.local:8765" value={url} onChange={e => setUrl(e.target.value)} />
            </div>

            {/* ── Status tab ── */}
            {tab === 'status' && hub.configured && (
              <>
                {hubOnline === null && (
                  <div className="tbd-status tbd-status--info">연결 확인 중…</div>
                )}
                {hubOnline === true && (
                  <div className="tbd-status tbd-status--ok" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {Icon.Check()}연결됨 · 사용자 <strong>{hub.username}</strong>
                  </div>
                )}
                {hubOnline === false && (
                  <div className="tbd-status tbd-status--err" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {Icon.Close()}Hub 서버에 연결할 수 없습니다 · 토큰은 저장됨
                  </div>
                )}
                <dl className="tbd-meta-list" style={{ padding: '4px 0' }}>
                  <dt>사용자</dt><dd>{hub.username}</dd>
                  <dt>Hub URL</dt><dd>{hub.url}</dd>
                  <dt>토큰</dt><dd>{hub.token ? `${hub.token.slice(0, 8)}…` : '없음'}</dd>
                </dl>
                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                  <button className="tbd-btn" onClick={() => invoke('open_url', { url: hub.url })}>{Icon.Eye()}브라우저에서 열기</button>
                  <button className="tbd-btn tbd-btn--danger" onClick={disconnect}>연결 해제</button>
                </div>
              </>
            )}

            {/* ── Login tab ── */}
            {tab === 'login' && (
              <>
                {hub.configured && (
                  <div className="tbd-status tbd-status--info" style={{ fontSize: 11.5 }}>
                    이미 연결됨 ({hub.username}). 다른 계정으로 전환하려면 아래에서 로그인하세요.
                  </div>
                )}
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
                {status && tab === 'login' && (
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
                  <button className="tbd-btn" onClick={doTestConnection} disabled={loading || !url}>연결 테스트</button>
                  <button className="tbd-btn tbd-btn--primary" onClick={doSaveToken} disabled={!token}>저장</button>
                </div>
                {status && tab === 'advanced' && (
                  <div className={`tbd-status tbd-status--${status.tone}`} style={{ marginTop: 4 }}>
                    {status.msg}
                  </div>
                )}
                <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--muted)' }}>
                  로그인 흐름을 우회해 발급된 토큰을 직접 입력합니다.
                </div>
              </>
            )}
          </div>
        </div>

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
