import { useState, useEffect, useCallback, useRef } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { listen } from '@tauri-apps/api/event';
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

type Toast = { id: number; msg: string; tone: 'ok' | 'err' | 'info' };
let toastId = 0;

export default function App() {
  const [route, setRoute] = useState<Route>('capture');
  const [recording, setRecording] = useState(false);
  const [transition, setTransition] = useState<'starting' | 'stopping' | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [hub, setHubRaw] = useState<HubState>(HUB_INITIAL);
  const setHub = useCallback((h: HubState) => {
    setHubRaw(h);
    try { localStorage.setItem('trailbox_hub', JSON.stringify(h)); } catch {}
  }, []);
  const [maximized, setMaximized] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [liveStatus, setLiveStatus] = useState<any>(null);
  const [localSessions, setLocalSessions] = useState<any[]>([]);
  const captureConfigRef = useRef<any>(null);

  // Fetch sessions once at mount + on refreshKey change
  useEffect(() => {
    invoke<any[]>('list_local_sessions').then(list => {
      if (Array.isArray(list)) setLocalSessions(list);
    }).catch(() => {});
  }, [refreshKey]);


  const showToast = useCallback((msg: string, tone: Toast['tone'] = 'info') => {
    const id = ++toastId;
    setToasts(t => [...t, { id, msg, tone }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500);
  }, []);

  useEffect(() => {
    if (!recording) { setLiveStatus(null); return; }
    const id = setInterval(async () => {
      setElapsed(e => {
        const next = e + 1;
        invoke('sync_overlay_time', { elapsed: next }).catch(() => {});
        return next;
      });
      try {
        const s = await invoke<any>('read_recording_status');
        if (s) setLiveStatus(s);
      } catch {}
    }, 1000);
    return () => clearInterval(id);
  }, [recording]);

  useEffect(() => {
    const win = getCurrentWindow();
    const check = async () => setMaximized(await win.isMaximized());
    check();
    const unlisten = win.onResized(() => { check(); });
    return () => { unlisten.then(fn => fn()); };
  }, []);

  useEffect(() => {
    const u1 = listen('global-stop-recording', () => {
      if (recording && !transition) {
        stopRecording();
        showToast('Ctrl+Alt+R로 녹화 중지됨', 'ok');
      }
    });
    const u2 = listen('global-pick-window', async () => {
      setRoute('capture');
      try {
        const w = await invoke<any>('pick_window_click');
        if (w && w.hwnd) showToast(`창 선택됨: ${w.title || w.process_name}`, 'ok');
      } catch {}
    });
    return () => { u1.then(fn => fn()); u2.then(fn => fn()); };
  }, [recording, transition]);

  const startRecording = useCallback(async () => {
    const config = captureConfigRef.current;
    if (!config) {
      showToast('캡처 설정을 먼저 구성하세요', 'err');
      return;
    }
    setTransition('starting');
    try {
      const sid = await invoke<string>('start_recording', { config });
      setSessionId(sid);
      setTransition(null);
      setRecording(true);
      setElapsed(0);
      invoke('show_overlay').catch(() => {});
      showToast(`녹화 시작: ${sid}`, 'ok');
    } catch (e) {
      setTransition(null);
      showToast(`녹화 시작 실패: ${e}`, 'err');
    }
  }, [showToast]);

  const stopRecording = useCallback(async () => {
    setTransition('stopping');
    setRecording(false);
    invoke('hide_overlay').catch(() => {});
    try {
      const result = await invoke<any>('stop_recording');
      setTransition(null);
      const dur = result?.duration ? `${Math.round(result.duration)}초` : '';
      const frames = result?.frames ? `, ${result.frames} 프레임` : '';
      showToast(`녹화 완료${dur ? ` (${dur}${frames})` : ''}`, 'ok');
      setRefreshKey(k => k + 1);
    } catch (e) {
      setTransition(null);
      showToast(`녹화 중지 오류: ${e}`, 'err');
    }
  }, [showToast]);

  const fmtElapsed = (s: number) => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
      : `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  };

  const win = getCurrentWindow();

  const captureScreen = (
    <CaptureScreen
      recording={recording}
      transition={transition}
      onStart={startRecording}
      onStop={stopRecording}
      elapsed={elapsed}
      fmtElapsed={fmtElapsed}
      sessionId={sessionId}
      configRef={captureConfigRef}
      hubConfigured={hub.configured}
      hubUrl={hub.url}
      hubToken={hub.token}
      showToast={showToast}
      liveStatus={liveStatus}
      lastSession={localSessions[0] ?? null}
    />
  );

  return (
    <div className="tbd-app">
      <div className="tbd-window">
        <div className="tbd-titlebar--custom" data-tauri-drag-region>
          <a className="tbd-brand" href="#" onClick={e => { e.preventDefault(); setRoute('capture'); }} style={{ WebkitAppRegion: 'no-drag' } as any}>
            <div className="sidebar__brand-mark" style={{ width: 20, height: 20, borderRadius: 5 }} />
            <span style={{ fontWeight: 600, fontSize: 13 }}>Trailbox</span>
          </a>
          <div className="tbd-tabs" style={{ WebkitAppRegion: 'no-drag' } as any}>
            {TABS.map(t => (
              <button key={t.key} className={`tbd-tab ${route === t.key ? 'active' : ''}`} onClick={() => setRoute(t.key)}>
                {t.icon()}<span>{t.label}</span>
              </button>
            ))}
          </div>
          {recording && (
            <span className="tbd-rec-pill" style={{ marginLeft: 12 }}>
              <span className="dot" />REC {fmtElapsed(elapsed)}
            </span>
          )}
          <div className="tbd-titlebar__controls" style={{ WebkitAppRegion: 'no-drag' } as any}>
            <ThemeToggle />
            <button onClick={() => win.minimize()} title="최소화">{Icon.Minimize()}</button>
            <button onClick={() => win.toggleMaximize()} title={maximized ? '이전 크기로' : '최대화'}>{Icon.Maximize()}</button>
            <button className="close" onClick={() => win.close()} title="닫기">{Icon.Close()}</button>
          </div>
        </div>
        <div className="tbd-body no-side">
          <div className="tbd-main">
            <div className="content" style={{ display: route === 'capture' ? undefined : 'none' }}>{captureScreen}</div>
            <div className="content" style={{ display: route === 'sessions' ? undefined : 'none' }}><SessionsScreen hub={hub} localSessions={localSessions} /></div>
            <div className="content" style={{ display: route === 'hub' ? undefined : 'none' }}><HubSettingsScreen hub={hub} setHub={setHub} /></div>
          </div>
        </div>
      </div>

      {toasts.length > 0 && (
        <div style={{ position: 'fixed', bottom: 20, left: '50%', transform: 'translateX(-50%)', zIndex: 300, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {toasts.map(t => (
            <div key={t.id} className={`tbd-status tbd-status--${t.tone}`} style={{ padding: '8px 16px', borderRadius: 8, boxShadow: 'var(--shadow-pop)', minWidth: 240, textAlign: 'center', animation: 'tbd-toast-in 0.2s ease-out' }}>
              {t.msg}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
