// ============================================================
// App chrome — Sidebar, Topbar, Layout shell
// ============================================================
const { useState: useState_chrome } = React;

function Sidebar({ route, setRoute, user, pendingCount }) {
  const I = window.Icons;
  const item = (key, label, icon, badge) => ({ key, label, icon, badge });
  const main = [
    item('sessions', '세션', <I.Sessions className="nav-icon" />),
  ];
  const adminItems = user.role === 'admin' ? [
    item('admin-users', '사용자', <I.Users className="nav-icon" />, pendingCount > 0 ? pendingCount : null),
    item('admin-settings', '시스템 설정', <I.Settings className="nav-icon" />),
    item('admin-audit', '감사 로그', <I.Audit className="nav-icon" />),
  ] : [];

  return (
    <aside className="sidebar">
      <a className="sidebar__brand" href="#" onClick={(e) => { e.preventDefault(); setRoute('sessions'); }}>
        <div className="sidebar__brand-mark" />
        <div className="sidebar__brand-text">
          Trailbox
          <small>Hub</small>
        </div>
      </a>

      <div className="sidebar__section-label">워크스페이스</div>
      {main.map(it => (
        <a key={it.key} className={`nav-item ${route === it.key ? 'active' : ''}`}
           href="#" onClick={(e) => { e.preventDefault(); setRoute(it.key); }}>
          {it.icon}<span>{it.label}</span>
          {it.badge != null && <span className="nav-badge">{it.badge}</span>}
        </a>
      ))}

      {adminItems.length > 0 && (
        <>
          <div className="sidebar__section-label">관리자</div>
          {adminItems.map(it => (
            <a key={it.key} className={`nav-item ${route === it.key ? 'active' : ''}`}
               href="#" onClick={(e) => { e.preventDefault(); setRoute(it.key); }}>
              {it.icon}<span>{it.label}</span>
              {it.badge != null && <span className="nav-badge">{it.badge}</span>}
            </a>
          ))}
        </>
      )}

      <div className="sidebar__user">
        <window.Avatar name={user.username} size="sm" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>{user.username}</div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>{user.role === 'admin' ? 'Administrator' : 'Member'}</div>
        </div>
        <button
          className="btn btn--ghost btn--sm btn--icon"
          title="계정"
          onClick={() => setRoute('account')}
        >
          <I.Account />
        </button>
      </div>
    </aside>
  );
}

function Topbar({ crumbs, actions, route, setRoute, onToggleTheme, theme }) {
  const I = window.Icons;
  return (
    <header className="topbar">
      <nav className="topbar__crumbs">
        {crumbs.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="sep"><I.Chevron width={12} height={12} /></span>}
            {c.to ? (
              <a href="#" onClick={(e) => { e.preventDefault(); setRoute(c.to); }} style={{ color: 'var(--muted)' }}>{c.label}</a>
            ) : (
              <strong>{c.label}</strong>
            )}
          </React.Fragment>
        ))}
      </nav>
      <div className="topbar__actions">
        {actions}
        <button
          className="btn btn--ghost btn--icon btn--sm"
          onClick={onToggleTheme}
          title={theme === 'dark' ? '라이트 모드' : '다크 모드'}
        >
          {theme === 'dark' ? <I.Sun /> : <I.Moon />}
        </button>
      </div>
    </header>
  );
}

window.Sidebar = Sidebar;
window.Topbar = Topbar;
