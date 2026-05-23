import { useState, useEffect, useCallback } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { ThemeToggle } from './components/ThemeToggle';
import { Icon } from './components/Icon';
import { CaptureScreen } from './screens/CaptureScreen';
import { SessionsScreen } from './screens/SessionsScreen';
import { HubSettingsScreen } from './screens/HubSettingsScreen';
import { HUB_INITIAL, type HubState } from './data/mock';

export type Route = 'capture' | 'sessions' | 'hub';

const TABS: { key: Route; label: string; icon: (p?: any) => React.ReactNode }[] = [
  { key: 'capture', label: '캡처', icon: Icon.Capture },
  { key: 'sessions', label: '세션', icon: Icon.Sessions },
  { key: 'hub', label: 'Hub', icon: Icon.Hub },
];

export default function App() {
  const [route, setRoute] = useState<Route>('capture');
  const [recording, setRecording] = useState(false);
  const [transition, setTransition] = useState<'starting' | 'stopping' | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [hub, setHub] = useState<HubState>(HUB_INITIAL);
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!recording) return;
    const id = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(id);
  }, [recording]);

  useEffect(() => {
    const win = getCurrentWindow();
    const check = async () => setMaximized(await win.isMaximized());
    check();
    const unlisten = win.onResized(() => { check(); });
    return () => { unlisten.then(fn => fn()); };
  }, []);

  const startRecording = useCallback(() => {
    setTransition('starting');
    setTimeout(() => { setTransition(null); setRecording(true); setElapsed(0); }, 900);
  }, []);

  const stopRecording = useCallback(() => {
    setTransition('stopping');
    setRecording(false);
    setTimeout(() => setTransition(null), 1200);
  }, []);

  const fmtElapsed = (s: number) => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
      : `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  };

  const win = getCurrentWindow();

  let screen: React.ReactNode;
  switch (route) {
    case 'capture':
      screen = <CaptureScreen recording={recording} transition={transition} onStart={startRecording} onStop={stopRecording} elapsed={elapsed} fmtElapsed={fmtElapsed} />;
      break;
    case 'sessions':
      screen = <SessionsScreen hub={hub} />;
      break;
    case 'hub':
      screen = <HubSettingsScreen hub={hub} setHub={setHub} />;
      break;
  }

  return (
    <div className="tbd-app" data-theme="dark">
      <div className="tbd-window">
        {/* Custom titlebar (44px) — integrated tabs, no separate sidebar */}
        <div className="tbd-titlebar--custom" data-tauri-drag-region>
          <a className="tbd-brand" href="#" onClick={e => { e.preventDefault(); setRoute('capture'); }} style={{ WebkitAppRegion: 'no-drag' } as any}>
            <div className="sidebar__brand-mark" style={{ width: 20, height: 20, borderRadius: 5 }} />
            <span style={{ fontWeight: 600, fontSize: 13 }}>Trailbox</span>
          </a>

          <div className="tbd-tabs" style={{ WebkitAppRegion: 'no-drag' } as any}>
            {TABS.map(t => (
              <button key={t.key} className={`tbd-tab ${route === t.key ? 'active' : ''}`} onClick={() => setRoute(t.key)}>
                {t.icon()}
                <span>{t.label}</span>
              </button>
            ))}
          </div>

          {recording && (
            <span className="tbd-rec-pill" style={{ marginLeft: 12 }}>
              <span className="dot" />
              REC {fmtElapsed(elapsed)}
            </span>
          )}

          <div className="tbd-titlebar__controls" style={{ WebkitAppRegion: 'no-drag' } as any}>
            <ThemeToggle />
            <button onClick={() => win.minimize()} title="최소화">
              {Icon.Minimize()}
            </button>
            <button onClick={() => win.toggleMaximize()} title={maximized ? '이전 크기로' : '최대화'}>
              {Icon.Maximize()}
            </button>
            <button className="close" onClick={() => win.close()} title="닫기">
              {Icon.Close()}
            </button>
          </div>
        </div>

        <div className="tbd-body no-side">
          <div className="tbd-main">
            <div className="content">{screen}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
