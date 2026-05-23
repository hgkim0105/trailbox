export function CaptureScreen() {
  return (
    <div>
      <div className="section-header">
        <div>
          <h1>캡처</h1>
          <p>대상 애플리케이션 · 캡처 대상 · 녹화 시작</p>
        </div>
      </div>

      <div className="tbd-card">
        <div className="tbd-card__head">
          <h3>대상 애플리케이션</h3>
        </div>
        <div className="tbd-card__body">
          <div className="tbd-stub">
            <h2>Capture 화면 stub</h2>
            <p>
              <code>core/screen_recorder.py</code>, <code>core/process_detector.py</code>,
              <code>core/adb.py</code> 와 IPC로 연결 예정.
            </p>
            <p>Replaces <code>ui/launcher_panel.py</code> + <code>ui/recorder_panel.py</code>.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
