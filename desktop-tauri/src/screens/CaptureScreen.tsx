import { useState, useMemo } from 'react';
import { Icon } from '../components/Icon';
import { WINDOWS, ANDROID_DEVICES } from '../data/mock';

type Props = {
  recording: boolean;
  transition: 'starting' | 'stopping' | null;
  onStart: () => void;
  onStop: () => void;
  elapsed: number;
  fmtElapsed: (s: number) => string;
};

type Target = 'monitor' | 'window' | 'android';

function MiniSpark({ color }: { color: string }) {
  const pts = useMemo(() => {
    const n = 40;
    const arr: number[] = [];
    let v = 30 + Math.random() * 40;
    for (let i = 0; i < n; i++) {
      v += (Math.random() - 0.5) * 12;
      v = Math.max(5, Math.min(95, v));
      arr.push(v);
    }
    return arr;
  }, []);
  const d = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i / (pts.length - 1)) * 200},${100 - v}`).join(' ');
  return (
    <svg className="tbd-mini-spark" viewBox="0 0 200 100" preserveAspectRatio="none">
      <polyline points={d.replace(/[ML]/g, '')} fill="none" stroke={color} strokeWidth="2" opacity="0.75" />
    </svg>
  );
}

export function CaptureScreen({ recording, transition, onStart, onStop, elapsed, fmtElapsed }: Props) {
  const [target, setTarget] = useState<Target>('window');
  const [exe, setExe] = useState('');
  const [logDir, setLogDir] = useState('');
  const [extraDirs, setExtraDirs] = useState<string[]>([]);
  const [recursive, setRecursive] = useState(true);
  const [exts, setExts] = useState('log, txt');
  const [hwnd, setHwnd] = useState(WINDOWS[0].hwnd);
  const [serial, setSerial] = useState(ANDROID_DEVICES[0].serial);
  const [backend, setBackend] = useState<'auto' | 'scrcpy' | 'screenrecord'>('auto');
  const [fps, setFps] = useState(60);
  const [audio, setAudio] = useState(true);
  const [input, setInput] = useState(true);
  const [metrics, setMetrics] = useState(true);
  const [autoUpload, setAutoUpload] = useState(false);

  const btnState = transition ? 'transition' : recording ? 'recording' : '';

  return (
    <div>
      <div className="section-header">
        <div>
          <h1>캡처</h1>
          <p>대상 애플리케이션 · 캡처 대상 · 녹화 시작</p>
        </div>
      </div>

      <div className="capture-grid">
        {/* ── Left: config cards ── */}
        <div>
          {/* Card: Target Application */}
          <div className="tbd-card">
            <div className="tbd-card__head"><h3>대상 애플리케이션</h3></div>
            <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="tbd-form-row">
                <label>실행 파일</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input className="tbd-input mono" placeholder="exe 경로" value={exe} onChange={e => setExe(e.target.value)} style={{ flex: 1 }} />
                  <button className="tbd-btn">{Icon.Folder()}찾기</button>
                  <button className="tbd-btn tbd-btn--primary">{Icon.Play()}앱 실행</button>
                </div>
              </div>
              <div className="tbd-form-row">
                <label>로그 폴더</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input className="tbd-input mono" placeholder="로그 폴더 경로" value={logDir} onChange={e => setLogDir(e.target.value)} style={{ flex: 1 }} />
                  <button className="tbd-btn">{Icon.Folder()}찾기</button>
                  <button className="tbd-btn">{Icon.Search()}창 찾기</button>
                </div>
              </div>
              {extraDirs.length > 0 && (
                <div className="tbd-form-row">
                  <label>추가 폴더</label>
                  <div style={{ maxHeight: 88, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {extraDirs.map((d, i) => (
                      <div key={i} style={{ display: 'flex', gap: 4 }}>
                        <input className="tbd-input mono" value={d} readOnly style={{ flex: 1 }} />
                        <button className="tbd-btn tbd-btn--sm tbd-btn--icon" onClick={() => setExtraDirs(x => x.filter((_, j) => j !== i))}>
                          {Icon.Close()}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="tbd-form-row">
                <label></label>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <button className="tbd-btn tbd-btn--sm" onClick={() => setExtraDirs(x => [...x, ''])}>
                    {Icon.Plus()}폴더 추가
                  </button>
                  <label className="tbd-check" style={{ padding: '2px 0' }}>
                    <input type="checkbox" checked={recursive} onChange={e => setRecursive(e.target.checked)} />
                    <span className="tbd-check__label">하위 폴더</span>
                  </label>
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                    <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>확장자</span>
                    <input className="tbd-input mono" value={exts} onChange={e => setExts(e.target.value)} style={{ width: 100 }} />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Card: Capture Target */}
          <div className="tbd-card">
            <div className="tbd-card__head"><h3>캡처 대상</h3></div>
            <div className="tbd-card__body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div className="tbd-radio-group">
                <button className={`tbd-radio ${target === 'monitor' ? 'active' : ''}`} onClick={() => setTarget('monitor')}>
                  {Icon.PC()}전체 모니터
                </button>
                <button className={`tbd-radio ${target === 'window' ? 'active' : ''}`} onClick={() => setTarget('window')}>
                  {Icon.Window()}특정 창 (WGC)
                </button>
                <button className={`tbd-radio ${target === 'android' ? 'active' : ''}`} onClick={() => setTarget('android')}>
                  {Icon.Phone()}Android
                </button>
              </div>

              {target === 'window' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <select className="tbd-select" value={hwnd} onChange={e => setHwnd(Number(e.target.value))} style={{ flex: 1 }}>
                      {WINDOWS.map(w => <option key={w.hwnd} value={w.hwnd}>{w.label}</option>)}
                    </select>
                    <button className="tbd-btn tbd-btn--icon">{Icon.Refresh()}</button>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <button className="tbd-btn">{Icon.Crosshair()}창 클릭으로 선택</button>
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
                      {ANDROID_DEVICES.map(d => <option key={d.serial} value={d.serial}>{d.label}</option>)}
                    </select>
                    <button className="tbd-btn tbd-btn--icon">{Icon.Refresh()}</button>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11.5 }}>
                    <span className="dot" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--success)', flexShrink: 0 }} />
                    <span style={{ color: 'var(--success)' }}>{ANDROID_DEVICES.filter(d => d.online).length}개 디바이스 연결됨</span>
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

              {target === 'monitor' && (
                <div style={{ fontSize: 12, color: 'var(--muted)', padding: '4px 0' }}>
                  Primary monitor 0 · DXGI Desktop Duplication
                </div>
              )}

              <div className="options-grid" style={{ marginTop: 4 }}>
                <label className="tbd-check">
                  <input type="checkbox" checked={fps > 0} readOnly />
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
                  <div>
                    <div className="tbd-check__label">시스템 사운드</div>
                    <div className="tbd-check__desc">루프백 오디오 캡처</div>
                  </div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={input} onChange={e => setInput(e.target.checked)} />
                  <div>
                    <div className="tbd-check__label">입력 기록</div>
                    <div className="tbd-check__desc">키보드 · 마우스 이벤트</div>
                  </div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={metrics} onChange={e => setMetrics(e.target.checked)} />
                  <div>
                    <div className="tbd-check__label">프로세스 텔레메트리</div>
                    <div className="tbd-check__desc">CPU · RAM · GPU 1Hz 샘플</div>
                  </div>
                </label>
              </div>
            </div>
          </div>
        </div>

        {/* ── Right: status panel ── */}
        <div>
          {/* Record button */}
          <button
            className={`tbd-record-btn ${btnState}`}
            onClick={transition ? undefined : recording ? onStop : onStart}
          >
            <div className="tbd-record-btn__dot" />
            <div className="tbd-record-btn__label">
              {transition === 'starting' ? '준비 중…' : transition === 'stopping' ? '마무리 중…' : recording ? '녹화 중지' : '녹화 시작'}
            </div>
            <div className="tbd-record-btn__sub">
              {recording ? fmtElapsed(elapsed) : <kbd>Ctrl+Alt+R</kbd>}
            </div>
          </button>

          {/* Auto upload */}
          <div className="tbd-card" style={{ marginTop: 14 }}>
            <div className="tbd-card__body" style={{ padding: '8px 14px' }}>
              <label className="tbd-check" style={{ padding: 0 }}>
                <input type="checkbox" checked={autoUpload} onChange={e => setAutoUpload(e.target.checked)} />
                <div>
                  <div className="tbd-check__label">자동 업로드</div>
                  <div className="tbd-check__desc">녹화 종료 시 Hub에 자동 업로드</div>
                </div>
              </label>
            </div>
          </div>

          {/* Current session */}
          <div className="tbd-card" style={{ marginTop: 14 }}>
            <div className="tbd-card__head"><h3>현재 세션</h3></div>
            <div className="tbd-card__body">
              {recording ? (
                <>
                  <dl className="tbd-meta-list">
                    <dt>Session</dt><dd>aurora_20260523_120000</dd>
                    <dt>경과</dt><dd>{fmtElapsed(elapsed)}</dd>
                    <dt>프레임</dt><dd>{(elapsed * 30).toLocaleString()}</dd>
                    <dt>이벤트</dt><dd>{(elapsed * 26).toLocaleString()}</dd>
                    <dt>CPU</dt><dd>42%</dd>
                    <dt>RAM</dt><dd>2.1 GB</dd>
                  </dl>
                  <div style={{ marginTop: 8 }}>
                    <MiniSpark color="oklch(0.65 0.18 25)" />
                  </div>
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--muted)', fontSize: 12 }}>
                  녹화 시작 후 여기에 라이브 메트릭이 표시됩니다
                </div>
              )}
            </div>
          </div>

          {/* Last session */}
          <div className="tbd-card" style={{ marginTop: 14 }}>
            <div className="tbd-card__head"><h3>마지막 세션</h3></div>
            <div className="tbd-card__body">
              <dl className="tbd-meta-list">
                <dt>Session</dt><dd>aurora_20260523_114108</dd>
                <dt>시작</dt><dd>15분 전 · 8:07</dd>
              </dl>
              <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                <button className="tbd-btn tbd-btn--sm">{Icon.Eye()}뷰어</button>
                <button className="tbd-btn tbd-btn--sm">{Icon.Share()}공유</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
