"use client";

import { useEffect, useState } from "react";
import { apiActivity, onApiActivity } from "@/lib/api";
import { MARK_PATH } from "./Mark";

// The launch screen: on black, kettlebells fall one after the other, bounce and settle, until
// the first page has its data. It is in the server HTML, so it shows from the first paint and
// the animation (CSS only) runs before the app is interactive. Shown once per app launch: the
// layout mounts it once, page changes inside the app never bring it back.
const BELLS = 5;
/** Long enough to see three kettlebells land: never a flash. */
const MIN_MS = 1800;
/** The data must have been idle this long: a page often chains a second call to the first. */
const IDLE_MS = 250;
/** A page with no call at all is ready once this has passed. */
const NO_CALL_MS = 600;
/** Whatever happens (a hung request), the app shows after this. */
const MAX_MS = 12000;
const FADE_MS = 350;

export default function Splash() {
  const [phase, setPhase] = useState<"loading" | "leaving" | "gone">("loading");

  useEffect(() => {
    const start = Date.now();
    let busySince = start;
    const unsubscribe = onApiActivity(() => {
      if (apiActivity().inFlight > 0) busySince = Date.now();
    });
    const timer = setInterval(() => {
      const now = Date.now();
      const { inFlight, started } = apiActivity();
      const idle = inFlight === 0 && now - busySince >= IDLE_MS;
      const ready = started > 0 ? idle : now - start >= NO_CALL_MS;
      if ((now - start >= MIN_MS && ready) || now - start >= MAX_MS) {
        clearInterval(timer);
        setPhase("leaving");
      }
    }, 100);
    return () => {
      clearInterval(timer);
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (phase !== "leaving") return;
    const timer = setTimeout(() => setPhase("gone"), FADE_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  if (phase === "gone") return null;
  return (
    <div className="splash" data-leaving={phase === "leaving"} role="status" aria-label="Loading">
      <div className="splash-row">
        {Array.from({ length: BELLS }, (_, i) => (
          <svg
            key={i}
            className="splash-bell"
            // Cropped to the mark, so each bell stands on the floor.
            viewBox="8.5 9.5 47 43.5"
            style={{ animationDelay: `${i * 0.6}s` }}
            aria-hidden
          >
            <path fill="currentColor" d={MARK_PATH} />
          </svg>
        ))}
      </div>
      <div className="splash-floor" />
    </div>
  );
}
