// ============================================================
// App root — Router, Theme, Tweaks integration
// ============================================================
const { useState, useEffect, useMemo } = React;

const DEFAULT_TWEAKS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "accent_h": 282,
  "list_layout": "cards",
  "density": "comfortable"
}/*EDITMODE-END*/;

function App() {
  const T = window.TrailboxData;
  const { useTweaks, TweaksPanel, TweakSection, TweakRadio, TweakColor, TweakSelect } = window;

  const [authed, setAuthed] = useState(true); // start logged-in to showcase the Hub
  const [route, setRoute] = useState('sessions'); // sessions | sessions/:id | account | admin-* | login | register
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [sessions, setSessions] = useState(T.SESSIONS);

  const [tweaks, setTweak] = useTweaks(DEFAULT_TWEAKS);

  // Theme on root
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', tweaks.theme);
  }, [tweaks.theme]);

  // Accent hue
  useEffect(() => {
    document.documentElement.style.setProperty('--accent-h', String(tweaks.accent_h));
  }, [tweaks.accent_h]);

  const toggleTheme = () => setTweak('theme', tweaks.theme === 'dark' ? 'light' : 'dark');

  const openSession = (id) => {
    setCurrentSessionId(id);
    setRoute('session-detail');
  };

  const deleteSession = (id) => {
    setSessions(s => s.filter(x => x.session_id !== id));
    setRoute('sessions');
  };

  const user = T.CURRENT_USER;
  const pendingCount = T.PENDING_USERS.length;

  // ── Render ──
  if (!authed) {
    if (route === 'register') {
      return (
        <>
          <window.RegisterScreen setRoute={setRoute} />
          <TweaksUI tweaks={tweaks} setTweak={setTweak} />
        </>
      );
    }
    return (
      <>
        <window.LoginScreen setRoute={setRoute} onLogin={() => { setAuthed(true); setRoute('sessions'); }} />
        <TweaksUI tweaks={tweaks} setTweak={setTweak} />
      </>
    );
  }

  // Determine crumbs and content
  let crumbs = [], content = null;
  if (route === 'sessions') {
    crumbs = [{ label: '워크스페이스', to: 'sessions' }, { label: '세션' }];
    content = (
      <window.SessionsListScreen
        setRoute={setRoute}
        openSession={openSession}
        layout={tweaks.list_layout}
        sessions={sessions}
        user={user}
      />
    );
  } else if (route === 'session-detail') {
    const session = sessions.find(s => s.session_id === currentSessionId) || sessions[0];
    crumbs = [{ label: '세션', to: 'sessions' }, { label: session.session_id }];
    content = (
      <window.SessionDetailScreen
        session={session}
        setRoute={setRoute}
        openSession={openSession}
        deleteSession={deleteSession}
      />
    );
  } else if (route === 'account') {
    crumbs = [{ label: '내 계정' }];
    content = <window.AccountScreen user={user} />;
  } else if (route === 'admin-users') {
    crumbs = [{ label: '관리자' }, { label: '사용자' }];
    content = <window.AdminUsersScreen />;
  } else if (route === 'admin-settings') {
    crumbs = [{ label: '관리자' }, { label: '시스템 설정' }];
    content = <window.AdminSettingsScreen />;
  } else if (route === 'admin-audit') {
    crumbs = [{ label: '관리자' }, { label: '감사 로그' }];
    content = <window.AdminAuditScreen />;
  } else {
    crumbs = [{ label: '세션' }];
    content = <div className="content"><h1>준비 중</h1></div>;
  }

  return (
    <>
      <div className={`app ${tweaks.density === 'compact' ? 'app--compact' : ''}`}>
        <window.Sidebar route={route} setRoute={setRoute} user={user} pendingCount={pendingCount} />
        <div className="main">
          <window.Topbar
            crumbs={crumbs}
            setRoute={setRoute}
            theme={tweaks.theme}
            onToggleTheme={toggleTheme}
            actions={
              <>
                <window.Button size="sm" variant="ghost" icon={<window.Icons.Search />}>
                  <span style={{ marginLeft: 2 }}>검색</span>
                  <span className="kbd" style={{ marginLeft: 6 }}>⌘K</span>
                </window.Button>
                <button
                  className="btn btn--ghost btn--sm"
                  onClick={() => { setAuthed(false); setRoute('login'); }}
                  title="로그아웃"
                >
                  <window.Icons.Logout /> 로그아웃
                </button>
              </>
            }
          />
          {content}
        </div>
      </div>
      <TweaksUI tweaks={tweaks} setTweak={setTweak} />
    </>
  );
}

const ACCENT_OPTIONS = [
  { hue: 282, label: '인디고' },
  { hue: 250, label: '블루' },
  { hue: 200, label: '시안' },
  { hue: 150, label: '에메랄드' },
  { hue: 30,  label: '오렌지' },
  { hue: 350, label: '핑크' },
];

function AccentPicker({ value, onChange }) {
  return (
    <div className="twk-row">
      <div className="twk-lbl"><span>액센트</span></div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {ACCENT_OPTIONS.map(o => {
          const on = value === o.hue;
          return (
            <button
              key={o.hue}
              type="button"
              title={o.label}
              onClick={() => onChange(o.hue)}
              style={{
                width: 26, height: 26,
                background: `oklch(0.6 0.18 ${o.hue})`,
                border: on ? '2px solid white' : '1px solid rgba(0,0,0,0.1)',
                boxShadow: on ? `0 0 0 2px oklch(0.6 0.18 ${o.hue}), 0 2px 4px rgba(0,0,0,0.15)` : '0 1px 3px rgba(0,0,0,0.15)',
                borderRadius: 6,
                cursor: 'pointer',
                padding: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {on && <span style={{ color: 'white', fontSize: 12, fontWeight: 700 }}>✓</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

const LAYOUT_OPTIONS = [
  { value: 'cards', label: '카드' },
  { value: 'table', label: '테이블' },
  { value: 'compact', label: '컴팩트' },
];

function LayoutPicker({ value, onChange }) {
  return (
    <div className="twk-row">
      <div className="twk-lbl"><span>레이아웃</span></div>
      <div style={{
        display: 'flex',
        padding: 2,
        background: 'rgba(0,0,0,0.06)',
        borderRadius: 8,
        gap: 2,
      }}>
        {LAYOUT_OPTIONS.map(o => {
          const on = value === o.value;
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => onChange(o.value)}
              style={{
                flex: 1,
                height: 24,
                border: 0,
                background: on ? 'white' : 'transparent',
                boxShadow: on ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
                color: on ? '#29261b' : 'rgba(41,38,27,0.6)',
                borderRadius: 6,
                fontSize: 11,
                fontWeight: on ? 600 : 500,
                cursor: 'pointer',
                transition: 'background 0.12s, color 0.12s',
              }}
            >{o.label}</button>
          );
        })}
      </div>
    </div>
  );
}

function ThemePicker({ value, onChange }) {
  const opts = [{ value: 'light', label: '라이트' }, { value: 'dark', label: '다크' }];
  return (
    <div className="twk-row">
      <div className="twk-lbl"><span>테마</span></div>
      <div style={{
        display: 'flex',
        padding: 2,
        background: 'rgba(0,0,0,0.06)',
        borderRadius: 8,
        gap: 2,
      }}>
        {opts.map(o => {
          const on = value === o.value;
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => onChange(o.value)}
              style={{
                flex: 1,
                height: 24,
                border: 0,
                background: on ? 'white' : 'transparent',
                boxShadow: on ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
                color: on ? '#29261b' : 'rgba(41,38,27,0.6)',
                borderRadius: 6,
                fontSize: 11,
                fontWeight: on ? 600 : 500,
                cursor: 'pointer',
              }}
            >{o.label}</button>
          );
        })}
      </div>
    </div>
  );
}

function TweaksUI({ tweaks, setTweak }) {
  const { TweaksPanel, TweakSection } = window;
  return (
    <TweaksPanel title="Tweaks">
      <TweakSection title="외관" />
      <ThemePicker value={tweaks.theme} onChange={v => setTweak('theme', v)} />
      <AccentPicker value={tweaks.accent_h} onChange={v => setTweak('accent_h', v)} />

      <TweakSection title="세션 목록" />
      <LayoutPicker value={tweaks.list_layout} onChange={v => setTweak('list_layout', v)} />
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
