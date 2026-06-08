import { useState, useEffect, useMemo, useCallback, type MutableRefObject } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { confirm } from '@tauri-apps/plugin-dialog';
import { Icon } from '../components/Icon';
import { WINDOWS, ANDROID_DEVICES, IOS_DEVICES } from '../data/mock';
import type { WindowInfo, AdbDevice, IOSDevice } from '../data/mock';

type Props = {
  recording: boolean;
  transition: 'starting' | 'stopping' | null;
  onStart: () => void;
  onStop: () => void;
  // Lookback ("instant replay") — opt-in second capture mode. UI guards on
  // window/monitor targets only (the bridge would refuse Android/iOS anyway).
  buffering: boolean;
  bufferSeconds: number;
  onBufferSecondsChange: (s: number) => void;
  onStartBuffering: () => void;
  onSaveLookback: () => void;
  onStopBuffering: () => void;
  recentCaptures: Array<{ session_id: string; at: number; duration: number }>;
  elapsed: number;
  fmtElapsed: (s: number) => string;
  sessionId: string | null;
  configRef: MutableRefObject<any>;
  hubConfigured: boolean;
  hubUrl: string;
  hubToken: string;
  showToast: (msg: string, tone: 'ok' | 'err' | 'info') => void;
  liveStatus: any;
  lastSession: any;
  autoUploadRef: MutableRefObject<boolean>;
};

type Target = 'monitor' | 'window' | 'android' | 'ios';

// iOS capture goes through AVFoundation, which is macOS-only. The Windows
// build has no working path for it, so hide the option entirely rather than
// let users select something that will always fail to start.
const IS_WINDOWS = typeof navigator !== 'undefined'
  && /Windows/i.test(navigator.userAgent ?? '');
const IOS_SUPPORTED = !IS_WINDOWS;

function MiniSpark({ color }: { color: string }) {
  const pts = useMemo(() => {
    const arr: number[] = [];
    let v = 30 + Math.random() * 40;
    for (let i = 0; i < 40; i++) { v += (Math.random() - 0.5) * 12; v = Math.max(5, Math.min(95, v)); arr.push(v); }
    return arr;
  }, []);
  const d = pts.map((v, i) => `${(i / 39) * 200},${100 - v}`).join(' ');
  return <svg className="tbd-mini-spark" viewBox="0 0 200 100" preserveAspectRatio="none"><polyline points={d} fill="none" stroke={color} strokeWidth="2" opacity="0.75" /></svg>;
}

export function CaptureScreen({
  recording, transition, onStart, onStop,
  buffering, bufferSeconds, onBufferSecondsChange, onStartBuffering, onSaveLookback, onStopBuffering, recentCaptures,
  elapsed, fmtElapsed, sessionId, configRef,
  hubConfigured, hubUrl, hubToken, showToast, liveStatus,
  lastSession: lastSessionProp, autoUploadRef,
}: Props) {
  const [mode, setMode] = useState<'record' | 'lookback'>('record');
  const [target, setTarget] = useState<Target>('window');
  // Lookback is desktop-only (Monitor/Window). Auto-revert to 'record' on
  // unsupported targets, and force-show the right mode while a session is
  // in flight so the visible UI matches what's actually running.
  const lookbackSupported = target === 'window' || target === 'monitor';
  useEffect(() => {
    if (!lookbackSupported && mode === 'lookback') setMode('record');
  }, [lookbackSupported, mode]);
  useEffect(() => {
    if (recording && mode !== 'record') setMode('record');
    if (buffering && mode !== 'lookback') setMode('lookback');
  }, [recording, buffering, mode]);

  // Flash the save button at the moment of click — not when the bridge's
  // "saved" event lands, since that gets polled at 1 Hz so the visual lag is
  // ~1s. The confirmation that the save actually succeeded shows up in the
  // recent-captures list below (slide-in animation on a new row).
  const [flashKey, setFlashKey] = useState(0);
  const onSaveClick = useCallback(() => {
    setFlashKey(k => k + 1);
    onSaveLookback();
  }, [onSaveLookback]);

  const fmtClock = (ms: number) => {
    const d = new Date(ms);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  };
  const [exe, setExe] = useState('');
  const [logDir, setLogDir] = useState('');
  const [extraDirs, setExtraDirs] = useState<string[]>([]);
  const [recursive, setRecursive] = useState(true);
  const [exts, setExts] = useState('log, txt');
  const [hwnd, setHwnd] = useState(0);
  const [serial, setSerial] = useState('');
  const [backend, setBackend] = useState<'auto' | 'scrcpy' | 'screenrecord'>('auto');
  const [fps, setFps] = useState(60);
  const [audio, setAudio] = useState(true);
  const [input, setInput] = useState(true);
  const [metrics, setMetrics] = useState(true);
  const [autoUpload, setAutoUpload] = useState(false);
  const [windows, setWindows] = useState<WindowInfo[]>(WINDOWS);
  const [devices, setDevices] = useState<AdbDevice[]>(ANDROID_DEVICES);
  const [iosUdid, setIosUdid] = useState('');
  const [iosBundle, setIosBundle] = useState('');
  const [iosDevices, setIosDevices] = useState<IOSDevice[]>(IOS_DEVICES);
  const [launching, setLaunching] = useState(false);
  const lastSession = lastSessionProp ? {
    id: lastSessionProp.session_id ?? '',
    dur: lastSessionProp.duration_seconds ? `${Math.floor(lastSessionProp.duration_seconds / 60)}:${String(Math.floor(lastSessionProp.duration_seconds % 60)).padStart(2, '0')}` : '',
  } : null;

  useEffect(() => {
    const selected = windows.find(w => w.hwnd === hwnd);
    const selectedIos = iosDevices.find(d => d.udid === iosUdid);

    let targetConfig: Record<string, unknown>;
    if (target === 'window') {
      targetConfig = { kind: 'window', hwnd, title: selected?.title ?? selected?.label ?? '' };
    } else if (target === 'android') {
      targetConfig = { kind: 'android', serial, backend, capture_audio: audio };
    } else if (target === 'ios') {
      // bridge_record.py expects (udid, device_name, bundle_id, capture_audio).
      // device_name is what AVFoundation matches on; bundle_id is best-effort
      // (None lets metrics skip the bundle filter — every running process is
      // candidate, useful when foreground detection is unavailable).
      targetConfig = {
        kind: 'ios',
        udid: iosUdid,
        device_name: selectedIos?.name ?? '',
        bundle_id: iosBundle || null,
        capture_audio: audio,
      };
    } else {
      targetConfig = { kind: 'monitor', index: 0 };
    }

    configRef.current = {
      target: targetConfig,
      exe_path: exe || selected?.exe_path || selected?.exe || '',
      log_dirs: [logDir, ...extraDirs].filter(Boolean),
      max_fps: fps, audio, input, metrics,
      log_recursive: recursive,
      log_extensions: exts.split(',').map(e => e.trim()).filter(Boolean).map(e => e.startsWith('.') ? e : `.${e}`),
    };
  });

  const refreshWindows = useCallback(async () => {
    try {
      const list = await invoke<WindowInfo[]>('enumerate_windows');
      if (Array.isArray(list) && list.length > 0) {
        setWindows(list);
        if (!hwnd || !list.find(w => w.hwnd === hwnd)) setHwnd(list[0].hwnd);
      }
    } catch { /* mock fallback */ }
  }, [hwnd]);

  const refreshDevices = useCallback(async () => {
    try {
      const list = await invoke<AdbDevice[]>('list_android_devices');
      if (Array.isArray(list) && list.length > 0) {
        setDevices(list);
        if (!list.find(d => d.serial === serial)) setSerial(list[0].serial);
      }
    } catch { /* mock fallback */ }
  }, [serial]);

  const refreshIosDevices = useCallback(async () => {
    try {
      // Real call replaces mock on first success. On failure (bridge spawn
      // failure, non-mac host, etc.) we keep the mock so the UI still renders
      // — matches the Android pattern.
      const list = await invoke<IOSDevice[]>('list_ios_devices');
      if (Array.isArray(list)) {
        setIosDevices(list);
        if (list.length > 0 && !list.find(d => d.udid === iosUdid)) {
          setIosUdid(list[0].udid);
        }
      }
    } catch { /* mock fallback */ }
  }, [iosUdid]);

  const pickWindowClick = async () => {
    try {
      const win = await invoke<WindowInfo>('pick_window_click');
      if (win && win.hwnd) {
        const exists = windows.find(w => w.hwnd === win.hwnd);
        if (!exists) setWindows(prev => [win, ...prev]);
        setHwnd(win.hwnd);
        if (win.exe_path) setExe(win.exe_path);
      }
    } catch { /* cancelled or error */ }
  };

  const findWindowForLog = async () => {
    if (!logDir) return;
    try {
      const win = await invoke<WindowInfo | null>('find_window_for_log', { logDir });
      if (win && win.hwnd) {
        const exists = windows.find(w => w.hwnd === win.hwnd);
        if (!exists) setWindows(prev => [win, ...prev]);
        setHwnd(win.hwnd);
      }
    } catch { /* not found */ }
  };

  const launchExe = async () => {
    if (!exe) return;
    setLaunching(true);
    try {
      await invoke('launch_exe', { exePath: exe });
      setTimeout(() => { refreshWindows(); setLaunching(false); }, 1500);
    } catch {
      setLaunching(false);
    }
  };

  const pickFile = async () => {
    try {
      const path = await invoke<string | null>('pick_file');
      if (path) setExe(path);
    } catch { /* no dialog */ }
  };

  const pickFolder = async () => {
    try {
      const path = await invoke<string | null>('pick_folder');
      if (path) setLogDir(path);
    } catch { /* no dialog */ }
  };

  const shareSession = async (sid: string) => {
    if (!hubConfigured) {
      showToast('Hub 연결이 필요합니다. Hub 탭에서 설정하세요.', 'err');
      return;
    }
    if (!(await confirm(`세션 "${sid}"을(를) Hub에 업로드하고 공유 링크를 발급하시겠습니까?`, { title: 'Hub 업로드 · 공유', kind: 'info' }))) return;
    showToast('Hub에 업로드 중…', 'info');
    try {
      await invoke('hub_upload', { url: hubUrl, token: hubToken, sessionId: sid });
      showToast('업로드 완료. 공유 링크 발급 중…', 'info');
      const result = await invoke<any>('hub_share', { url: hubUrl, token: hubToken, sessionId: sid });
      const shareUrl = result?.url || result?.share_url || '';
      if (shareUrl) {
        await navigator.clipboard.writeText(shareUrl);
        showToast(`공유 링크 클립보드에 복사됨`, 'ok');
      } else {
        showToast('공유 링크 발급 완료', 'ok');
      }
    } catch (e) {
      showToast(`공유 실패: ${e}`, 'err');
    }
  };

  // Defer window fetch so the UI renders immediately on cold start
  const [initialized, setInitialized] = useState(false);
  useEffect(() => {
    if (!initialized) {
      const t = setTimeout(() => { refreshWindows(); setInitialized(true); }, 1500);
      return () => clearTimeout(t);
    }
  }, [initialized]);

  // Fetch last session on mount

  const btnState = transition ? 'transition' : recording ? 'recording' : '';

  return (
    <div>
      <div className="section-header">
        <div><h1>캡처</h1><p>대상 애플리케이션 · 캡처 대상 · 녹화 시작</p></div>
      </div>

      <div className="capture-grid">
        <div>
          {/* Target Application */}
          <div className="tbd-card">
            <div className="tbd-card__head"><h3>대상 애플리케이션</h3></div>
            <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="tbd-form-row">
                <label>실행 파일</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input className="tbd-input mono" placeholder="exe 경로" value={exe} onChange={e => setExe(e.target.value)} style={{ flex: 1 }} />
                  <button className="tbd-btn" onClick={pickFile}>{Icon.Folder()}찾기</button>
                  <button className="tbd-btn tbd-btn--primary" onClick={launchExe} disabled={!exe || launching}>{Icon.Play()}{launching ? '실행 중…' : '앱 실행'}</button>
                </div>
              </div>
              <div className="tbd-form-row">
                <label>로그 폴더</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input className="tbd-input mono" placeholder="로그 폴더 경로" value={logDir} onChange={e => setLogDir(e.target.value)} style={{ flex: 1 }} />
                  <button className="tbd-btn" onClick={pickFolder}>{Icon.Folder()}찾기</button>
                  <button className="tbd-btn" onClick={findWindowForLog} disabled={!logDir}>{Icon.Search()}창 찾기</button>
                </div>
              </div>
              {extraDirs.length > 0 && (
                <div className="tbd-form-row">
                  <label>추가 폴더</label>
                  <div style={{ maxHeight: 88, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {extraDirs.map((d, i) => (
                      <div key={i} style={{ display: 'flex', gap: 4 }}>
                        <input className="tbd-input mono" value={d} onChange={e => { const v = e.target.value; setExtraDirs(x => x.map((old, j) => j === i ? v : old)); }} style={{ flex: 1 }} />
                        <button className="tbd-btn tbd-btn--sm" onClick={async () => { try { const p = await invoke<string | null>('pick_folder'); if (p) setExtraDirs(x => x.map((old, j) => j === i ? p : old)); } catch {} }}>{Icon.Folder()}찾기</button>
                        <button className="tbd-btn tbd-btn--sm tbd-btn--icon" onClick={() => setExtraDirs(x => x.filter((_, j) => j !== i))}>{Icon.Close()}</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="tbd-form-row">
                <label></label>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <button className="tbd-btn tbd-btn--sm" onClick={async () => { try { const p = await invoke<string | null>('pick_folder'); setExtraDirs(x => [...x, p ?? '']); } catch { setExtraDirs(x => [...x, '']); } }}>{Icon.Plus()}폴더 추가</button>
                  <label className="tbd-check" style={{ padding: '2px 0' }}>
                    <input type="checkbox" checked={recursive} onChange={e => setRecursive(e.target.checked)} />
                    <span className="tbd-check__label">하위폴더 포함</span>
                  </label>
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                    <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>확장자</span>
                    <input className="tbd-input mono" value={exts} onChange={e => setExts(e.target.value)} style={{ width: 100 }} />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Capture Target */}
          <div className="tbd-card">
            <div className="tbd-card__head"><h3>캡처 대상</h3></div>
            <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div className="tbd-radio-group">
                <button className={`tbd-radio ${target === 'monitor' ? 'active' : ''}`} onClick={() => setTarget('monitor')}>{Icon.PC()}전체 모니터</button>
                <button className={`tbd-radio ${target === 'window' ? 'active' : ''}`} onClick={() => setTarget('window')}>{Icon.Window()}특정 창 (WGC)</button>
                <button className={`tbd-radio ${target === 'android' ? 'active' : ''}`} onClick={() => { setTarget('android'); refreshDevices(); }}>{Icon.Phone()}Android</button>
                {IOS_SUPPORTED && (
                  <button className={`tbd-radio ${target === 'ios' ? 'active' : ''}`} onClick={() => { setTarget('ios'); refreshIosDevices(); }}>{Icon.Phone()}iOS</button>
                )}
              </div>

              {target === 'window' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <select className="tbd-select" value={hwnd} onChange={e => setHwnd(Number(e.target.value))} style={{ flex: 1 }}>
                      {windows.map(w => <option key={w.hwnd} value={w.hwnd}>{w.label}</option>)}
                    </select>
                    <button className="tbd-btn tbd-btn--icon" onClick={refreshWindows}>{Icon.Refresh()}</button>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <button className="tbd-btn" onClick={pickWindowClick}>{Icon.Crosshair()}창 클릭으로 선택</button>
                    <span style={{ fontSize: 11, color: 'var(--subtle)' }}>
                      <kbd style={{ padding: '1px 4px', border: '1px solid var(--border)', borderRadius: 3, fontFamily: 'Geist Mono', fontSize: 10 }}>Ctrl+Shift+P</kbd>
                    </span>
                  </div>
                </div>
              )}

              {target === 'android' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <select className="tbd-select" value={serial} onChange={e => setSerial(e.target.value)} style={{ flex: 1 }}>
                      {devices.map(d => <option key={d.serial} value={d.serial}>{d.label}</option>)}
                    </select>
                    <button className="tbd-btn tbd-btn--icon" onClick={refreshDevices}>{Icon.Refresh()}</button>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11.5 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--success)', flexShrink: 0 }} />
                    <span style={{ color: 'var(--success)' }}>{devices.filter(d => d.online).length}개 디바이스 연결됨</span>
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>백엔드</span>
                    <div className="tbd-radio-group" style={{ flex: 0 }}>
                      {(['auto', 'scrcpy', 'screenrecord'] as const).map(b => (
                        <button key={b} className={`tbd-radio ${backend === b ? 'active' : ''}`} onClick={() => setBackend(b)}>{b}</button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {target === 'ios' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <select className="tbd-select" value={iosUdid} onChange={e => setIosUdid(e.target.value)} style={{ flex: 1 }}>
                      {iosDevices.length === 0 && <option value="">디바이스가 없습니다 — USB 연결 + 신뢰 + 새로고침</option>}
                      {iosDevices.map(d => <option key={d.udid || d.name} value={d.udid}>{d.label}</option>)}
                    </select>
                    <button className="tbd-btn tbd-btn--icon" onClick={refreshIosDevices}>{Icon.Refresh()}</button>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11.5 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: iosDevices.some(d => d.capturable) ? 'var(--success)' : 'var(--muted)', flexShrink: 0 }} />
                    <span style={{ color: iosDevices.some(d => d.capturable) ? 'var(--success)' : 'var(--muted)' }}>
                      {iosDevices.filter(d => d.capturable).length}개 디바이스 캡처 가능
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: 11.5, color: 'var(--muted)', minWidth: 60 }}>Bundle ID</span>
                    <input className="tbd-input mono" placeholder="com.example.app (비우면 전체 프로세스)" value={iosBundle} onChange={e => setIosBundle(e.target.value)} style={{ flex: 1 }} />
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.4 }}>
                    메트릭(CPU/RAM/GPU)을 잡으려면 별도 터미널에서 <code style={{ fontSize: 10.5 }}>sudo pymobiledevice3 remote tunneld</code> 실행 필요. 화면·로그는 영향 없음.
                  </div>
                </div>
              )}

              {target === 'monitor' && (
                <div style={{ fontSize: 12, color: 'var(--muted)', padding: '4px 0' }}>Primary monitor 0 · DXGI Desktop Duplication</div>
              )}

              <div className="options-grid" style={{ marginTop: 4 }}>
                <label className="tbd-check">
                  <input type="checkbox" checked readOnly />
                  <div>
                    <div className="tbd-check__label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      Max FPS
                      <select className="tbd-select" value={fps} onChange={e => setFps(Number(e.target.value))} style={{ width: 64, height: 20, fontSize: 11 }}>
                        {[10, 15, 24, 30, 60].map(v => <option key={v} value={v}>{v}</option>)}
                      </select>
                    </div>
                    <div className="tbd-check__desc">프레임 속도 상한</div>
                  </div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={audio} onChange={e => setAudio(e.target.checked)} />
                  <div><div className="tbd-check__label">시스템 사운드</div><div className="tbd-check__desc">루프백 오디오 캡처</div></div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={input} onChange={e => setInput(e.target.checked)} />
                  <div><div className="tbd-check__label">입력 기록</div><div className="tbd-check__desc">키보드 · 마우스 이벤트</div></div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={metrics} onChange={e => setMetrics(e.target.checked)} />
                  <div><div className="tbd-check__label">프로세스 텔레메트리</div><div className="tbd-check__desc">CPU · RAM · GPU 1Hz 샘플</div></div>
                </label>
              </div>
            </div>
          </div>
        </div>

        {/* Right: status panel.

            Mode tabs are always rendered so the user can always see both
            choices (the previous "hide while running" version made the tabs
            invisible when an action was in flight, which felt like the
            record button had vanished). Tabs cross-disable while a session
            is active so the user can't switch out from under the bridge. */}
        <div>
          {/* Mode tabs — always visible, prominent at the top of the panel. */}
          <div className="tbd-mode-tabs" role="tablist" aria-label="캡처 모드">
            <button
              role="tab"
              aria-selected={mode === 'record'}
              className={`tbd-mode-tab ${mode === 'record' ? 'active' : ''}`}
              onClick={() => setMode('record')}
              disabled={buffering}
              title={buffering ? '버퍼링 중에는 모드 전환 불가' : ''}
            >{Icon.Capture()}<span>녹화</span></button>
            <button
              role="tab"
              aria-selected={mode === 'lookback'}
              className={`tbd-mode-tab ${mode === 'lookback' ? 'active' : ''}`}
              onClick={() => setMode('lookback')}
              disabled={recording || !lookbackSupported}
              title={
                !lookbackSupported ? 'Windows 데스크탑 캡처만 지원'
                : recording ? '녹화 중에는 모드 전환 불가'
                : '직전 N초 저장 (NVIDIA ShadowPlay 스타일)'
              }
            >{Icon.Clock()}<span>직전 기록 저장</span></button>
          </div>

          {mode === 'record' && (
            <button
              className={`tbd-record-btn ${btnState}`}
              onClick={transition ? undefined : recording ? onStop : onStart}
              disabled={!!transition}
            >
              <div className="tbd-record-btn__dot" />
              <div className="tbd-record-btn__label">
                {transition === 'starting' ? '준비 중…' : transition === 'stopping' ? '마무리 중…' : recording ? '녹화 중지' : '녹화 시작'}
              </div>
              <div className="tbd-record-btn__sub">
                {recording ? fmtElapsed(elapsed) : <kbd>Ctrl+Alt+R</kbd>}
              </div>
            </button>
          )}

          {mode === 'lookback' && !buffering && (
            <>
              <button
                className={`tbd-record-btn ${transition ? 'transition' : ''}`}
                onClick={transition ? undefined : onStartBuffering}
                disabled={!!transition || !lookbackSupported}
              >
                <div className="tbd-record-btn__dot" />
                <div className="tbd-record-btn__label">
                  {transition === 'starting' ? '준비 중…' : '버퍼링 시작'}
                </div>
                <div className="tbd-record-btn__sub">
                  직전 {bufferSeconds}초를 항상 보관
                </div>
              </button>
              <div className="tbd-card" style={{ marginTop: 14 }}>
                <div className="tbd-card__body" style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>버퍼 길이</span>
                  <input
                    type="number"
                    className="tbd-input mono"
                    min={5}
                    max={300}
                    step={5}
                    value={bufferSeconds}
                    onChange={e => {
                      const v = parseInt(e.target.value || '30', 10);
                      if (!isNaN(v)) onBufferSecondsChange(Math.max(5, Math.min(300, v)));
                    }}
                    style={{ width: 80 }}
                  />
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>초 (5–300)</span>
                </div>
              </div>
            </>
          )}

          {mode === 'lookback' && buffering && (
            <>
              <button
                key={flashKey}
                className="tbd-record-btn recording lookback-save"
                onClick={transition ? undefined : onSaveClick}
                style={{ position: 'relative', overflow: 'hidden' }}
              >
                <div className="tbd-record-btn__dot" />
                <div className="tbd-record-btn__label">
                  {transition === 'stopping' ? '마무리 중…' : '✂ 지금 저장'}
                </div>
                <div className="tbd-record-btn__sub">
                  직전 {bufferSeconds}초 클립 · 저장 {recentCaptures.length}회
                </div>
              </button>

              <div className="tbd-card" style={{ marginTop: 10 }}>
                <div className="tbd-card__head" style={{ padding: '6px 12px' }}>
                  <h3 style={{ margin: 0, fontSize: 11.5 }}>
                    최근 저장 {recentCaptures.length > 0 && <span style={{ color: 'var(--muted)', fontWeight: 400 }}>· {recentCaptures.length}개</span>}
                  </h3>
                </div>
                <div className="tbd-card__body" style={{ padding: '6px 12px', maxHeight: 132, overflowY: 'auto' }}>
                  {recentCaptures.length === 0 ? (
                    <div style={{ fontSize: 11.5, color: 'var(--muted)', textAlign: 'center', padding: '8px 0' }}>
                      "지금 저장"을 누르면 직전 {bufferSeconds}초가 새 세션으로 기록됩니다
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {recentCaptures.slice(-5).reverse().map((c, i) => (
                        <div
                          key={`${c.at}-${i}`}
                          className="mono"
                          style={{
                            display: 'flex', gap: 8, alignItems: 'baseline',
                            fontSize: 11, padding: '3px 0',
                            animation: i === 0 ? 'tbd-toast-in 0.25s ease-out' : undefined,
                          }}
                        >
                          <span style={{
                            width: 6, height: 6, borderRadius: '50%',
                            background: 'var(--success)', flexShrink: 0,
                            alignSelf: 'center',
                          }} />
                          <span style={{ color: 'var(--muted)', minWidth: 58 }}>{fmtClock(c.at)}</span>
                          <span style={{ color: 'var(--fg-2)', minWidth: 36 }}>{Math.round(c.duration)}s</span>
                          <span style={{
                            flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap', color: 'var(--fg)',
                          }}>{c.session_id}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <button
                className="tbd-btn"
                onClick={onStopBuffering}
                disabled={!!transition}
                style={{ width: '100%', marginTop: 8 }}
              >버퍼링 중지</button>
            </>
          )}

          <div className="tbd-card" style={{ marginTop: 14 }}>
            <div className="tbd-card__body" style={{ padding: '8px 14px' }}>
              <label className="tbd-check" style={{ padding: 0 }}>
                <input type="checkbox" checked={autoUpload} onChange={e => { setAutoUpload(e.target.checked); autoUploadRef.current = e.target.checked; }} />
                <div><div className="tbd-check__label">자동 동기화</div><div className="tbd-check__desc">녹화 종료 시 Hub에 자동 동기화</div></div>
              </label>
            </div>
          </div>

          <div className="tbd-card" style={{ marginTop: 14 }}>
            <div className="tbd-card__head"><h3>현재 세션</h3></div>
            <div className="tbd-card__body">
              {recording ? (
                <>
                  <dl className="tbd-meta-list">
                    <dt>Session</dt><dd>{sessionId ?? '—'}</dd>
                    <dt>경과</dt><dd>{liveStatus?.elapsed ? `${Math.round(liveStatus.elapsed)}초` : fmtElapsed(elapsed)}</dd>
                    <dt>프레임</dt><dd>{(liveStatus?.frames ?? 0).toLocaleString()}</dd>
                    <dt>CPU</dt><dd>{liveStatus?.cpu_pct != null ? `${liveStatus.cpu_pct}%` : '—'}</dd>
                    <dt>RAM</dt><dd>{liveStatus?.rss_mb != null ? `${liveStatus.rss_mb.toFixed(1)} MB` : '—'}</dd>
                    <dt>GPU</dt><dd>{liveStatus?.gpu_pct != null ? `${liveStatus.gpu_pct}%` : '—'}</dd>
                    <dt>VRAM</dt><dd>{liveStatus?.gpu_vram_mb != null ? `${liveStatus.gpu_vram_mb.toFixed(0)} MB` : '—'}</dd>
                  </dl>
                  <div style={{ marginTop: 8 }}><MiniSpark color="oklch(0.65 0.18 25)" /></div>
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--muted)', fontSize: 12 }}>녹화 시작 후 여기에 라이브 메트릭이 표시됩니다</div>
              )}
            </div>
          </div>

          <div className="tbd-card" style={{ marginTop: 14 }}>
            <div className="tbd-card__head"><h3>마지막 세션</h3></div>
            <div className="tbd-card__body">
              {lastSession ? (
                <>
                  <dl className="tbd-meta-list">
                    <dt>Session</dt><dd>{lastSession.id}</dd>
                    <dt>길이</dt><dd>{lastSession.dur}</dd>
                  </dl>
                  <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                    <button className="tbd-btn tbd-btn--sm" onClick={() => invoke('open_viewer', { sessionId: lastSession.id }).catch(() => {})}>{Icon.Eye()}뷰어</button>
                    <button className="tbd-btn tbd-btn--sm" onClick={() => shareSession(lastSession.id)}>{Icon.Share()}공유</button>
                  </div>
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--muted)', fontSize: 12 }}>아직 녹화된 세션이 없습니다</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
