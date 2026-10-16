"use client";

import { useEffect, useRef, useState } from "react";
import { apiActivity, onApiActivity } from "@/lib/api";
import { MARK_PATH } from "./Mark";

// The launch screen, validated by the owner on 16/10: on black, one kettlebell falls, bounces
// on the floor and off the sides while it spins, then settles and "LIFTER" appears. The app
// shows once the bell has settled and the first page has its data; if the data takes longer,
// the bell stays where it landed. Shown once per launch: the layout mounts it once.
const BELL_W = 64;
const BELL_H = 59;
const GRAVITY = 2200; // px/s²
const FLOOR_AT = 0.62; // the floor's height, as a share of the screen
const BOUNCE = 0.55; // vertical speed kept at each bounce on the floor
const WALL = 0.7; // horizontal speed kept off a side
/** The data must have been idle this long: a page often chains a second call to the first. */
const IDLE_MS = 250;
/** A page with no call at all is ready once this has passed. */
const NO_CALL_MS = 600;
/** Whatever happens (a hung request), the app shows after this. */
const MAX_MS = 12000; // the CSS hides it at the same time if JavaScript never runs
const FADE_MS = 350;

export default function Splash() {
  const [phase, setPhase] = useState<"loading" | "leaving" | "gone">("loading");
  const [settled, setSettled] = useState(false);
  const screen = useRef<HTMLDivElement>(null);
  const bell = useRef<SVGSVGElement>(null);
  // From the start of the page load, not from hydration: a slow phone does not wait longer.
  // Kept across renders, so the bell settling does not forget when the last call ended.
  const busySince = useRef<number | null>(null);

  useEffect(() => {
    busySince.current ??= Date.now() - performance.now();
    return onApiActivity(() => {
      if (apiActivity().inFlight > 0) busySince.current = Date.now();
    });
  }, []);

  // The fall: plain physics, one frame at a time.
  useEffect(() => {
    const box = screen.current;
    const svg = bell.current;
    if (!box || !svg) return;
    const width = box.clientWidth;
    const floor = Math.round(box.clientHeight * FLOOR_AT);
    const left = 24;
    const right = width - 24;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      svg.style.transform = `translate(${width / 2 - BELL_W / 2}px, ${floor - BELL_H}px)`;
      const still = requestAnimationFrame(() => setSettled(true));
      return () => cancelAnimationFrame(still);
    }
    const dir = Math.random() < 0.5 ? -1 : 1;
    const s = {
      x: width / 2 - BELL_W / 2,
      y: -BELL_H - 20,
      vx: dir * (140 + Math.random() * 60),
      vy: 0,
      rot: 0,
      squash: 0,
      rest: 0,
      t: performance.now(),
    };
    let frame = 0;
    const step = (now: number) => {
      const dt = Math.min(0.033, (now - s.t) / 1000);
      s.t = now;
      s.vy += GRAVITY * dt;
      s.x += s.vx * dt;
      s.y += s.vy * dt;
      if (s.y + BELL_H >= floor) {
        s.y = floor - BELL_H;
        if (Math.abs(s.vy) > 120) s.squash = Math.min(0.28, Math.abs(s.vy) / 4000);
        s.vy = Math.abs(s.vy) < 90 / BOUNCE ? 0 : -s.vy * BOUNCE;
        s.vx *= 0.82;
      }
      if (s.x <= left) {
        s.x = left;
        s.vx = Math.abs(s.vx) * WALL;
      }
      if (s.x + BELL_W >= right) {
        s.x = right - BELL_W;
        s.vx = -Math.abs(s.vx) * WALL;
      }
      const onFloor = s.y >= floor - BELL_H - 0.5 && s.vy === 0;
      if (onFloor) s.vx *= Math.pow(0.12, dt);
      s.rot = onFloor ? s.rot * Math.pow(0.02, dt) : s.rot + s.vx * dt * 0.9;
      s.squash *= Math.pow(0.0005, dt);
      svg.style.transform =
        `translate(${s.x}px, ${s.y}px) rotate(${s.rot}deg)` +
        ` scale(${1 + s.squash}, ${1 - s.squash})`;
      if (onFloor && Math.abs(s.vx) < 4) {
        s.rest += dt;
        if (s.rest > 0.3) {
          setSettled(true);
          return;
        }
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, []);

  // When to leave: the bell has settled and the first page's calls are done.
  useEffect(() => {
    const start = Date.now() - performance.now();
    const timer = setInterval(() => {
      const now = Date.now();
      const { inFlight, started } = apiActivity();
      const idle = inFlight === 0 && now - (busySince.current ?? start) >= IDLE_MS;
      const ready = started > 0 ? idle : now - start >= NO_CALL_MS;
      if ((settled && ready) || now - start >= MAX_MS) {
        clearInterval(timer);
        setPhase("leaving");
      }
    }, 100);
    return () => clearInterval(timer);
  }, [settled]);

  useEffect(() => {
    if (phase !== "leaving") return;
    const timer = setTimeout(() => setPhase("gone"), FADE_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  if (phase === "gone") return null;
  return (
    <div
      ref={screen}
      className="splash"
      data-leaving={phase === "leaving"}
      role="status"
      aria-label="Loading"
    >
      <div className="splash-floor" style={{ top: `${FLOOR_AT * 100}%` }} />
      <svg
        ref={bell}
        className="splash-bell"
        // Cropped to the mark, so the bell stands on the floor.
        viewBox="8.5 9.5 47 43.5"
        width={BELL_W}
        height={BELL_H}
        aria-hidden
      >
        <path fill="currentColor" d={MARK_PATH} />
      </svg>
      <p className="splash-label" data-shown={settled}>
        LIFTER
      </p>
    </div>
  );
}
