"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import ApiStatus from "@/components/ApiStatus";
import { BackIcon } from "@/components/icons";
import SessionView from "@/components/SessionView";
import { useApi } from "@/lib/api";
import { label, shortDate } from "@/lib/format";
import type { SessionDetail, SessionSummary, WeekDetail } from "@/lib/types";

/** A week as it went: every session with what was done, its Garmin line and its note. */
export default function WeekPage() {
  const { id } = useParams<{ id: string }>();
  const state = useApi<WeekDetail>(/^\d+$/.test(id) ? `/weeks/${id}` : null);
  const back = state.status === "ok" && state.data.week.block_id
    ? `/planning/blocks/${state.data.week.block_id}`
    : "/planning";
  return (
    <>
      <header className="topbar">
        <Link href={back} className="avatar" aria-label="Back">
          <BackIcon />
        </Link>
      </header>
      {state.status === "ok" ? <Week detail={state.data} /> : <ApiStatus state={state} />}
    </>
  );
}

function Week({ detail }: { detail: WeekDetail }) {
  const { week, sessions } = detail;
  return (
    <>
      <p className="eyebrow muted small">
        {[week.block && label(week.block), label(week.phase)].filter(Boolean).join(" · ")}
      </p>
      <h1 style={{ margin: "4px 0 6px", fontSize: 30 }}>
        Week {week.number}
        {week.title && <span className="muted"> · {week.title}</span>}
      </h1>
      <p className="muted small">
        {shortDate(week.start_date)} · {week.done}/{week.sessions} done · {week.missed} missed ·{" "}
        {week.strength_sessions_done} strength
      </p>

      {Object.keys(week.intent).length > 0 && (
        <details className="card week">
          <summary className="row">
            <h2 style={{ margin: 0 }}>Intent</h2>
            <span className="small muted">Show</span>
          </summary>
          {Object.entries(week.intent).map(([part, text]) => (
            <p key={part} className="line">
              <b>{label(part)}</b>
              <span>{text}</span>
            </p>
          ))}
        </details>
      )}
      {week.review && (
        <section className="card">
          <h2>Review</h2>
          <p>{week.review}</p>
        </section>
      )}

      {sessions
        .filter((s) => s.kind !== "rest")
        .map((s) => (
          <DoneSession key={s.id} summary={s} />
        ))}
    </>
  );
}

function DoneSession({ summary }: { summary: SessionSummary }) {
  const detail = useApi<SessionDetail>(`/sessions/${summary.id}`);
  const heading = (
    <div className="row" style={{ margin: "28px 0 12px" }}>
      <div>
        <p className="eyebrow muted small" style={{ margin: 0 }}>
          {shortDate(summary.day)}
        </p>
        <h2 style={{ margin: "2px 0 0", fontSize: 22 }}>{summary.title}</h2>
        {summary.moved_from && (
          <p className="small muted" style={{ margin: 0 }}>
            Moved from {shortDate(summary.moved_from)}
          </p>
        )}
      </div>
      <span className="badge" data-status={summary.status}>
        {summary.status}
      </span>
    </div>
  );
  if (detail.status !== "ok") {
    return (
      <>
        {heading}
        <ApiStatus state={detail} />
      </>
    );
  }
  return <SessionView session={detail.data} mode="done" heading={heading} />;
}
