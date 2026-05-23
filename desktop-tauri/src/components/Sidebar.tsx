import { Icon } from './Icon';
import type { Route } from '../App';
import type { HubState } from '../data/mock';

type Props = {
  route: Route;
  setRoute: (r: Route) => void;
  recording: boolean;
  hub: HubState;
};

const NAV: { group: string; items: { key: Route; label: string; icon: (p?: any) => React.ReactNode }[] }[] = [
  { group: 'CAPTURE', items: [{ key: 'capture', label: '캡처', icon: Icon.Capture }] },
  { group: 'DATA', items: [{ key: 'sessions', label: '세션', icon: Icon.Sessions }] },
  { group: 'SYNC', items: [{ key: 'hub', label: 'Hub 설정', icon: Icon.Hub }] },
];

export function Sidebar({ route, setRoute, recording, hub }: Props) {
  return (
    <aside className="sidebar">
      <a className="sidebar__brand" href="#" onClick={e => { e.preventDefault(); setRoute('capture'); }}>
        <div className="sidebar__brand-mark" />
        <div className="sidebar__brand-text">
          Trailbox
          <small>Desktop</small>
        </div>
      </a>

      {NAV.map(g => (
        <div className="sidebar__group" key={g.group}>
          <div className="sidebar__group-label">{g.group}</div>
          {g.items.map(item => (
            <a
              key={item.key}
              className={`nav-item ${route === item.key ? 'active' : ''}`}
              href="#"
              onClick={e => { e.preventDefault(); setRoute(item.key); }}
            >
              {item.icon()}
              <span>{item.label}</span>
              {item.key === 'capture' && recording && (
                <span className="nav-badge" style={{ background: 'var(--danger)', width: 8, height: 8, minWidth: 8, padding: 0 }} />
              )}
              {item.key === 'sessions' && (
                <span className="nav-badge">6</span>
              )}
              {item.key === 'hub' && hub.configured && (
                <span className="tbd-badge tbd-badge--success" style={{ marginLeft: 'auto', height: 16, fontSize: '9.5px' }}>
                  <span className="dot" style={{ width: 4, height: 4, background: 'var(--success)', borderRadius: '50%' }} />
                  연결됨
                </span>
              )}
            </a>
          ))}
        </div>
      ))}

      <div className="sidebar__hub-status">
        {hub.configured ? (
          <>
            <div className="label">HUB</div>
            <div className="value">{hub.username}</div>
            <div className="sub">{hub.url}</div>
          </>
        ) : (
          <>
            <div className="label">HUB</div>
            <div className="sub">연결 안 됨</div>
          </>
        )}
      </div>
    </aside>
  );
}
