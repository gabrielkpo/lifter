import Link from "next/link";
import type { ReactNode } from "react";
import { ProfileIcon } from "./icons";

/** Page header: optional eyebrow, the title, and the avatar that opens the profile. */
export default function TopBar({ title, eyebrow }: { title: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="topbar">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
      </div>
      <Link href="/profile" className="avatar" aria-label="Profile">
        <ProfileIcon />
      </Link>
    </header>
  );
}
