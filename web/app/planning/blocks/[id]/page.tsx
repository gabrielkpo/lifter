"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import { BackIcon } from "@/components/icons";
import WeekChart from "@/components/WeekChart";
import { NOT_FOUND, useApi } from "@/lib/api";
import { label, shortDate } from "@/lib/format";
import type { BlockDetail, WeekExercise } from "@/lib/types";

const LIFTS = ["strength", "weightlifting"];

/** A block: how each lift moved week by week (load, reps, RIR), then the weeks themselves. */
export default function BlockPage() {
  const { id } = useParams<{ id: string }>();
  const valid = /^\d+$/.test(id);
  const fetched = useApi<BlockDetail>(valid ? `/blocks/${id}` : null);
  const state = valid ? fetched : NOT_FOUND;
  return (
    <>
      <header className="topbar">
        <Link href="/planning" className="avatar" aria-label="Back to planning">
          <BackIcon />
        </Link>
      </header>
      {state.status === "ok" ? <Block detail={state.data} /> : <ApiStatus state={state} />}
    </>
  );
}

/** Lifts done in at least two weeks, most present first: the ones worth a curve. */
function trackedLifts(progress: WeekExercise[]): string[] {
  const weeksDone = new Map<string, number>();
  for (const p of progress) {
    if (p.origin === "done" && LIFTS.includes(p.category)) {
      weeksDone.set(p.exercise, (weeksDone.get(p.exercise) ?? 0) + 1);
    }
  }
  return [...weeksDone.entries()]
    .filter(([, n]) => n >= 2)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name]) => name);
}

function Block({ detail }: { detail: BlockDetail }) {
  const { block, weeks, progress } = detail;
  const lifts = trackedLifts(progress);
  const [exercise, setExercise] = useState<string | null>(lifts[0] ?? null);
  const target = block.target_strength_sessions;

  const series = (origin: "planned" | "done", pick: (p: WeekExercise) => number | null) =>
    weeks.map((w) => {
      const row = progress.find(
        (p) => p.week_id === w.id && p.exercise === exercise && p.origin === origin,
      );
      return row ? pick(row) : null;
    });
  const chartWeeks = weeks.map((w) => ({ number: w.number, phase: w.phase }));

  return (
    <>
      <p className="eyebrow muted small">Block {block.position}</p>
      <h1 style={{ margin: "4px 0 6px", fontSize: 30 }}>{label(block.kind)}</h1>
      <div className="progress">
        <div style={{ width: `${target ? Math.min(1, block.strength_sessions_done / target) * 100 : 0}%` }} />
      </div>
      <p className="muted small">
        {block.strength_sessions_done}
        {target ? ` / ${target}` : ""} strength sessions · {shortDate(block.start_date)} →{" "}
        {shortDate(block.end_date)}
      </p>
      {block.intent && <p style={{ lineHeight: 1.45 }}>{block.intent}</p>}

      <h2 className="section-title">Progression</h2>
      {lifts.length === 0 ? (
        <p className="empty">Curves appear once a lift is logged in two weeks.</p>
      ) : (
        <>
          <div className="chips" role="group" aria-label="Exercise">
            {lifts.map((name) => (
              <button
                key={name}
                className="chip"
                aria-pressed={name === exercise}
                onClick={() => setExercise(name)}
              >
                {name}
              </button>
            ))}
          </div>
          <p className="legend small muted">
            <span className="key done" /> Done <span className="key planned" /> Planned
            <span className="key deload" /> Deload
          </p>
          <div className="charts">
            <WeekChart
              title="Top load"
              unit="kg"
              fromZero={false}
              weeks={chartWeeks}
              done={series("done", (p) => p.top_load_kg)}
              planned={series("planned", (p) => p.top_load_kg)}
            />
            <WeekChart
              title="Reps"
              weeks={chartWeeks}
              done={series("done", (p) => p.reps)}
              planned={series("planned", (p) => p.reps)}
            />
            <WeekChart
              title="RIR"
              weeks={chartWeeks}
              done={series("done", (p) => p.avg_rir)}
              planned={series("planned", (p) => p.avg_rir)}
            />
          </div>
        </>
      )}

      <h2 className="section-title">Weeks</h2>
      <ul className="list">
        {weeks.map((w) => (
          <li key={w.id} style={{ fontSize: 16 }}>
            <Link href={`/planning/weeks/${w.id}`} className="row" style={{ width: "100%" }}>
              <span>
                <strong>Week {w.number}</strong> · {label(w.phase)}
                <br />
                <span className="small">{shortDate(w.start_date)}</span>
              </span>
              <span className="small">
                {w.done}/{w.sessions} done ›
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
