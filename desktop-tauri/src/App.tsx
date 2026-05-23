import { useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { ThemeToggle } from './components/ThemeToggle';
import { CaptureScreen } from './screens/CaptureScreen';
import { SessionsScreen } from './screens/SessionsScreen';
import { HubSettingsScreen } from './screens/HubSettingsScreen';

export type Route = 'capture' | 'sessions' | 'hub';

const TITLES: Record<Route, string> = {
  capture: '캡처',
  sessions: '세션',
  hub: 'Hub 설정',
};

export default function App() {
  const [route, setRoute] = useState<Route>('capture');

  let screen: React.ReactNode;
  switch (route) {
    case 'capture':
      screen = <CaptureScreen />;
      break;
    case 'sessions':
      screen = <SessionsScreen />;
      break;
    case 'hub':
      screen = <HubSettingsScreen />;
      break;
  }

  return (
    <div className="app">
      <Sidebar route={route} setRoute={setRoute} />
      <main className="main">
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 20px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg)',
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600 }}>{TITLES[route]}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ThemeToggle />
          </div>
        </header>

        <div className="content">{screen}</div>
      </main>
    </div>
  );
}
