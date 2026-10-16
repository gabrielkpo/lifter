import type { ReactNode } from "react";
import Stat from "@/components/Stat";
import { label, partFormat, partResult, partTarget, prescription, shortDate } from "@/lib/format";
import type { Line, Part, SessionDetail } from "@/lib/types";

/**
 * A session, in one of two readings:
 * - "plan": the workout to do (the WOD tab): what is prescribed, then the athlete's note;
 * - "done": what was actually done (the week page): logged lines, metcon result, Garmin line.
 */
export default function SessionView({
  session,
  mode,
  heading,
}: {
  session: SessionDetail;
  mode: "plan" | "done";
  /** Replaces the date and title header (the WOD tab and the week page show their own). */
  heading?: ReactNode;
}) {
  return (
    <>
      {heading ?? (
        <>
          <p className="eyebrow muted small">{shortDate(session.day)}</p>
          <div className="row">
            <h1 style={{ margin: "4px 0 12px", fontSize: 28 }}>{session.title}</h1>
            <span className="badge" data-status={session.status}>
              {session.status}
            </span>
          </div>
        </>
      )}

      <div className="parts">
        {session.parts
          // Nothing prescribed (a warm-up left free): nothing to show in the plan.
          .filter((part) => mode === "done" || part.planned.length > 0 || part.notes || part.format)
          .map((part) =>
          mode === "plan" ? (
            <PlannedPart key={part.position} part={part} />
          ) : (
            <DonePart key={part.position} part={part} />
          ),
        )}
      </div>

      {mode === "plan" ? <Note session={session} /> : <DoneFooter session={session} />}
    </>
  );
}

function PlannedPart({ part }: { part: Part }) {
  const format = partFormat(part);
  const target = partTarget(part);
  return (
    <section className="card">
      <h2>{part.title ?? label(part.kind)}</h2>
      {(format || target) && (
        <p className="small" style={{ marginBottom: 10 }}>
          {[format, target].filter(Boolean).join(" · ")}
        </p>
      )}
      <Lines lines={part.planned} />
      {part.notes && <p className="small">{part.notes}</p>}
    </section>
  );
}

function DonePart({ part }: { part: Part }) {
  const target = partTarget(part);
  const result = partResult(part);
  const logged = part.done.length > 0;
  return (
    <section className="card">
      <div className="row">
        <h2>{part.title ?? label(part.kind)}</h2>
        {result && <strong>{result}</strong>}
      </div>
      {(partFormat(part) || target) && (
        <p className="small" style={{ marginBottom: 10 }}>
          {[partFormat(part), target].filter(Boolean).join(" · ")}
        </p>
      )}
      {logged ? (
        <Lines lines={part.done} />
      ) : (
        <div style={{ opacity: result ? 1 : 0.5 }}>
          <Lines lines={part.planned} />
          {/* A metcon logged by its result only: its movements were the planned ones. */}
          <p className="small">{result ? "As planned." : "Not logged: shown as planned."}</p>
        </div>
      )}
      {part.result_notes && <p className="small">{part.result_notes}</p>}
    </section>
  );
}

function Note({ session }: { session: SessionDetail }) {
  return (
    <section className="card">
      <h2>Note</h2>
      {session.notes || session.deviation ? (
        <>
          {session.notes && <p>{session.notes}</p>}
          {session.deviation && <p>{session.deviation}</p>}
        </>
      ) : (
        <p className="small">
          What you did, added or skipped. Writing it from the app comes with the session log.
        </p>
      )}
    </section>
  );
}

function DoneFooter({ session }: { session: SessionDetail }) {
  const g = session.garmin;
  return (
    <>
      {g && (
        <section className="card">
          <h2>Garmin</h2>
          <div className="stats">
            <Stat value={g.duration_minutes} unit="min" name="Duration" />
            <Stat value={g.avg_hr_bpm} unit="bpm" name="Avg HR" />
            <Stat value={g.max_hr_bpm} unit="bpm" name="Max HR" />
            <Stat value={g.z4_z5_minutes} unit="min" name="Z4–Z5" />
            <Stat value={g.training_load} name="Load" />
            <Stat value={g.calories} unit="kcal" name="Calories" />
          </div>
        </section>
      )}
      {(session.notes || session.deviation) && (
        <section className="card">
          <h2>Note</h2>
          {session.notes && <p>{session.notes}</p>}
          {session.deviation && <p>{session.deviation}</p>}
        </section>
      )}
    </>
  );
}

function Lines({ lines }: { lines: Line[] }) {
  if (lines.length === 0) return <p className="line muted">–</p>;
  return lines.map((line) => (
    <p key={line.position} className="line">
      <b>{line.exercise}</b>
      <span>
        {prescription(line)}
        {line.rir !== null && ` · RIR ${line.rir}`}
        {line.rest_seconds !== null && ` · rest ${line.rest_seconds}s`}
      </span>
      {line.notes && <span> · {line.notes}</span>}
    </p>
  ));
}
