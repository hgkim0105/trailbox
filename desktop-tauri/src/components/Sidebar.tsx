import { Icon } from './Icon';
import type { Route } from '../App';

type Props = {
  route: Route;
  setRoute: (r: Route) => void;
};

const NAV: Array<{ key: Route; label: string; icon: React.ReactNode }> = [
  { key: 'capture', label: '캡처', icon: <Icon.Capture /> },
  { key: 'sessions', label: '세션', icon: <Icon.Sessions /> },
  { key: 'hub', label: 'Hub 설정', icon: <Icon.Hub /> },
];

export function Sidebar({ route, setRoute }: Props) {
  return (
    <aside className="sidebar">
      <a
        className="sidebar__brand"
        href="#"
        onClick={(e) => {
          e.preventDefault();
          setRoute('capture');
        }}
      >
        <div className="sidebar__brand-mark" />
        <div className="sidebar__brand-text">
          Trailbox
          <small>Desktop</small>
        </div>
      </a>

      {NAV.map((item) => (
        <a
          key={item.key}
          className={`nav-item ${route === item.key ? 'active' : ''}`}
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setRoute(item.key);
          }}
        >
          {item.icon}
          <span>{item.label}</span>
        </a>
      ))}

      <div className="sidebar__footer">
        <span>v0.0.0 · scaffold</span>
        <span style={{ color: 'var(--subtle)' }}>PyQt6 → Tauri 포팅 중</span>
      </div>
    </aside>
  );
}
