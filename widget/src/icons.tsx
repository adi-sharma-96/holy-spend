import React from "react";

export type IconName =
  | "add"
  | "arrow-down"
  | "arrow-up"
  | "back"
  | "basket"
  | "bag"
  | "calendar"
  | "camera"
  | "car"
  | "chart"
  | "chevron"
  | "close"
  | "dining"
  | "expand"
  | "file"
  | "heart"
  | "home"
  | "leaf"
  | "more"
  | "play"
  | "plane"
  | "receipt"
  | "refresh"
  | "scan"
  | "sparkle"
  | "trash"
  | "upload";

const paths: Record<IconName, React.ReactNode> = {
  add: <path d="M12 5v14M5 12h14" />,
  "arrow-down": <path d="m7 10 5 5 5-5" />,
  "arrow-up": <path d="m7 14 5-5 5 5" />,
  back: <path d="m15 18-6-6 6-6" />,
  basket: (
    <>
      <path d="m5 10 2 10h10l2-10H5Z" />
      <path d="m8 10 4-6 4 6M3 10h18M9 14v3M15 14v3" />
    </>
  ),
  bag: (
    <>
      <path d="M5 8h14l-1 13H6L5 8Z" />
      <path d="M9 9V6a3 3 0 0 1 6 0v3" />
    </>
  ),
  calendar: (
    <>
      <path d="M4 6h16v15H4V6Z" />
      <path d="M8 3v5M16 3v5M4 11h16" />
    </>
  ),
  camera: (
    <>
      <path d="M14.5 5 13 3h-2L9.5 5H5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-4.5Z" />
      <circle cx="12" cy="12.5" r="3.5" />
    </>
  ),
  car: (
    <>
      <path d="m4 15 1.5-6h13L20 15v4h-2v-2H6v2H4v-4Z" />
      <path d="m7 9 1.5-3h7L17 9M7 13h.01M17 13h.01" />
    </>
  ),
  chart: (
    <>
      <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" />
    </>
  ),
  chevron: <path d="m9 18 6-6-6-6" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  dining: (
    <>
      <path d="M7 3v18M4 3v5a3 3 0 0 0 6 0V3M17 3v18M17 3c3 2 3 7 0 9" />
    </>
  ),
  expand: (
    <>
      <path d="M8 3H3v5M16 3h5v5M8 21H3v-5M21 16v5h-5" />
    </>
  ),
  file: (
    <>
      <path d="M6 2h8l4 4v16H6z" />
      <path d="M14 2v5h5" />
    </>
  ),
  heart: <path d="M20.8 5.6a5.1 5.1 0 0 0-7.2 0L12 7.2l-1.6-1.6a5.1 5.1 0 1 0-7.2 7.2L12 21l8.8-8.2a5.1 5.1 0 0 0 0-7.2Z" />,
  home: (
    <>
      <path d="m3 11 9-8 9 8" />
      <path d="M5 10v11h14V10M9 21v-7h6v7" />
    </>
  ),
  leaf: (
    <>
      <path d="M12 2c-4 3-7 7-7 11a7 7 0 0 0 14 0c0-4-3-8-7-11Z" />
      <path d="M12 8v10" />
    </>
  ),
  more: (
    <>
      <circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  play: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m10 8 6 4-6 4V8Z" />
    </>
  ),
  plane: <path d="m22 2-9 20-2-9-9-2 20-9ZM11 13l5-5" />,
  receipt: (
    <>
      <path d="M6 3v18l3-2 3 2 3-2 3 2V3l-3 2-3-2-3 2-3-2Z" />
      <path d="M9 9h6M9 13h6" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 7v5h-5" />
      <path d="M18.1 16a7 7 0 1 1 .9-8l1 4" />
    </>
  ),
  scan: (
    <>
      <path d="M8 3H3v5M16 3h5v5M8 21H3v-5M21 16v5h-5" />
      <path d="M7 12h10" />
    </>
  ),
  sparkle: <path d="m12 3 1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3ZM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" />,
  trash: (
    <>
      <path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
    </>
  ),
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      className="icon"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      {paths[name]}
    </svg>
  );
}
