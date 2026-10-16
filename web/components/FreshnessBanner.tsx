"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";

/** Older than this, the Garmin data is stale: the same threshold as `lifter data-test --freshness`. */
const STALE_HOURS = 36;

/** A line at the top of every page when the Mac's sync seems to have stopped: a failed sync
 * raises a macOS notification, which Focus or a refused permission can hide. */
export default function FreshnessBanner() {
  const status = useApi<{ garmin_last_seen_at: string | null }>("/status");
  // Read once when the app opens; the banner is about hours, not seconds.
  const [now] = useState(() => Date.now());
  if (status.status !== "ok" || status.data.garmin_last_seen_at === null) return null;
  const hours = (now - new Date(status.data.garmin_last_seen_at).getTime()) / 3_600_000;
  if (hours < STALE_HOURS) return null;
  const age = hours < 48 ? `${Math.round(hours)} h` : `${Math.round(hours / 24)} days`;
  return (
    <p className="banner" role="status">
      Garmin data is {age} old: the sync on the Mac may have stopped.
    </p>
  );
}
