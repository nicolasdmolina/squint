import type { ReactNode, SVGProps } from 'react';

// One drawn set: 20px grid, 1.5px stroke, round caps and joins.
function Svg({ children, size = 18, ...rest }: SVGProps<SVGSVGElement> & { size?: number; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

type P = { size?: number; className?: string };

/** The Squint mark: an eye narrowed to read closely, the pupil a lens. */
export const Mark = ({ size = 26, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true" className={className}>
    <path d="M3.5 17.5C8 10.5 24 10.5 28.5 17.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    <path d="M8 20.5C12.5 23.5 19.5 23.5 24 20.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    <circle cx="16" cy="17.25" r="3.6" fill="currentColor" />
  </svg>
);

/** Nav: check (a reading lens), accuracy (a target), how it works (an open card). */
export const LensIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="8.75" cy="8.75" r="5.5" />
    <path d="m12.75 12.75 4 4" />
  </Svg>
);

export const TargetIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="7.25" />
    <circle cx="10" cy="10" r="3.75" />
    <circle cx="10" cy="10" r="0.6" fill="currentColor" />
  </Svg>
);

export const CardIcon = (p: P) => (
  <Svg {...p}>
    <rect x="3" y="3.25" width="14" height="13.5" rx="2.5" />
    <path d="M6.5 7.5h7M6.5 10.5h7M6.5 13.5h4" />
  </Svg>
);

export const UploadIcon = (p: P) => (
  <Svg {...p}>
    <path d="M10 13V3.5M6.25 7.25 10 3.5l3.75 3.75" />
    <path d="M3.5 12.5v3.25c0 .41.34.75.75.75h11.5c.41 0 .75-.34.75-.75V12.5" />
  </Svg>
);

export const SunIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="3.25" />
    <path d="M10 2.5v1.75M10 15.75v1.75M2.5 10h1.75M15.75 10h1.75M4.7 4.7l1.24 1.24M14.06 14.06l1.24 1.24M4.7 15.3l1.24-1.24M14.06 5.94l1.24-1.24" />
  </Svg>
);

export const MoonIcon = (p: P) => (
  <Svg {...p}>
    <path d="M16.25 12.1A6.5 6.5 0 0 1 7.9 3.75a6.5 6.5 0 1 0 8.35 8.35Z" />
  </Svg>
);

export const SystemIcon = (p: P) => (
  <Svg {...p}>
    <rect x="2.75" y="3.75" width="14.5" height="9.5" rx="2" />
    <path d="M7 16.5h6M10 13.25v3.25" />
  </Svg>
);

export const AlertIcon = (p: P) => (
  <Svg {...p}>
    <path d="M10 2.75 18 16.5H2L10 2.75Z" />
    <path d="M10 8v3.75" />
    <circle cx="10" cy="14" r="0.4" fill="currentColor" />
  </Svg>
);

export const CheckIcon = (p: P) => (
  <Svg {...p}>
    <path d="m4 10.5 3.75 3.75L16 6" />
  </Svg>
);

export const LockIcon = (p: P) => (
  <Svg {...p}>
    <rect x="4" y="9" width="12" height="8.5" rx="2" />
    <path d="M6.75 9V6.5a3.25 3.25 0 0 1 6.5 0V9" />
  </Svg>
);

export const ArrowLeftIcon = (p: P) => (
  <Svg {...p}>
    <path d="M16 10H4M8.5 5.5 4 10l4.5 4.5" />
  </Svg>
);

export const ArrowRightIcon = (p: P) => (
  <Svg {...p}>
    <path d="M4 10h12M11.5 5.5 16 10l-4.5 4.5" />
  </Svg>
);

export const CloseIcon = (p: P) => (
  <Svg {...p}>
    <path d="m5 5 10 10M15 5 5 15" />
  </Svg>
);

export const FileIcon = (p: P) => (
  <Svg {...p}>
    <path d="M11.5 2.75H5.25a.5.5 0 0 0-.5.5v13.5c0 .28.22.5.5.5h9.5a.5.5 0 0 0 .5-.5V6.5L11.5 2.75Z" />
    <path d="M11.5 2.75V6.5h3.75M7.5 10.5h5M7.5 13.5h5" />
  </Svg>
);

export const InfoIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="10" cy="10" r="7.25" />
    <path d="M10 9v4.75" />
    <circle cx="10" cy="6.4" r="0.4" fill="currentColor" />
  </Svg>
);

export const RedoIcon = (p: P) => (
  <Svg {...p}>
    <path d="M15.5 8.5A6 6 0 1 0 16 12" />
    <path d="M16 4v4.5h-4.5" />
  </Svg>
);
