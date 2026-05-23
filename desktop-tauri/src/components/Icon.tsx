import type { SVGProps } from 'react';

type P = SVGProps<SVGSVGElement>;

const d: P = {
  viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
  width: 16, height: 16, 'aria-hidden': true,
};

const s = (ch: React.ReactNode, p?: P) => <svg {...d} {...p}>{ch}</svg>;

export const Icon = {
  Capture: (p?: P) => s(<><circle cx="8" cy="8" r="5.5" /><circle cx="8" cy="8" r="2" /><path d="M8 1v2M8 13v2M1 8h2M13 8h2" /></>, p),
  Sessions: (p?: P) => s(<><path d="M2.5 4h11M2.5 8h11M2.5 12h11" /><path d="M4 4v8M9 4v8" strokeOpacity={0.4} /></>, p),
  Hub: (p?: P) => s(<><path d="M6.5 9.5a2.5 2.5 0 0 0 3.5 0l2-2a2.5 2.5 0 0 0-3.5-3.5l-1 1" /><path d="M9.5 6.5a2.5 2.5 0 0 0-3.5 0l-2 2a2.5 2.5 0 0 0 3.5 3.5l1-1" /></>, p),
  Search: (p?: P) => s(<><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" /></>, p),
  Plus: (p?: P) => s(<path d="M8 3v10M3 8h10" />, p),
  Close: (p?: P) => s(<path d="M3.5 3.5 12.5 12.5M12.5 3.5 3.5 12.5" />, p),
  Check: (p?: P) => s(<path d="M3.5 8.5 6.5 11.5 12.5 4.5" />, p),
  Download: (p?: P) => s(<><path d="M8 2v8M4 7l4 4 4-4" /><path d="M2.5 13.5h11" /></>, p),
  Upload: (p?: P) => s(<><path d="M8 10V2M4 5l4-4 4 4" /><path d="M2.5 13.5h11" /></>, p),
  Trash: (p?: P) => s(<path d="M2.5 4h11M6 4V2.5h4V4M4 4l.5 9a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1l.5-9" />, p),
  Share: (p?: P) => s(<><circle cx="12" cy="3.5" r="1.5" /><circle cx="4" cy="8" r="1.5" /><circle cx="12" cy="12.5" r="1.5" /><path d="M10.7 4.4 5.3 7.1M5.3 8.9l5.4 2.7" /></>, p),
  Link: (p?: P) => s(<><path d="M6.5 9.5a2.5 2.5 0 0 0 3.5 0l2-2a2.5 2.5 0 0 0-3.5-3.5l-1 1" /><path d="M9.5 6.5a2.5 2.5 0 0 0-3.5 0l-2 2a2.5 2.5 0 0 0 3.5 3.5l1-1" /></>, p),
  Eye: (p?: P) => s(<><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8Z" /><circle cx="8" cy="8" r="2" /></>, p),
  Sun: (p?: P) => s(<><circle cx="8" cy="8" r="2.5" /><path d="M8 1.5V3M8 13v1.5M14.5 8H13M3 8H1.5M3.6 3.6l1 1M11.4 11.4l1 1M11.4 4.6l1-1M3.6 12.4l1-1" /></>, p),
  Moon: (p?: P) => s(<path d="M13.5 9.5A6 6 0 0 1 6.5 2.5 6 6 0 1 0 13.5 9.5Z" />, p),
  PC: (p?: P) => s(<><rect x="1.5" y="3" width="13" height="8" rx="1" /><path d="M5.5 13.5h5M8 11v2.5" /></>, p),
  Phone: (p?: P) => s(<><rect x="4.5" y="1.5" width="7" height="13" rx="1.5" /><path d="M7 12.5h2" /></>, p),
  Chevron: (p?: P) => s(<path d="M6 3.5 10.5 8 6 12.5" />, p),
  ChevronDown: (p?: P) => s(<path d="M3.5 6 8 10.5 12.5 6" />, p),
  Refresh: (p?: P) => s(<><path d="M2.5 7a5.5 5.5 0 0 1 10.2-1.5M13.5 9a5.5 5.5 0 0 1-10.2 1.5" /><path d="M13 2v3.5h-3.5M3 14v-3.5h3.5" /></>, p),
  Folder: (p?: P) => s(<path d="M2 4.5a1 1 0 0 1 1-1h3.5l1.5 1.5H13a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z" />, p),
  Play: (p?: P) => s(<path d="M5 3.5v9l7-4.5z" fill="currentColor" stroke="none" />, p),
  Window: (p?: P) => s(<><rect x="1.5" y="2.5" width="13" height="11" rx="1.5" /><path d="M1.5 5.5h13" /><circle cx="3.5" cy="4" r="0.5" fill="currentColor" /><circle cx="5.5" cy="4" r="0.5" fill="currentColor" /></>, p),
  Crosshair: (p?: P) => s(<><circle cx="8" cy="8" r="5.5" /><path d="M8 1v3M8 12v3M1 8h3M12 8h3" /></>, p),
  Cpu: (p?: P) => s(<><rect x="4" y="4" width="8" height="8" rx="1" /><rect x="6" y="6" width="4" height="4" rx="0.5" /><path d="M6 1.5v2.5M10 1.5v2.5M6 12v2.5M10 12v2.5M1.5 6h2.5M1.5 10h2.5M12 6h2.5M12 10h2.5" /></>, p),
  Bolt: (p?: P) => s(<path d="M8.5 1.5 3 9h4l-.5 5.5L12 7H8z" fill="currentColor" stroke="currentColor" />, p),
  Clock: (p?: P) => s(<><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.5 1.5" /></>, p),
  Key: (p?: P) => s(<><circle cx="5" cy="11" r="2.5" /><path d="M7 9 14 2M11 5l2 2M12.5 3.5l1.5 1.5" /></>, p),
  Robot: (p?: P) => s(<><rect x="2.5" y="5" width="11" height="9" rx="1.5" /><path d="M6 9.5v1M10 9.5v1" strokeWidth={2} /><path d="M8 5V2.5M5 2.5h6" /></>, p),
  Minimize: (p?: P) => s(<path d="M4 8h8" />, p),
  Maximize: (p?: P) => s(<rect x="3.5" y="3.5" width="9" height="9" rx="1" />, p),
  Keyboard: (p?: P) => s(<><rect x="1.5" y="4" width="13" height="8" rx="1" /><path d="M4 7h.01M6.5 7h.01M9 7h.01M11.5 7h.01M4 9.5h7" /></>, p),
  Mouse: (p?: P) => s(<><rect x="4" y="2" width="8" height="12" rx="4" /><path d="M8 4.5V7" /></>, p),
};
