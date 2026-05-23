// ============================================================
// Icons — small inline SVGs, no external deps
// Outline style, 1.5 stroke, 16px viewBox
// ============================================================
const { createElement: h } = React;

const svg = (children, props = {}) => h('svg', {
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  width: 16,
  height: 16,
  'aria-hidden': true,
  ...props,
}, children);

const path = (d, extra = {}) => h('path', { d, ...extra });

const Icons = {
  Sessions: (p) => svg([
    path('M2.5 4h11M2.5 8h11M2.5 12h11', { key: 1 }),
    path('M4 4v8M9 4v8', { key: 2, strokeOpacity: 0.4 }),
  ], p),
  Users: (p) => svg([
    path('M11 13.5v-1a3 3 0 0 0-3-3H5a3 3 0 0 0-3 3v1', { key: 1 }),
    h('circle', { key: 2, cx: 6.5, cy: 4.5, r: 2.5 }),
    path('M14 13.5v-1a3 3 0 0 0-2.25-2.9', { key: 3 }),
    path('M10 2.6a2.5 2.5 0 0 1 0 4.8', { key: 4 }),
  ], p),
  Settings: (p) => svg([
    h('circle', { key: 1, cx: 8, cy: 8, r: 2 }),
    path('M8 1v2M8 13v2M3 8H1M15 8h-2M3.8 3.8 5.2 5.2M10.8 10.8l1.4 1.4M3.8 12.2 5.2 10.8M10.8 5.2l1.4-1.4', { key: 2 }),
  ], p),
  Audit: (p) => svg([
    path('M3 2.5h7.5L13 5v8.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-11Z', { key: 1 }),
    path('M10 2.5V5h3', { key: 2 }),
    path('M5.5 8.5h5M5.5 11h3', { key: 3, strokeOpacity: 0.5 }),
  ], p),
  Account: (p) => svg([
    h('circle', { key: 1, cx: 8, cy: 5.5, r: 2.5 }),
    path('M3 13.5a5 5 0 0 1 10 0', { key: 2 }),
  ], p),
  Logout: (p) => svg([
    path('M6 14H3.5a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1H6', { key: 1 }),
    path('M10 11.5 13.5 8 10 4.5M6 8h7.5', { key: 2 }),
  ], p),
  Search: (p) => svg([
    h('circle', { key: 1, cx: 7, cy: 7, r: 4.5 }),
    path('M10.5 10.5 14 14', { key: 2 }),
  ], p),
  Plus: (p) => svg(path('M8 3v10M3 8h10'), p),
  Close: (p) => svg(path('M3.5 3.5 12.5 12.5M12.5 3.5 3.5 12.5'), p),
  Check: (p) => svg(path('M3.5 8.5 6.5 11.5 12.5 4.5'), p),
  Copy: (p) => svg([
    h('rect', { key: 1, x: 5, y: 5, width: 8.5, height: 8.5, rx: 1.5 }),
    path('M10 5V3.5a1 1 0 0 0-1-1H3.5a1 1 0 0 0-1 1V9a1 1 0 0 0 1 1H5', { key: 2 }),
  ], p),
  Download: (p) => svg([
    path('M8 2v8M4 7l4 4 4-4', { key: 1 }),
    path('M2.5 13.5h11', { key: 2 }),
  ], p),
  Trash: (p) => svg([
    path('M2.5 4h11M6 4V2.5h4V4M4 4l.5 9a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1l.5-9', { key: 1 }),
  ], p),
  Share: (p) => svg([
    h('circle', { key: 1, cx: 12, cy: 3.5, r: 1.5 }),
    h('circle', { key: 2, cx: 4, cy: 8, r: 1.5 }),
    h('circle', { key: 3, cx: 12, cy: 12.5, r: 1.5 }),
    path('M10.7 4.4 5.3 7.1M5.3 8.9l5.4 2.7', { key: 4 }),
  ], p),
  Link: (p) => svg([
    path('M6.5 9.5a2.5 2.5 0 0 0 3.5 0l2-2a2.5 2.5 0 0 0-3.5-3.5l-1 1', { key: 1 }),
    path('M9.5 6.5a2.5 2.5 0 0 0-3.5 0l-2 2a2.5 2.5 0 0 0 3.5 3.5l1-1', { key: 2 }),
  ], p),
  Eye: (p) => svg([
    path('M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8Z', { key: 1 }),
    h('circle', { key: 2, cx: 8, cy: 8, r: 2 }),
  ], p),
  Play: (p) => svg(h('path', { d: 'M5 3.5v9l7-4.5z', fill: 'currentColor', stroke: 'none' }), p),
  Pause: (p) => svg([
    h('rect', { key: 1, x: 4.5, y: 3, width: 2.5, height: 10, rx: 0.5, fill: 'currentColor', stroke: 'none' }),
    h('rect', { key: 2, x: 9, y: 3, width: 2.5, height: 10, rx: 0.5, fill: 'currentColor', stroke: 'none' }),
  ], p),
  SkipBack: (p) => svg([
    path('M4 3.5v9', { key: 1 }),
    h('path', { key: 2, d: 'M13 3.5v9L5.5 8z', fill: 'currentColor', stroke: 'none' }),
  ], p),
  SkipFwd: (p) => svg([
    path('M12 3.5v9', { key: 1 }),
    h('path', { key: 2, d: 'M3 3.5v9L10.5 8z', fill: 'currentColor', stroke: 'none' }),
  ], p),
  Sun: (p) => svg([
    h('circle', { key: 1, cx: 8, cy: 8, r: 2.5 }),
    path('M8 1.5V3M8 13v1.5M14.5 8H13M3 8H1.5M3.6 3.6l1 1M11.4 11.4l1 1M11.4 4.6l1-1M3.6 12.4l1-1', { key: 2 }),
  ], p),
  Moon: (p) => svg(path('M13.5 9.5A6 6 0 0 1 6.5 2.5 6 6 0 1 0 13.5 9.5Z'), p),
  Grid: (p) => svg([
    h('rect', { key: 1, x: 2, y: 2, width: 5, height: 5, rx: 1 }),
    h('rect', { key: 2, x: 9, y: 2, width: 5, height: 5, rx: 1 }),
    h('rect', { key: 3, x: 2, y: 9, width: 5, height: 5, rx: 1 }),
    h('rect', { key: 4, x: 9, y: 9, width: 5, height: 5, rx: 1 }),
  ], p),
  List: (p) => svg([
    path('M3 4h10M3 8h10M3 12h10', { key: 1 }),
    h('circle', { key: 2, cx: 1.5, cy: 4, r: 0.5, fill: 'currentColor' }),
    h('circle', { key: 3, cx: 1.5, cy: 8, r: 0.5, fill: 'currentColor' }),
    h('circle', { key: 4, cx: 1.5, cy: 12, r: 0.5, fill: 'currentColor' }),
  ], p),
  Rows: (p) => svg([
    h('rect', { key: 1, x: 2, y: 3, width: 12, height: 4, rx: 1 }),
    h('rect', { key: 2, x: 2, y: 9, width: 12, height: 4, rx: 1 }),
  ], p),
  PC: (p) => svg([
    h('rect', { key: 1, x: 1.5, y: 3, width: 13, height: 8, rx: 1 }),
    path('M5.5 13.5h5M8 11v2.5', { key: 2 }),
  ], p),
  Phone: (p) => svg([
    h('rect', { key: 1, x: 4.5, y: 1.5, width: 7, height: 13, rx: 1.5 }),
    path('M7 12.5h2', { key: 2 }),
  ], p),
  Chevron: (p) => svg(path('M6 3.5 10.5 8 6 12.5'), p),
  ChevronDown: (p) => svg(path('M3.5 6 8 10.5 12.5 6'), p),
  Filter: (p) => svg(path('M2 3.5h12L9.5 8.5v4l-3-1v-3z'), p),
  Cpu: (p) => svg([
    h('rect', { key: 1, x: 4, y: 4, width: 8, height: 8, rx: 1 }),
    h('rect', { key: 2, x: 6, y: 6, width: 4, height: 4, rx: 0.5 }),
    path('M6 1.5v2.5M10 1.5v2.5M6 12v2.5M10 12v2.5M1.5 6h2.5M1.5 10h2.5M12 6h2.5M12 10h2.5', { key: 3 }),
  ], p),
  Bolt: (p) => svg(h('path', { d: 'M8.5 1.5 3 9h4l-.5 5.5L12 7H8z', fill: 'currentColor', stroke: 'currentColor' }), p),
  Clock: (p) => svg([
    h('circle', { key: 1, cx: 8, cy: 8, r: 6 }),
    path('M8 4.5V8l2.5 1.5', { key: 2 }),
  ], p),
  Key: (p) => svg([
    h('circle', { key: 1, cx: 5, cy: 11, r: 2.5 }),
    path('M7 9 14 2M11 5l2 2M12.5 3.5l1.5 1.5', { key: 2 }),
  ], p),
  Robot: (p) => svg([
    h('rect', { key: 1, x: 2.5, y: 5, width: 11, height: 9, rx: 1.5 }),
    path('M6 9.5v1M10 9.5v1', { key: 2, strokeWidth: 2 }),
    path('M8 5V2.5M5 2.5h6', { key: 3 }),
  ], p),
  Mouse: (p) => svg([
    h('rect', { key: 1, x: 4, y: 2, width: 8, height: 12, rx: 4 }),
    path('M8 4.5V7', { key: 2 }),
  ], p),
  Keyboard: (p) => svg([
    h('rect', { key: 1, x: 1.5, y: 4, width: 13, height: 8, rx: 1 }),
    path('M4 7h.01M6.5 7h.01M9 7h.01M11.5 7h.01M4 9.5h7', { key: 2 }),
  ], p),
  Document: (p) => svg([
    path('M3 2.5h6.5L13 5.5v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z', { key: 1 }),
    path('M9 2.5V5.5h3.5', { key: 2 }),
  ], p),
};

window.Icons = Icons;
