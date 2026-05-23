export function SessionsScreen() {
  return (
    <div>
      <div className="section-header">
        <div>
          <h1>세션</h1>
          <p>로컬 · Hub · 업로드 / 공유 / 뷰어</p>
        </div>
      </div>

      <div className="tbd-card">
        <div className="tbd-card__head">
          <h3>세션 목록</h3>
        </div>
        <div className="tbd-card__body">
          <div className="tbd-stub">
            <h2>Sessions 화면 stub</h2>
            <p>
              로컬: <code>output/*/session_meta.json</code> 읽기.
              Hub: <code>HubClient.list_sessions()</code> 호출.
            </p>
            <p>Replaces <code>ui/session_picker.py</code> + <code>ui/remote_session_picker.py</code>.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
