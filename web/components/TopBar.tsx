import Link from "next/link";
import type { ReactNode } from "react";
import { ProfileIcon } from "./icons";

/** Page header: optional eyebrow, the title, and the avatar that opens the profile; `leading`
 * and `actions` are a page's own buttons, before the title and before the avatar. */
export default function TopBar({
  title,
  eyebrow,
  leading,
  actions,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  leading?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="topbar">
      <div className="topbar-title">
        {leading}
        <div>
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h1>{title}</h1>
        </div>
      </div>
      <div className="topbar-actions">
        {actions}
        <Link href="/profile" className="avatar" aria-label="Profile">
          <ProfileIcon />
        </Link>
      </div>
    </header>
  );
}
