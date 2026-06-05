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
  const [buffering, setBuffering] = useState(false);
  const [bufferSeconds, setBufferSeconds] = useState(30);
  // Append-only list of lookback captures from the current buffering session,
  // newest last. Cleared on each fresh start_buffering so a previous run's
  // captures don't leak into the next one. Read-only for the UI — App drives
  // it via the drain_lookback_saved poll below.
  const [recentCaptures, setRecentCaptures] = useState<Array<{ session_id: string; at: number; duration: number }>>([]);
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
  const [remoteSessions, setRemoteSessions] = useState<any[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const captureConfigRef = useRef<any>(null);
  const autoUploadRef = useRef(false);

  // Fetch both local + Hub sessions, deferred on first mount
  useEffect(() => {
    const delay = refreshKey === 0 ? 2000 : 0;
    if (refreshKey === 0) setSessionsLoading(true);
    const t = setTimeout(() => {
      invoke<any[]>('list_local_sessions').then(list => {
        if (Array.isArray(list)) setLocalSessions(list);
      }).catch(() => {}).finally(() => setSessionsLoading(false));
      if (hub.configured && hub.token) {
        invoke<any[]>('hub_list_sessions', { url: hub.url, token: hub.token }).then(list => {
          if (Array.isArray(list)) setRemoteSessions(list);
        }).catch(() => {});
      }
    }, delay);
    return () => clearTimeout(t);
  }, [refreshKey]);

  // Background sync queue + auto cleanup on first load
  const syncRan = useRef(false);
  useEffect(() => {
    if (syncRan.current || !hub.configured || !hub.token) return;
    syncRan.current = true;
    invoke<any>('hub_sync_queue', { url: hub.url, token: hub.token })
      .then(r => {
        if (r?.uploaded > 0) {
          showToast(`${r.uploaded}개 세션 자동 동기화 완료`, 'ok');
        }
        // Auto cleanup after sync
        const policy = hub.cleanupPolicy || 'keep';
        if (policy !== 'keep') {
          invoke<any>('cleanup_synced_sessions', { policy })
            .then(cr => {
              if (cr?.deleted > 0) {
                showToast(`${cr.deleted}개 동기화 세션 정리됨`, 'info');
              }
            })
            .catch(() => {});
        }
        if (r?.uploaded > 0) setRefreshKey(k => k + 1);
      })
      .catch(() => {});
  }, [hub.configured, hub.token]);


  const showToast = useCallback((msg: string, tone: Toast['tone'] = 'info') => {
    const id = ++toastId;
    setToasts(t => [...t, { id, msg, tone }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500);
  }, []);

  useEffect(() => {
    // Tick both during recording and during lookback buffering — the bridge
    // emits "status" lines in both modes (frames/cpu for recording, captures/
    // buffer_seconds for lookback) and read_recording_status returns whichever
    // is currently active.
    if (!recording && !buffering) { setLiveStatus(null); return; }
    const id = setInterval(async () => {
      setElapsed(e => {
        const next = e + 1;
        invoke('sync_overlay_time', { elapsed: next }).catch(() => {});
        return next;
      });
      try {
        const s = await invoke<any>('read_recording_status');
        if (s) setLiveStatus(s);
        if (buffering) {
          // Drain any "saved" events that piled up so we can refresh the
          // session list + show a toast per capture + log them inline.
          const saved = await invoke<any[]>('drain_lookback_saved');
          if (Array.isArray(saved) && saved.length > 0) {
            const now = Date.now();
            const additions = saved.map(ev => ({
              session_id: ev?.session_id || '',
              at: now,
              duration: typeof ev?.duration === 'number' ? ev.duration : 0,
            }));
            for (const ev of additions) {
              showToast(`직전 ${Math.round(ev.duration)}초 저장됨: ${ev.session_id}`, 'ok');
            }
            setRecentCaptures(prev => [...prev, ...additions]);
            setRefreshKey(k => k + 1);
          }
        }
      } catch {}
    }, 1000);
    return () => clearInterval(id);
  }, [recording, buffering]);

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

  const startBuffering = useCallback(async () => {
    const config = captureConfigRef.current;
    if (!config) {
      showToast('캡처 설정을 먼저 구성하세요', 'err');
      return;
    }
    const target = config.target;
    if (target?.kind !== 'window' && target?.kind !== 'monitor') {
      showToast('직전 기록 저장은 모니터/창 캡처만 지원합니다', 'err');
      return;
    }
    setTransition('starting');
    setRecentCaptures([]);
    try {
      await invoke<number>('start_buffering', {
        config: { ...config, buffer_seconds: bufferSeconds },
      });
      setTransition(null);
      setBuffering(true);
      setElapsed(0);
      showToast(`버퍼링 시작 (${bufferSeconds}초 윈도우)`, 'ok');
    } catch (e) {
      setTransition(null);
      showToast(`버퍼링 시작 실패: ${e}`, 'err');
    }
  }, [showToast, bufferSeconds]);

  const saveLookbackNow = useCallback(async () => {
    try {
      await invoke('save_lookback_now');
      // The status loop above will drain "saved" events and toast them.
    } catch (e) {
      showToast(`저장 실패: ${e}`, 'err');
    }
  }, [showToast]);

  const stopBuffering = useCallback(async () => {
    setTransition('stopping');
    setBuffering(false);
    try {
      await invoke('stop_buffering');
      setTransition(null);
      showToast('버퍼링 중지', 'info');
      setRefreshKey(k => k + 1);
    } catch (e) {
      setTransition(null);
      showToast(`버퍼링 중지 오류: ${e}`, 'err');
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
      // Auto-upload if enabled
      if (autoUploadRef.current && hub.configured && result?.session_id) {
        showToast('Hub 동기화 중…', 'info');
        invoke('hub_upload', { url: hub.url, token: hub.token, sessionId: result.session_id })
          .then(() => {
            showToast('Hub 동기화 완료', 'ok');
            setRefreshKey(k => k + 1);
          })
          .catch((e) => showToast(`자동 동기화 실패: ${e}`, 'err'));
      }
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
      buffering={buffering}
      bufferSeconds={bufferSeconds}
      onBufferSecondsChange={setBufferSeconds}
      onStartBuffering={startBuffering}
      onSaveLookback={saveLookbackNow}
      onStopBuffering={stopBuffering}
      recentCaptures={recentCaptures}
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
      autoUploadRef={autoUploadRef}
    />
  );

  return (
    <div className="tbd-app">
      <div className="tbd-window">
        <div className="tbd-titlebar--custom" data-tauri-drag-region>
          <a className="tbd-brand" href="#" onClick={e => { e.preventDefault(); setRoute('capture'); }} style={{ WebkitAppRegion: 'no-drag' } as any}>
            <img src="/trailbox.png" alt="" style={{ width: 20, height: 20, borderRadius: 5 }} />
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
            <div className="content" style={{ display: route === 'sessions' ? undefined : 'none' }}><SessionsScreen hub={hub} localSessions={localSessions} remoteSessions={remoteSessions} sessionsLoading={sessionsLoading} onRefresh={() => setRefreshKey(k => k + 1)} /></div>
            <div className="content" style={{ display: route === 'hub' ? undefined : 'none' }}><HubSettingsScreen hub={hub} setHub={setHub} active={route === 'hub'} /></div>
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
