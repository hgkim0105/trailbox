// ============================================================
// Canvas root — arranges all desktop artboards on the design canvas
// ============================================================
const { useState: useStateRoot } = React;

function CanvasRoot() {
  return (
    <window.DesignCanvas>
      <window.DCSection
        id="main-window"
        title="Trailbox 데스크탑 — 메인 윈도우"
        subtitle="1200×800 · Hub 디자인 시스템 + 데스크탑 밀도 조정. 사이드바 / 탭으로 캡처·세션·Hub 전환"
      >
        <window.DCArtboard id="main-native" label="A · Native chrome (Windows 타이틀바)" width={1200} height={800}>
          <window.DesktopApp chrome="native" initialRoute="capture" />
        </window.DCArtboard>

        <window.DCArtboard id="main-custom" label="B · Custom chrome (Tauri 스타일, 통합 탭)" width={1200} height={800}>
          <window.DesktopApp chrome="custom" initialRoute="capture" />
        </window.DCArtboard>
      </window.DCSection>

      <window.DCSection
        id="states"
        title="앱 상태별 — Custom chrome"
        subtitle="같은 윈도우의 다른 모드 · 녹화 중 / 세션 화면 / Hub 화면"
      >
        <window.DCArtboard id="state-recording" label="녹화 중 (Capture · REC pill)" width={1200} height={800}>
          <window.DesktopApp chrome="custom" initialRoute="capture" initialRecording={true} />
        </window.DCArtboard>

        <window.DCArtboard id="state-sessions" label="세션 화면 (로컬+Hub 통합)" width={1200} height={800}>
          <window.DesktopApp chrome="custom" initialRoute="sessions" />
        </window.DCArtboard>

        <window.DCArtboard id="state-hub" label="Hub 설정 화면" width={1200} height={800}>
          <window.DesktopApp chrome="custom" initialRoute="hub" />
        </window.DCArtboard>
      </window.DCSection>

      <window.DCSection
        id="viewer"
        title="Session Viewer (viewer.html) — 녹화 후 자동 생성되는 자체완결 페이지"
        subtitle="영상 + 메트릭 차트 + 이벤트 타임라인. 더블클릭하면 OS 기본 브라우저로 열림"
      >
        <window.DCArtboard id="session-viewer" label="Session Viewer · 1280×800" width={1280} height={800}>
          <ViewerEmbed />
        </window.DCArtboard>
      </window.DCSection>

      <window.DCSection
        id="overlay"
        title="Recording Overlay"
        subtitle="녹화 중 데스크탑 전체에 떠 있는 always-on-top 위젯. click-through (마우스 이벤트는 통과)"
      >
        <window.DCArtboard id="rec-overlay" label="녹화 중 오버레이 (작은 떠다니는 위젯)" width={560} height={360}>
          <window.TbdRecordingOverlay />
        </window.DCArtboard>
      </window.DCSection>
    </window.DesignCanvas>
  );
}

function ViewerEmbed() {
  return (
    <iframe
      src="Session Viewer.html"
      title="Session Viewer"
      style={{
        width: '100%', height: '100%',
        border: 0,
        display: 'block',
        background: 'oklch(0.155 0.012 275)',
      }}
    />
  );
}

window.CanvasRoot = CanvasRoot;

ReactDOM.createRoot(document.getElementById('root')).render(<CanvasRoot />);
