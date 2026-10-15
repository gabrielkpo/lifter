"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CoachIcon, HealthIcon, PlanningIcon, PrIcon, WodIcon } from "./icons";

const TABS = [
  { href: "/wod", label: "WOD", Icon: WodIcon },
  { href: "/prs", label: "PRs", Icon: PrIcon },
  { href: "/coach", label: "Coach", Icon: CoachIcon },
  { href: "/planning", label: "Planning", Icon: PlanningIcon },
  { href: "/health", label: "Health", Icon: HealthIcon },
];

export default function TabBar() {
  const pathname = usePathname();
  // A session belongs to the WOD tab.
  const active = pathname.startsWith("/sessions") ? "/wod" : pathname;
  return (
    <nav className="tabbar" aria-label="Main">
      <ul>
        {TABS.map(({ href, label, Icon }) => (
          <li key={href}>
            <Link href={href} aria-current={active.startsWith(href) ? "page" : undefined}>
              <Icon />
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
