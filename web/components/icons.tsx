// Inline icons (no icon package): 24 px, stroke or fill in currentColor.
import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = {
  width: 24,
  height: 24,
  viewBox: "0 0 24 24",
  "aria-hidden": true,
};

export function WodIcon() {
  return (
    <svg {...base} fill="currentColor">
      <rect x="3" y="9" width="4" height="12" rx="1.5" />
      <rect x="10" y="3" width="4" height="18" rx="1.5" />
      <rect x="17" y="12" width="4" height="9" rx="1.5" />
    </svg>
  );
}

export function PrIcon() {
  return (
    <svg {...base} fill="currentColor">
      <path d="M13 2 4 14h7l-1 8 9-12h-7z" />
    </svg>
  );
}

export function CoachIcon() {
  return (
    <svg {...base} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <path d="M4 5h16v11H9l-5 4z" />
    </svg>
  );
}

export function PlanningIcon() {
  return (
    <svg {...base} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </svg>
  );
}

export function HealthIcon() {
  return (
    <svg {...base} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <path d="M3 12h4l2-5 4 10 2-5h6" />
    </svg>
  );
}

export function ProfileIcon() {
  return (
    <svg {...base} fill="currentColor">
      <circle cx="12" cy="8" r="4.5" />
      <path d="M3.5 21c.8-4.4 4.2-7 8.5-7s7.7 2.6 8.5 7z" />
    </svg>
  );
}

export function BackIcon() {
  return (
    <svg {...base} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <path d="M15 5 8 12l7 7" />
    </svg>
  );
}
