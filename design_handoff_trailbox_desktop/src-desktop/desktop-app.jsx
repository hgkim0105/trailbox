// ============================================================
// Trailbox Desktop App — Main component
// Used inside design canvas artboards with `chrome` prop
// ============================================================
const { useState: useStateD, useEffect: useEffectD, useRef: useRefD, useMemo: useMemoD } = React;

// ── Chrome / Window frame ────────────────────────────────
function WindowChrome({ chrome, title, rightSlot, route, setRoute, recording, theme, onToggleTheme }) {
  const I = window.Icons;
  if (chrome === 'native') {
    return (
      <div className="tbd-titlebar tbd-titlebar--native">
        <span className="tbd-title">{title}</span>
        {rightSlot}
        <div className="tbd-win-controls">
          <button className="tbd-win-btn" title="최소화"><svg width="10" height="10" viewBox="0 0 10 10"><line x1="0" y1="5" x2="10" y2="5" stroke="currentColor" strokeWidth="1.2" /></svg></button>
          <button className="tbd-win-btn" title="최대화"><svg width="10" height="10" viewBox="0 0 10 10"><rect x="1" y="1" width="8" height="8" fill="none" stroke="currentColor" strokeWidth="1.2" /></svg></button>
          <button className="tbd-win-btn tbd-win-btn--close" title="닫기"><svg width="10" height="10" viewBox="0 0 10 10"><path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.2" /></svg></button>
        </div>
      </div>
    );
  }
  // custom chrome
  const tabs = [
    { id: 'capture', label: '캡처', icon: <I.Bolt /> },
    { id: 'sessions', label: '세션', icon: <I.Sessions /> },
    { id: 'hub', label: 'Hub', icon: <I.Link /> },
  ];
  return (
    <div className="tbd-titlebar tbd-titlebar--custom">
      <div className="tbd-brand">
        <div className="tbd-brand-mark" />
        <span>Trailbox</span>
      </div>
      <div className="tbd-tablist">
        {tabs.map(t => (
          <button
            key={t.id}
            className={`tbd-tab ${route === t.id ? 'active' : ''}`}
            onClick={() => setRoute(t.id)}
          >
            {t.icon}<span>{t.label}</span>
          </button>
        ))}
      </div>
      <div className="tbd-actions">
        {rightSlot}
        <button className="tbd-btn tbd-btn--ghost tbd-btn--sm tbd-btn--icon" onClick={onToggleTheme} title={theme === 'dark' ? '라이트 모드' : '다크 모드'}>
          {theme === 'dark' ? <I.Sun /> : <I.Moon />}
        </button>
      </div>
      <div className="tbd-win-controls">
        <button className="tbd-win-btn" title="최소화"><svg width="10" height="10" viewBox="0 0 10 10"><line x1="0" y1="5" x2="10" y2="5" stroke="currentColor" strokeWidth="1.2" /></svg></button>
        <button className="tbd-win-btn" title="최대화"><svg width="10" height="10" viewBox="0 0 10 10"><rect x="1" y="1" width="8" height="8" fill="none" stroke="currentColor" strokeWidth="1.2" /></svg></button>
        <button className="tbd-win-btn tbd-win-btn--close" title="닫기"><svg width="10" height="10" viewBox="0 0 10 10"><path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.2" /></svg></button>
      </div>
    </div>
  );
}

// ── Sidebar (used in native chrome, since custom has tabs) ──
function DesktopSidebar({ route, setRoute, recording, hub, pendingCount }) {
  const I = window.Icons;
  return (
    <aside className="tbd-sidebar">
      <div className="tbd-sidebar__group">캡처</div>
      <a className={`tbd-nav ${route === 'capture' ? 'active' : ''}`} onClick={() => setRoute('capture')}>
        <I.Bolt /><span>캡처 준비</span>
        {recording && <span className="tbd-nav-badge" style={{ background: 'oklch(0.55 0.22 25)' }}>●</span>}
      </a>

      <div className="tbd-sidebar__group">데이터</div>
      <a className={`tbd-nav ${route === 'sessions' ? 'active' : ''}`} onClick={() => setRoute('sessions')}>
        <I.Sessions /><span>세션</span>
        <span className="tbd-nav-badge">{window.TrailboxDesktopData.DESKTOP_SESSIONS.length}</span>
      </a>

      <div className="tbd-sidebar__group">연동</div>
      <a className={`tbd-nav ${route === 'hub' ? 'active' : ''}`} onClick={() => setRoute('hub')}>
        <I.Link /><span>Trailbox Hub</span>
        {hub.configured ? <span className="tbd-badge tbd-badge--success" style={{ marginLeft: 'auto' }}><span className="dot" />연결됨</span> : null}
      </a>

      <div className="tbd-sidebar__hub-status">
        <strong>{hub.username || '미로그인'}</strong>
        <div className="row">
          {hub.configured
            ? <><span className="dot" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--success)' }} /> {hub.url.replace(/^https?:\/\//, '')}</>
            : <span>Hub 미연결</span>}
        </div>
      </div>
    </aside>
  );
}

// ── Recording status pill (shown in titlebar / actions area when recording) ──
function RecPill({ elapsed }) {
  const m = Math.floor(elapsed / 60);
  const s = Math.floor(elapsed % 60);
  return (
    <div className="tbd-rec-pill">
      <span className="dot" />
      <span>REC {String(m).padStart(2, '0')}:{String(s).padStart(2, '0')}</span>
    </div>
  );
}

// ── App root used inside each artboard ───────────────────
function DesktopApp({ chrome = 'native', initialRoute = 'capture', initialRecording = false, embedded = false }) {
  const D = window.TrailboxDesktopData;
  const [route, setRoute] = useStateD(initialRoute);
  const [recording, setRecording] = useStateD(initialRecording);
  const [transition, setTransition] = useStateD(null); // 'starting' | 'stopping' | null
  const [elapsed, setElapsed] = useStateD(initialRecording ? 38 : 0);
  const [theme, setTheme] = useStateD('light');
  const [hub, setHub] = useStateD(D.HUB_STATE);

  // Tick elapsed seconds while recording
  useEffectD(() => {
    if (!recording) return;
    const id = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(id);
  }, [recording]);

  const startRecording = () => {
    setTransition('starting');
    setTimeout(() => { setTransition(null); setRecording(true); setElapsed(0); }, 900);
  };
  const stopRecording = () => {
    setTransition('stopping');
    setTimeout(() => { setTransition(null); setRecording(false); }, 1200);
  };

  const title = 'Trailbox';

  // For native chrome: sidebar visible. For custom: tabs in titlebar instead.
  const showSidebar = chrome === 'native';

  let content = null;
  if (route === 'capture') {
    content = (
      <window.TbdCaptureScreen
        recording={recording} transition={transition}
        onStart={startRecording} onStop={stopRecording}
        elapsed={elapsed}
      />
    );
  } else if (route === 'sessions') {
    content = <window.TbdSessionsScreen hub={hub} />;
  } else if (route === 'hub') {
    content = <window.TbdHubScreen hub={hub} setHub={setHub} />;
  }

  return (
    <div className={`tbd-app ${embedded ? 'tbd-app--embedded' : ''}`} data-theme={theme}>
      <div className="tbd-window">
        <WindowChrome
          chrome={chrome}
          title={title}
          route={route} setRoute={setRoute}
          theme={theme} onToggleTheme={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
          recording={recording}
          rightSlot={recording ? <RecPill elapsed={elapsed} /> : null}
        />
        <div className={`tbd-body ${!showSidebar ? 'tbd-body--no-side' : ''}`}>
          {showSidebar && (
            <DesktopSidebar route={route} setRoute={setRoute} recording={recording} hub={hub} />
          )}
          <main className="tbd-main">
            {content}
          </main>
        </div>
      </div>
    </div>
  );
}

window.DesktopApp = DesktopApp;
