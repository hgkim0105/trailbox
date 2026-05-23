// ============================================================
// Shared UI Components — Trailbox Hub
// ============================================================
const { useState, useEffect, useRef, useMemo } = React;

// ── Button ─────────────────────────────────
function Button({ variant = 'default', size, icon, iconOnly, children, className = '', ...rest }) {
  const cls = [
    'btn',
    variant && variant !== 'default' ? `btn--${variant}` : '',
    size ? `btn--${size}` : '',
    iconOnly ? 'btn--icon' : '',
    className,
  ].filter(Boolean).join(' ');
  return React.createElement(
    'button',
    { className: cls, ...rest },
    icon, children
  );
}

// ── Badge ─────────────────────────────────
function Badge({ tone = 'neutral', dot, children, className = '' }) {
  return (
    <span className={`badge badge--${tone} ${className}`}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

// ── Avatar ─────────────────────────────────
const PALETTE_HUES = [282, 240, 200, 160, 110, 40, 20, 320, 260];
function Avatar({ name, size, square }) {
  const initial = (name || '?').slice(0, 2).toUpperCase();
  const hue = PALETTE_HUES[(name || '').charCodeAt(0) % PALETTE_HUES.length];
  return (
    <span
      className={`avatar ${size === 'sm' ? 'avatar--sm' : ''} ${size === 'lg' ? 'avatar--lg' : ''}`}
      style={{
        background: `linear-gradient(135deg, oklch(0.6 0.18 ${hue}), oklch(0.45 0.2 ${(hue + 60) % 360}))`,
        borderRadius: square ? 8 : undefined,
      }}
    >{initial}</span>
  );
}

// ── Flash banner ─────────────────────────────────
function Flash({ tone = 'info', icon, title, children }) {
  return (
    <div className={`flash flash--${tone}`}>
      {icon}
      <div>
        {title && <strong>{title}</strong>}
        {title && children && <div style={{ marginTop: 2 }}>{children}</div>}
        {!title && children}
      </div>
    </div>
  );
}

// ── Field ─────────────────────────────────
function Field({ label, help, helpInline, children, action }) {
  return (
    <div className="field">
      {label && (
        <div className="field__label" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>{label} {helpInline && <span className="field__help--inline">{helpInline}</span>}</span>
          {action}
        </div>
      )}
      {children}
      {help && <div className="field__help">{help}</div>}
    </div>
  );
}

// ── Sparkline ─────────────────────────────────
function Sparkline({ data, color, fill, height = 24, width = 200, smooth = true }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return [x, y];
  });
  const d = smooth
    ? pts.reduce((acc, [x, y], i) => {
        if (i === 0) return `M${x},${y}`;
        const [px, py] = pts[i - 1];
        const cx1 = px + (x - px) / 2;
        return acc + ` C${cx1},${py} ${cx1},${y} ${x},${y}`;
      }, '')
    : 'M' + pts.map(p => p.join(',')).join(' L');
  const dFill = d + ` L${width},${height} L0,${height} Z`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none" style={{ display: 'block' }}>
      {fill && <path d={dFill} fill={fill} opacity="0.18" />}
      <path d={d} fill="none" stroke={color || 'currentColor'} strokeWidth="1.4" />
    </svg>
  );
}

// ── Procedural session thumbnail ─────────────────────────────────
// Stylized abstract thumbnails representing what was captured.
function SessionThumb({ session, withChart = true }) {
  const { seedRand, makeSparkline } = window.TrailboxData;
  const rand = seedRand(session.thumb_seed);
  const kind = session.thumb_kind;

  // hue families per kind
  const hueBase = kind === 'mobile' ? 150
                : kind === 'code' ? 220
                : kind === 'game' ? 280
                : 200;
  const hue1 = hueBase + (rand() - 0.5) * 40;
  const hue2 = (hueBase + 80 + rand() * 40) % 360;

  // mock content blocks
  const blocks = Array.from({ length: 6 }, (_, i) => ({
    x: rand() * 100,
    y: rand() * 60,
    w: 8 + rand() * 30,
    h: 4 + rand() * 8,
    op: 0.15 + rand() * 0.25,
  }));

  // chart line for thumb
  const spark = useMemo(() => makeSparkline(session.thumb_seed + 99, 60, [15, 70]), [session.thumb_seed]);
  const pts = spark.map((v, i) => `${(i / (spark.length - 1)) * 100},${100 - v}`).join(' ');

  return (
    <div className="thumb">
      {/* gradient bg */}
      <div
        className="thumb__bg"
        style={{
          background: `linear-gradient(135deg, oklch(0.35 0.14 ${hue1}) 0%, oklch(0.2 0.08 ${hue2}) 100%)`,
        }}
      />
      {/* abstract content blocks */}
      <svg viewBox="0 0 100 62.5" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
        {kind === 'game' && (
          <>
            <circle cx="62" cy="28" r="14" fill={`oklch(0.7 0.16 ${hue1})`} opacity="0.32" />
            <circle cx="38" cy="35" r="8" fill={`oklch(0.8 0.14 ${hue2})`} opacity="0.32" />
            <rect x="0" y="48" width="100" height="14" fill={`oklch(0.18 0.08 ${hue1})`} opacity="0.55" />
            {/* HUD */}
            <rect x="4" y="4" width="22" height="3" fill="white" opacity="0.5" rx="0.4" />
            <rect x="4" y="9" width="14" height="2" fill="white" opacity="0.35" rx="0.4" />
            <circle cx="92" cy="9" r="3" fill="white" opacity="0.3" />
          </>
        )}
        {kind === 'mobile' && (
          <>
            {/* phone */}
            <rect x="36" y="6" width="28" height="50" rx="3" fill={`oklch(0.18 0.04 ${hue2})`} opacity="0.85" />
            <rect x="39" y="11" width="22" height="38" rx="1.5" fill={`oklch(0.92 0.05 ${hue1})`} opacity="0.85" />
            <rect x="42" y="15" width="16" height="3" fill={`oklch(0.55 0.18 ${hue1})`} opacity="0.6" rx="0.3" />
            <rect x="42" y="21" width="12" height="2" fill="white" opacity="0.5" rx="0.3" />
            <rect x="42" y="25" width="14" height="2" fill="white" opacity="0.4" rx="0.3" />
            <rect x="42" y="32" width="16" height="8" fill="white" opacity="0.3" rx="0.6" />
          </>
        )}
        {kind === 'code' && (
          <>
            {/* terminal lines */}
            {blocks.map((b, i) => (
              <rect key={i} x={b.x * 0.6 + 4} y={i * 7 + 6} width={b.w + 20} height="2.4" fill="white" opacity={b.op} rx="0.4" />
            ))}
            <rect x="4" y="50" width="6" height="2.4" fill={`oklch(0.7 0.18 ${hue1})`} opacity="0.9" rx="0.3" />
            <rect x="12" y="50" width="20" height="2.4" fill="white" opacity="0.45" rx="0.3" />
          </>
        )}
      </svg>
      {/* chart overlay */}
      {withChart && (
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="thumb__chart" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
          <polyline points={pts} fill="none" stroke={`oklch(0.85 0.14 ${hue1})`} strokeWidth="0.6" opacity="0.7" />
        </svg>
      )}
      <div className="thumb__overlay" />
      <div className="thumb__badges">
        <Badge tone="neutral" className="badge--outline" >
          <span style={{ color: 'white', opacity: 0.9 }}>{session.device}</span>
        </Badge>
      </div>
      <div className="thumb__title">{session.session_id}</div>
      <div className="thumb__duration">{formatDuration(session.duration_seconds)}</div>
      <div className="thumb-play"><window.Icons.Play /></div>
    </div>
  );
}

// ── Helpers ─────────────────────────────────
function formatDuration(secs) {
  if (!secs) return '—';
  const s = Math.floor(secs % 60);
  const m = Math.floor((secs / 60) % 60);
  const h = Math.floor(secs / 3600);
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatSize(bytes) {
  if (!bytes) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatNumber(n) {
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
  return String(n);
}

// ── Segmented control ─────────────────────────────────
function Segmented({ value, onChange, options }) {
  return (
    <div className="seg">
      {options.map(opt => (
        <button
          key={opt.value}
          className={`seg__btn ${value === opt.value ? 'active' : ''}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.icon}{opt.label}
        </button>
      ))}
    </div>
  );
}

// ── Toast/copy feedback ─────────────────────────────────
function useCopy() {
  const [copied, setCopied] = useState(null);
  const copy = (text, id = '_') => {
    try { navigator.clipboard.writeText(text); } catch (_) {}
    setCopied(id);
    setTimeout(() => setCopied(c => c === id ? null : c), 1400);
  };
  return [copied, copy];
}

// Export
Object.assign(window, {
  Button, Badge, Avatar, Flash, Field, Sparkline,
  SessionThumb, Segmented, useCopy,
  formatDuration, formatSize, formatNumber,
});
