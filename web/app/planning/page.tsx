"use client";

import ApiStatus from "@/components/ApiStatus";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { label, num, shortDate, today } from "@/lib/format";
import type { Goal, Program, Week } from "@/lib/types";

/** The long term: the cycle's blocks counted in strength sessions, the weeks, the goals. */
export default function PlanningPage() {
  const program = useApi<Program>("/program");
  const weeks = useApi<Week[]>("/weeks");
  const goals = useApi<Goal[]>("/goals");

  return (
    <>
      <TopBar title="Planning" />
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
                <article key={block.id} className={now ? "card accent" : "card"}>
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
                  {block.intent && <p style={{ marginTop: 8 }}>{block.intent}</p>}
                </article>
              );
            })}
            {weeks.status === "ok" && (
              <ul className="list">
                {weeks.data
                  .filter((w) => w.cycle_id === cycle.id)
                  .map((w) => (
                    <li key={w.id} style={{ fontSize: 16 }}>
                      <span>
                        <strong>Week {w.number}</strong> · {label(w.phase)}
                        <br />
                        <span className="small">{shortDate(w.start_date)}</span>
                      </span>
                      <span className="small">
                        {w.done}/{w.sessions} done · {w.strength_sessions_done} strength
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </section>
        ))
      )}

      <h2 className="section-title">Goals</h2>
      {goals.status !== "ok" ? (
        <ApiStatus state={goals} />
      ) : goals.data.length === 0 ? (
        <p className="empty">No goal yet.</p>
      ) : (
        goals.data.map((g) => (
          <article key={g.id} className="card">
            <div className="row">
              <h3>{g.title}</h3>
              <span className="badge" data-status={g.status === "achieved" ? "done" : undefined}>
                {g.status}
              </span>
            </div>
            <p className="small">
              {g.baseline_value !== null
                ? `${num(g.baseline_value)} ${g.unit ?? ""}`
                : (g.baseline_text ?? "–")}{" "}
              →{" "}
              <strong style={{ color: "var(--text)" }}>
                {g.target_value !== null ? `${num(g.target_value)} ${g.unit ?? ""}` : g.target_text}
              </strong>
              {g.target_date && ` by ${shortDate(g.target_date)}`}
            </p>
            {g.milestones.length > 0 && (
              <p className="small" style={{ marginTop: 6 }}>
                {g.milestones
                  .map((m) => `${shortDate(m.day)}: ${m.value !== null ? num(m.value) : m.value_text}`)
                  .join(" · ")}
              </p>
            )}
          </article>
        ))
      )}
    </>
  );
}
