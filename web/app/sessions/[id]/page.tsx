"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import ApiStatus from "@/components/ApiStatus";
import { BackIcon } from "@/components/icons";
import { useApi } from "@/lib/api";
import { label, partFormat, partResult, partTarget, prescription, shortDate } from "@/lib/format";
import type { Line, Part, SessionDetail } from "@/lib/types";

/** A session: each part with what was planned and what was done, side by side. */
export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const state = useApi<SessionDetail>(/^\d+$/.test(id) ? `/sessions/${id}` : null);

  return (
    <>
      <header className="topbar">
        <Link href="/wod" className="avatar" aria-label="Back to the week">
          <BackIcon />
        </Link>
      </header>
      {state.status === "ok" ? <Session session={state.data} /> : <ApiStatus state={state} />}
    </>
  );
}

function Session({ session }: { session: SessionDetail }) {
  const g = session.garmin;
  return (
    <>
      <p className="eyebrow muted small">{shortDate(session.day)}</p>
      <div className="row">
        <h1 style={{ margin: "4px 0 12px", fontSize: 28 }}>{session.title}</h1>
        <span className="badge" data-status={session.status}>
          {session.status}
        </span>
      </div>
      {session.moved_from && (
        <p className="muted small">Moved from {shortDate(session.moved_from)}</p>
      )}

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

      {session.parts.map((part) => (
        <PartCard key={part.position} part={part} />
      ))}

      {(session.notes || session.deviation) && (
        <section className="card">
          <h2>Notes</h2>
          {session.notes && <p>{session.notes}</p>}
          {session.deviation && <p>Deviation: {session.deviation}</p>}
        </section>
      )}
    </>
  );
}

function PartCard({ part }: { part: Part }) {
  const target = partTarget(part);
  const result = partResult(part);
  const format = partFormat(part);
  return (
    <section className={part.kind === "metcon" ? "card accent" : "card"}>
      <h2>{part.title ?? label(part.kind)}</h2>
      {format && <p className="small">{format}</p>}
      {(target || result) && (
        <p className="row" style={{ marginTop: 6 }}>
          <span>{target ?? ""}</span>
          <strong style={{ color: "var(--text)" }}>{result ?? ""}</strong>
        </p>
      )}
      <div className="compare">
        <div>
          <div className="head">Planned</div>
          <Lines lines={part.planned} />
        </div>
        <div>
          <div className="head">Done</div>
          <Lines lines={part.done} />
        </div>
      </div>
      {part.result_notes && <p className="small" style={{ marginTop: 8 }}>{part.result_notes}</p>}
      {part.notes && <p className="small" style={{ marginTop: 8 }}>{part.notes}</p>}
    </section>
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

function Stat({ value, unit, name }: { value: number | null; unit?: string; name: string }) {
  return (
    <div className="stat">
      <div className="value">
        {value ?? "–"}
        {value !== null && unit && <span className="small muted"> {unit}</span>}
      </div>
      <div className="name">{name}</div>
    </div>
  );
}
