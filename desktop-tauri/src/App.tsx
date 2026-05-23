import { useState, useEffect, useCallback } from 'react';
import { Sidebar } from './components/Sidebar';
import { ThemeToggle } from './components/ThemeToggle';
import { CaptureScreen } from './screens/CaptureScreen';
import { SessionsScreen } from './screens/SessionsScreen';
import { HubSettingsScreen } from './screens/HubSettingsScreen';
import { HUB_INITIAL, type HubState } from './data/mock';

export type Route = 'capture' | 'sessions' | 'hub';

export default function App() {
  const [route, setRoute] = useState<Route>('capture');
  const [recording, setRecording] = useState(false);
  const [transition, setTransition] = useState<'starting' | 'stopping' | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [hub, setHub] = useState<HubState>(HUB_INITIAL);

  useEffect(() => {
    if (!recording) return;
    const id = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(id);
  }, [recording]);

  const startRecording = useCallback(() => {
    setTransition('starting');
    setTimeout(() => {
      setTransition(null);
      setRecording(true);
      setElapsed(0);
    }, 900);
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

  let screen: React.ReactNode;
  switch (route) {
    case 'capture':
      screen = (
        <CaptureScreen
          recording={recording}
          transition={transition}
          onStart={startRecording}
          onStop={stopRecording}
          elapsed={elapsed}
          fmtElapsed={fmtElapsed}
        />
      );
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
        {/* Native titlebar (32px) */}
        <div className="tbd-titlebar--native">
          <div className="tbd-title">
            <div className="sidebar__brand-mark" style={{ width: 14, height: 14, borderRadius: 4 }} />
            <span>Trailbox</span>
          </div>
          {recording && (
            <span className="tbd-rec-pill">
              <span className="dot" />
              REC {fmtElapsed(elapsed)}
            </span>
          )}
          <div className="tbd-titlebar__controls">
            <ThemeToggle />
          </div>
        </div>

        <div className="tbd-body">
          <Sidebar
            route={route}
            setRoute={setRoute}
            recording={recording}
            hub={hub}
          />
          <div className="tbd-main">
            <div className="content">{screen}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
