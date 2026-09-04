import type { SVGProps } from "react";

type IconName = "sequence" | "arrow" | "upload" | "external" | "sun" | "moon" |
  "history" | "settings" | "close" | "check" | "chevron" | "info" | "refresh";

const paths: Record<IconName, React.ReactNode> = {
  sequence: <><path d="M7 3c0 7 10 11 10 18M17 3C17 10 7 14 7 21M7.5 5h9M8.5 9h7M8.5 15h7M7.5 19h9" /></>,
  arrow: <path d="M4 12h15m-6-6 6 6-6 6" />,
  upload: <path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5" />,
  external: <path d="M13 4h7v7m0-7L10 14M10 5H4v15h15v-6" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M19 5l-1.4 1.4M6.4 17.6 5 19" /></>,
  moon: <path d="M20.5 13A8.5 8.5 0 0 1 11 3a8.5 8.5 0 1 0 9.5 10Z" />,
  history: <><path d="M3 10a9 9 0 1 1 2 8M3 4v6h6" /><path d="M12 7v5l3 2" /></>,
  settings: <><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="9" cy="6" r="2" /><circle cx="15" cy="12" r="2" /><circle cx="9" cy="18" r="2" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m6 9 6 6 6-6" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v1" /></>,
  refresh: <path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 4M5 14a8 8 0 0 0 13 4" />,
};

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    {paths[name]}
  </svg>;
}
