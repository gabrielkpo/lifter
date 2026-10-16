"use client";

import Link from "next/link";
import ApiStatus from "@/components/ApiStatus";
import PlanningTabs from "@/components/PlanningTabs";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { label, shortDate, today } from "@/lib/format";
import type { Program } from "@/lib/types";

/** The long term: the cycles and their blocks, counted in strength sessions. */
export default function PlanningPage() {
  const program = useApi<Program>("/program");

  return (
    <>
      <TopBar title="Planning" />
      <PlanningTabs />
      {program.status !== "ok" ? (
        <ApiStatus state={program} />
      ) : program.data.cycles.length === 0 ? (
        <p className="empty">No program loaded yet.</p>
      ) : (
        program.data.cycles.map((cycle) => (
          <section key={cycle.id}>
            <h2 className="section-title">{cycle.name}</h2>
            <p className="muted small">
              {shortDate(cycle.start_date)} → {shortDate(cycle.end_date)}
            </p>
            {cycle.blocks.map((block) => {
              const target = block.target_strength_sessions;
              const share = target ? Math.min(1, block.strength_sessions_done / target) : 0;
              const now = block.start_date <= today() && today() <= block.end_date;
              return (
                <Link
                  key={block.id}
                  href={`/planning/blocks/${block.id}`}
                  className="card card-link"
                >
                  <div className="row">
                    <h2>
                      Block {block.position} · {label(block.kind)}
                    </h2>
                    {now && <span className="badge">now</span>}
                  </div>
                  <div className="progress">
                    <div style={{ width: `${share * 100}%` }} />
                  </div>
                  <p className="small">
                    {block.strength_sessions_done}
                    {target ? ` / ${target}` : ""} strength sessions ·{" "}
                    {shortDate(block.start_date)} → {shortDate(block.end_date)}
                  </p>
                </Link>
              );
            })}
          </section>
        ))
      )}
    </>
  );
}
