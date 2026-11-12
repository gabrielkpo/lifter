"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { LOGIN_PATH } from "@/lib/session";

/** What only a signed-in page shows (the tab bar, the freshness banner, the launch screen):
 * nothing on the sign-in page, which reads no data. */
export default function SignedIn({ children }: { children: ReactNode }) {
  return usePathname() === LOGIN_PATH ? null : children;
}
