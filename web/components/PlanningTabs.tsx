"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/planning", label: "Cycles" },
  { href: "/planning/weeks", label: "Weeks" },
  { href: "/planning/goals", label: "Goals" },
];

/** The Planning tab's three views, one page each, so back from a week returns to Weeks. */
export default function PlanningTabs() {
  const pathname = usePathname();
  return (
    <nav className="pills" aria-label="Planning">
      {TABS.map(({ href, label }) => (
        <Link
          key={href}
          href={href}
          className="pill"
          aria-current={pathname === href ? "page" : undefined}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
