"use client";

import { useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import SessionView from "@/components/SessionView";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { addDays, label, parseDay, shortDate, today, weekday } from "@/lib/format";
import type { SessionDetail, SessionSummary, Week, WeekDetail } from "@/lib/types";

/** The week of training, day by day: the WOD tab. */
export default function WodPage() {
  const weeks = useApi<Week[]>("/weeks");
  // null: the week containing today.
  const [weekId, setWeekId] = useState<number | null>(null);
  const current = useApi<WeekDetail>(weekId === null ? "/weeks/current" : `/weeks/${weekId}`);

  // No week of the program contains today: open the last one that started.
  if (weekId === null && current.status === "error" && current.notFound) {
    if (weeks.status !== "ok") return <ApiStatus state={weeks} />;
    const started = weeks.data.filter((w) => w.start_date <= today());
    const fallback = started.at(-1) ?? weeks.data[0];
    if (!fallback) {
      return (
        <>
          <TopBar title="WOD" />
          <p className="empty">No program loaded yet.</p>
        </>
      );
    }
    setWeekId(fallback.id);
    return null;
  }
  if (current.status !== "ok") {
    return (
      <>
        <TopBar title="WOD" />
        <ApiStatus state={current} />
      </>
    );
  }

  const ids = weeks.status === "ok" ? weeks.data.map((w) => w.id) : [];
  const index = ids.indexOf(current.data.week.id);
  return (
    <WeekView
      key={current.data.week.id}
      detail={current.data}
      previous={index > 0 ? () => setWeekId(ids[index - 1]) : undefined}
      next={index >= 0 && index < ids.length - 1 ? () => setWeekId(ids[index + 1]) : undefined}
    />
  );
}

function WeekView({
  detail,
  previous,
  next,
}: {
  detail: WeekDetail;
  previous?: () => void;
  next?: () => void;
}) {
  const { week, sessions } = detail;
  const days = Array.from({ length: 7 }, (_, i) => addDays(week.start_date, i));
  const byDay = (day: string) => sessions.filter((s) => s.day === day);
  const firstWithSession = days.find((d) => byDay(d).length > 0) ?? days[0];
  const [selected, setSelected] = useState(days.includes(today()) ? today() : firstWithSession);
  const trainingDays = days.filter((d) => byDay(d).some((s) => s.kind !== "rest"));

  return (
    <>
      <TopBar
        eyebrow={[week.block && label(week.block), label(week.phase)].filter(Boolean).join(" · ")}
        title={`Week ${week.number}`}
      />

      <div className="row small muted">
        <button onClick={previous} disabled={!previous} aria-label="Previous week">
          {previous ? "‹ Previous" : ""}
        </button>
        <span>
          {week.done}/{week.sessions} done · {week.strength_sessions_done} strength
        </span>
        <button onClick={next} disabled={!next} aria-label="Next week">
          {next ? "Next ›" : ""}
        </button>
      </div>

      <div className="daystrip" role="group" aria-label="Days of the week">
        {days.map((day) => {
          const daySessions = byDay(day);
          const done = daySessions.some((s) => s.status === "done");
          const missed = daySessions.some((s) => s.status === "missed");
          return (
            <button
              key={day}
              aria-pressed={day === selected}
              data-has-session={daySessions.some((s) => s.kind !== "rest")}
              onClick={() => setSelected(day)}
            >
              <span className="dow">{weekday(day)}</span>
              <span className="dom">{parseDay(day).getDate()}</span>
              <span
                className="dot"
                style={{
                  background: done ? "var(--done)" : missed ? "var(--missed)" : "transparent",
                }}
              />
            </button>
          );
        })}
      </div>

      {byDay(selected).length === 0 && <p className="empty">Rest day.</p>}
      {byDay(selected).map((session) => (
        <DaySession
          key={session.id}
          session={session}
          weekNumber={week.number}
          dayNumber={trainingDays.indexOf(session.day) + 1}
        />
      ))}
    </>
  );
}

/** The session of the selected day, in full: header card, then its parts. */
function DaySession({
  session,
  weekNumber,
  dayNumber,
}: {
  session: SessionSummary;
  weekNumber: number;
  dayNumber: number;
}) {
  const detail = useApi<SessionDetail>(`/sessions/${session.id}`);
  const heading = (
    <section className="card">
      <div className="row">
        <h2>
          {session.kind === "rest" ? "Rest" : `Week ${weekNumber} / Day ${dayNumber}`}
        </h2>
        <span className="badge" data-status={session.status}>
          {session.status}
        </span>
      </div>
      <p>{session.title}</p>
      {session.moved_from && <p className="small">Moved from {shortDate(session.moved_from)}</p>}
    </section>
  );
  if (detail.status !== "ok") {
    return (
      <>
        {heading}
        <ApiStatus state={detail} />
      </>
    );
  }
  return <SessionView session={detail.data} mode="plan" heading={heading} />;
}
