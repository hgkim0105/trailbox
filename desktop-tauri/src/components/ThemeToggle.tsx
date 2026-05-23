import { useEffect, useState } from 'react';
import { Icon } from './Icon';

const KEY = 'trailbox_theme';
type Theme = 'light' | 'dark';

function readInitial(): Theme {
  const root = document.documentElement;
  const cur = root.getAttribute('data-theme');
  if (cur === 'dark' || cur === 'light') return cur;
  return 'light';
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readInitial);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* private mode */
    }
  }, [theme]);

  return (
    <button
      type="button"
      onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      title={theme === 'dark' ? '라이트 모드' : '다크 모드'}
      aria-label="테마 전환"
      style={{
        width: 28,
        height: 28,
        borderRadius: 6,
        border: '1px solid var(--border)',
        background: 'var(--surface)',
        color: 'var(--fg-2)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {theme === 'dark' ? <Icon.Sun /> : <Icon.Moon />}
    </button>
  );
}
