import type { CSSProperties } from 'react';

type IconProps = {
  size?: number;
  className?: string;
  style?: CSSProperties;
};

const wrap = (children: React.ReactNode, { size = 16, className, style }: IconProps = {}) => (
  <svg
    viewBox="0 0 16 16"
    width={size}
    height={size}
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    className={className}
    style={style}
  >
    {children}
  </svg>
);

export const Icon = {
  // Nav
  Capture: (p?: IconProps) => wrap(
    <>
      <circle cx={8} cy={8} r={3.5} />
      <circle cx={8} cy={8} r={1.5} fill="currentColor" stroke="none" />
    </>,
    p,
  ),
  Sessions: (p?: IconProps) => wrap(
    <>
      <path d="M2.5 4h11M2.5 8h11M2.5 12h11" />
      <path d="M4 4v8M9 4v8" strokeOpacity={0.4} />
    </>,
    p,
  ),
  Hub: (p?: IconProps) => wrap(
    <>
      <circle cx={8} cy={3.5} r={1.5} />
      <circle cx={3.5} cy={11} r={1.5} />
      <circle cx={12.5} cy={11} r={1.5} />
      <path d="M8 5v3M7 8.5 4.5 10M9 8.5 11.5 10" />
    </>,
    p,
  ),
  Sun: (p?: IconProps) => wrap(
    <>
      <circle cx={8} cy={8} r={2.5} />
      <path d="M8 1.5V3M8 13v1.5M14.5 8H13M3 8H1.5M3.6 3.6l1 1M11.4 11.4l1 1M11.4 4.6l1-1M3.6 12.4l1-1" />
    </>,
    p,
  ),
  Moon: (p?: IconProps) => wrap(<path d="M13.5 9.5A6 6 0 0 1 6.5 2.5 6 6 0 1 0 13.5 9.5Z" />, p),
};
