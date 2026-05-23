// ============================================================
// Capture screen — launcher_panel + recorder_panel merged
// ============================================================
const { useState: useStateCap, useMemo: useMemoCap } = React;

function TbdCaptureScreen({ recording, transition, onStart, onStop, elapsed }) {
  const D = window.TrailboxDesktopData;
  const I = window.Icons;

  const [target, setTarget] = useStateCap('window'); // monitor | window | android
  const [exe, setExe] = useStateCap('C:\\Games\\Aurora\\Aurora.exe');
  const [logDir, setLogDir] = useStateCap('C:\\Games\\Aurora\\Saved\\Logs');
  const [extraDirs, setExtraDirs] = useStateCap(['\\\\fileserver\\game-server-logs\\dev']);
  const [recursive, setRecursive] = useStateCap(true);
  const [exts, setExts] = useStateCap('log, txt');
  const [hwnd, setHwnd] = useStateCap(D.DESKTOP_WINDOWS[0].hwnd);
  const [serial, setSerial] = useStateCap(D.DESKTOP_ANDROID[0].serial);
  const [backend, setBackend] = useStateCap('auto');
  const [fps, setFps] = useStateCap(30);
  const [audio, setAudio] = useStateCap(true);
  const [input, setInput] = useStateCap(true);
  const [metrics, setMetrics] = useStateCap(true);
  const [autoUpload, setAutoUpload] = useStateCap(true);

  return (
    <>
      <div className="tbd-section-head">
        <h2>캡처 준비</h2>
        <span className="sub">대상을 정하고 녹화를 시작하세요</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button className="tbd-btn tbd-btn--ghost tbd-btn--sm"><I.Settings /> 설정</button>
        </div>
      </div>

      <div className="tbd-capture">
        {/* ── Left column ────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>

          {/* Target app */}
          <section className="tbd-card">
            <div className="tbd-card__head"><h3>대상 애플리케이션</h3></div>
            <div className="tbd-card__body">
              <div className="tbd-row">
                <label className="tbd-row__label">실행 파일</label>
                <input className="tbd-input mono" value={exe} onChange={e => setExe(e.target.value)} />
                <button className="tbd-btn tbd-btn--sm"><I.Document /> 찾기</button>
                <button className="tbd-btn tbd-btn--sm tbd-btn--primary">앱 실행</button>
              </div>

              <div className="tbd-row">
                <label className="tbd-row__label">로그 폴더</label>
                <input className="tbd-input mono" value={logDir} onChange={e => setLogDir(e.target.value)} />
                <button className="tbd-btn tbd-btn--sm"><I.Document /> 찾기</button>
                <button className="tbd-btn tbd-btn--sm"><I.Search /> 창 찾기</button>
              </div>

              <div className="tbd-row" style={{ alignItems: 'flex-start' }}>
                <label className="tbd-row__label" style={{ marginTop: 4 }}>추가 폴더</label>
                <div style={{ flex: 1 }}>
                  <ul className="tbd-extra-list">
                    {extraDirs.map((d, i) => (
                      <li key={i} className="tbd-extra-item">{d}</li>
                    ))}
                  </ul>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="tbd-btn tbd-btn--sm"
                      onClick={() => setExtraDirs([...extraDirs, '\\\\fileserver\\new-share'])}>
                      <I.Plus /> 폴더 추가
                    </button>
                    <button className="tbd-btn tbd-btn--sm"
                      onClick={() => setExtraDirs(extraDirs.slice(0, -1))}
                      disabled={extraDirs.length === 0}>− 제거</button>
                  </div>
                </div>
              </div>

              <div className="tbd-row" style={{ gap: 16 }}>
                <label className="tbd-check" style={{ padding: 0 }}>
                  <input type="checkbox" checked={recursive} onChange={e => setRecursive(e.target.checked)} />
                  <span className="tbd-check__main">하위 폴더까지 스캔</span>
                </label>
                <span style={{ fontSize: 12, color: 'var(--fg-2)' }}>확장자:</span>
                <input className="tbd-input mono" style={{ maxWidth: 160, flex: 'none' }}
                  value={exts} onChange={e => setExts(e.target.value)} placeholder="log, txt" />
              </div>
            </div>
          </section>

          {/* Capture target */}
          <section className="tbd-card">
            <div className="tbd-card__head"><h3>캡처 대상</h3></div>
            <div className="tbd-card__body">
              <div className="tbd-radio-group">
                <button className={`tbd-radio ${target === 'monitor' ? 'active' : ''}`} onClick={() => setTarget('monitor')}>
                  <I.Grid /> 전체 모니터
                </button>
                <button className={`tbd-radio ${target === 'window' ? 'active' : ''}`} onClick={() => setTarget('window')}>
                  <I.PC /> 특정 창 (WGC)
                </button>
                <button className={`tbd-radio ${target === 'android' ? 'active' : ''}`} onClick={() => setTarget('android')}>
                  <I.Phone /> Android (scrcpy)
                </button>
              </div>

              {target === 'window' && (
                <>
                  <div className="tbd-row">
                    <label className="tbd-row__label">창</label>
                    <select className="tbd-input" value={hwnd} onChange={e => setHwnd(parseInt(e.target.value))} style={{ flex: 1 }}>
                      {D.DESKTOP_WINDOWS.map(w => (
                        <option key={w.hwnd} value={w.hwnd}>{w.label}</option>
                      ))}
                    </select>
                    <button className="tbd-btn tbd-btn--sm"><I.Search /> 새로고침</button>
                  </div>
                  <div className="tbd-row">
                    <label className="tbd-row__label"></label>
                    <button className="tbd-btn tbd-btn--sm" style={{ flex: 'none' }}>🎯 창 클릭으로 선택</button>
                    <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>또는 단축키 <kbd className="kbd">Ctrl+Shift+P</kbd></span>
                  </div>
                </>
              )}

              {target === 'android' && (
                <>
                  <div className="tbd-row">
                    <label className="tbd-row__label">디바이스</label>
                    <select className="tbd-input" value={serial} onChange={e => setSerial(e.target.value)} style={{ flex: 1 }}>
                      {D.DESKTOP_ANDROID.map(d => (
                        <option key={d.serial} value={d.serial}>{d.label} · {d.serial}</option>
                      ))}
                    </select>
                    <button className="tbd-btn tbd-btn--sm"><I.Search /> 새로고침</button>
                  </div>
                  <div className="tbd-row" style={{ gap: 8 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--success)', marginLeft: 88 }} />
                    <span style={{ fontSize: 11.5, color: 'var(--success)' }}>
                      Android 디바이스 {D.DESKTOP_ANDROID.length}대 연결됨
                    </span>
                  </div>
                  <div className="tbd-row">
                    <label className="tbd-row__label">영상 백엔드</label>
                    <select className="tbd-input" value={backend} onChange={e => setBackend(e.target.value)} style={{ flex: 1 }}>
                      <option value="auto">auto · SDK 감지 + 첫 프레임 폴백</option>
                      <option value="scrcpy">scrcpy · 고화질 + 오디오</option>
                      <option value="screenrecord">screenrecord · Android 16+ 호환, 영상만</option>
                    </select>
                  </div>
                </>
              )}

              {target === 'monitor' && (
                <div style={{ padding: '8px 0', fontSize: 12, color: 'var(--muted)' }}>
                  주 모니터 (0번) 전체를 DXGI Desktop Duplication로 캡처합니다.
                </div>
              )}

              {/* Options */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, marginTop: 8 }}>
                <label className="tbd-check">
                  <input type="checkbox" checked={fps === 60} onChange={() => {}} style={{ display: 'none' }} />
                  <div>
                    <div className="tbd-check__main" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      최대 fps
                      <select value={fps} onChange={e => setFps(parseInt(e.target.value))}
                              style={{ fontSize: 11.5, padding: '1px 4px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--surface)', color: 'var(--fg)' }}>
                        {[10, 15, 24, 30, 60].map(v => <option key={v} value={v}>{v} fps</option>)}
                      </select>
                    </div>
                    <div className="tbd-check__desc">VFR이라 실제 fps는 소스에 따라 변함</div>
                  </div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={audio} onChange={e => setAudio(e.target.checked)} disabled={target === 'android'} />
                  <div>
                    <div className="tbd-check__main">시스템 사운드 (loopback)</div>
                    <div className="tbd-check__desc">{target === 'android' ? '— Android는 백엔드가 자동 처리' : 'WASAPI loopback · AAC'}</div>
                  </div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={input} onChange={e => setInput(e.target.checked)} />
                  <div>
                    <div className="tbd-check__main">입력 기록</div>
                    <div className="tbd-check__desc">{target === 'android' ? '터치 + 볼륨/전원 키 (getevent)' : '키보드 + 마우스 (pynput)'}</div>
                  </div>
                </label>
                <label className="tbd-check">
                  <input type="checkbox" checked={metrics} onChange={e => setMetrics(e.target.checked)} />
                  <div>
                    <div className="tbd-check__main">프로세스 텔레메트리</div>
                    <div className="tbd-check__desc">{target === 'android' ? 'CPU/RSS + jank + frame time' : 'CPU/GPU/RAM/VRAM · 1 Hz'}</div>
                  </div>
                </label>
              </div>
            </div>
          </section>
        </div>

        {/* ── Right column: record control + status ─── */}
        <aside className="tbd-status-panel">
          <button
            className={`tbd-record-btn ${recording ? 'recording' : ''} ${transition ? 'transition' : ''}`}
            onClick={recording ? onStop : onStart}
            disabled={!!transition}
          >
            <div className="tbd-record-btn__dot" />
            <div className="tbd-record-btn__label">
              {transition === 'starting' && '준비 중…'}
              {transition === 'stopping' && '마무리 중…'}
              {!transition && recording && '녹화 중지'}
              {!transition && !recording && '녹화 시작'}
            </div>
            <div className="tbd-record-btn__sub">
              {recording ? formatElapsed(elapsed) : 'Ctrl+Alt+R'}
            </div>
          </button>

          <label className="tbd-check" style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}>
            <input type="checkbox" checked={autoUpload} onChange={e => setAutoUpload(e.target.checked)} />
            <div>
              <div className="tbd-check__main">종료 시 Hub 자동 업로드</div>
              <div className="tbd-check__desc">Hub URL 미설정이면 조용히 건너뜀</div>
            </div>
          </label>

          <section className="tbd-card">
            <div className="tbd-card__head"><h3>현재 세션</h3></div>
            <div className="tbd-card__body">
              {recording ? (
                <dl className="tbd-meta-list">
                  <dt>세션 ID</dt><dd className="tbd-mono" style={{ fontSize: 11 }}>{makeSessionId(elapsed)}</dd>
                  <dt>경과</dt><dd>{formatElapsed(elapsed)}</dd>
                  <dt>프레임</dt><dd>{Math.floor(elapsed * (fps * 0.95)).toLocaleString()}</dd>
                  <dt>이벤트</dt><dd>{Math.floor(elapsed * 13.6).toLocaleString()}</dd>
                  <dt>현재 CPU</dt><dd>{(38 + Math.sin(elapsed / 5) * 18).toFixed(0)}%</dd>
                  <dt>현재 RAM</dt><dd>{(6.4 + Math.sin(elapsed / 7) * 0.3).toFixed(1)} GB</dd>
                </dl>
              ) : (
                <div style={{ color: 'var(--muted)', fontSize: 12 }}>
                  녹화를 시작하면 실시간 메트릭이 표시됩니다.
                </div>
              )}

              {recording && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 10.5, color: 'var(--muted)', letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 3 }}>CPU · 최근 30초</div>
                  <MiniSpark seed={elapsed} color="oklch(0.6 0.18 25)" />
                </div>
              )}
            </div>
          </section>

          <section className="tbd-card">
            <div className="tbd-card__head"><h3>마지막 세션</h3></div>
            <div className="tbd-card__body">
              <div className="tbd-mono" style={{ fontSize: 11.5, marginBottom: 4 }}>{window.TrailboxDesktopData.DESKTOP_SESSIONS[0].session_id}</div>
              <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 8 }}>
                {window.TrailboxDesktopData.DESKTOP_SESSIONS[0].started_rel} · {formatElapsed(window.TrailboxDesktopData.DESKTOP_SESSIONS[0].duration)}
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                <button className="tbd-btn tbd-btn--sm" style={{ flex: 1 }}><I.Eye /> 뷰어</button>
                <button className="tbd-btn tbd-btn--sm" style={{ flex: 1 }}><I.Share /> 공유</button>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}

function formatElapsed(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function makeSessionId(elapsed) {
  const base = '20260523-114108';
  return `${base}-7af3`;
}

// Tiny inline sparkline that uses elapsed as a hint for live feel
function MiniSpark({ seed = 0, color }) {
  const pts = useMemoCap(() => {
    const out = [];
    let v = 50;
    for (let i = 0; i < 40; i++) {
      v += (Math.sin((i + seed) * 0.7) + (Math.random() - 0.5)) * 6;
      v = Math.max(15, Math.min(85, v));
      out.push(v);
    }
    return out;
  }, [seed]);

  const path = pts.map((v, i) => `${i * (200 / (pts.length - 1))},${100 - v}`).join(' ');
  return (
    <svg viewBox="0 0 200 100" preserveAspectRatio="none" className="tbd-mini-spark">
      <polyline points={path} fill="none" stroke={color} strokeWidth="1.4" />
    </svg>
  );
}

window.TbdCaptureScreen = TbdCaptureScreen;
