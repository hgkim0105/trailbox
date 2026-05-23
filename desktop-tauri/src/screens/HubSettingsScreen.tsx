export function HubSettingsScreen() {
  return (
    <div>
      <div className="section-header">
        <div>
          <h1>Hub 설정</h1>
          <p>URL · 로그인 · 토큰 발급</p>
        </div>
      </div>

      <div className="tbd-card">
        <div className="tbd-card__head">
          <h3>연결</h3>
        </div>
        <div className="tbd-card__body">
          <div className="tbd-stub">
            <h2>Hub Settings stub</h2>
            <p>
              <code>HubClient.login()</code> + <code>issue_token()</code> 호출. 토큰은
              OS keychain (Tauri Stronghold)에 저장 예정.
            </p>
            <p>Replaces <code>ui/hub_dialogs.py</code>.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
