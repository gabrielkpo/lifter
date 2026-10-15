"use client";

import Stat from "@/components/Stat";
import ApiStatus from "@/components/ApiStatus";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { label, num, shortDate } from "@/lib/format";
import type { CalendarItem, DailyMetrics, Health } from "@/lib/types";

const DAYS = 28;

/** Health, read against training: recovery each morning next to the sessions of that day. */
export default function HealthPage() {
  const health = useApi<Health>(`/health?days=${DAYS}`);
  const metrics = health.status === "ok" ? health.data.metrics : [];
  const first = metrics.at(0)?.day;
  const last = metrics.at(-1)?.day;
  const calendar = useApi<CalendarItem[]>(
    first && last ? `/calendar?start=${first}&end=${last}` : null,
  );

  if (health.status !== "ok") {
    return (
      <>
        <TopBar title="Health" />
        <ApiStatus state={health} />
      </>
    );
  }
  const today = health.data.metrics.at(-1);
  const recovery = health.data.recovery.at(-1);
  if (!today) {
    return (
      <>
        <TopBar title="Health" />
        <p className="empty">No Garmin data yet: run `uv run lifter sync`.</p>
      </>
    );
  }
  const sessions = calendar.status === "ok" ? calendar.data.filter((i) => i.kind === "session") : [];
  const alerts = health.data.alerts.filter((a) => a.day === today.day);

  return (
    <>
      <TopBar eyebrow={shortDate(today.day)} title="Health" />

      <section className="card">
        <div className="row">
          <h2>Recovery</h2>
          <span className="badge" data-status={today.recovery_status}>
            {today.recovery_status}
          </span>
        </div>
        <div className="stats">
          <Stat value={today.recovery_score} name="Score" />
          <Stat value={today.hrv_delta_pct} unit="%" name="HRV vs base" signed />
          <Stat value={today.rhr_delta_bpm} unit="bpm" name="RHR vs base" signed />
          <Stat value={today.sleep_hours} unit="h" name="Sleep" />
          <Stat value={recovery?.readiness_score ?? null} name="Readiness" />
          <Stat value={recovery?.body_battery_highest ?? null} name="Body battery" />
        </div>
        <p className="small" style={{ marginTop: 10 }}>
          Trend: {label(today.trend)}
          {today.recovery_7d_avg !== null && ` · 7-day average ${num(today.recovery_7d_avg)}`}
        </p>
      </section>

      {alerts.length > 0 && (
        <section className="card accent">
          <h2>Alerts</h2>
          {alerts.map((a) => (
            <p key={a.alert} className="row">
              <span>{label(a.alert)}</span>
              <span className="badge" data-status={a.severity}>
                {a.severity}
              </span>
            </p>
          ))}
        </section>
      )}

      <section className="card">
        <h2>Recovery and training</h2>
        <p className="small">
          Morning recovery score, last {DAYS} days. White: a session was done that day; grey:
          no session. Read it as: did you train on good mornings, and how did you recover the
          days after?
        </p>
        <RecoveryBars metrics={health.data.metrics} sessions={sessions} />
        <ul className="list" style={{ margin: "14px -18px 0" }}>
          {sessions
            .filter((s) => s.status === "done" || s.status === "missed")
            .slice(-6)
            .reverse()
            .map((s) => {
              const m = health.data.metrics.find((d) => d.day === s.day);
              return (
                <li key={`${s.day}-${s.session_id}`} style={{ fontSize: 15 }}>
                  <span>
                    <strong>{s.title}</strong>
                    <br />
                    <span className="small">{shortDate(s.day)}</span>
                  </span>
                  <span className="small">
                    <span className="badge" data-status={s.status}>
                      {s.status}
                    </span>{" "}
                    recovery {m?.recovery_score ?? "–"}
                  </span>
                </li>
              );
            })}
        </ul>
      </section>

      <section className="card">
        <h2>Load</h2>
        <div className="stats">
          <Stat value={today.acute_load_7d} name="7-day load" />
          <Stat value={today.chronic_load_28d} name="28-day / week" />
          <Stat value={today.acwr} name="Ratio" />
        </div>
      </section>
    </>
  );
}

function RecoveryBars({
  metrics,
  sessions,
}: {
  metrics: DailyMetrics[];
  sessions: CalendarItem[];
}) {
  return (
    <div className="bars" role="img" aria-label="Recovery score by day, sessions highlighted">
      {metrics.map((m) => (
        <div
          key={m.day}
          title={`${shortDate(m.day)}: ${m.recovery_score ?? "no score"}`}
          data-trained={sessions.some((s) => s.day === m.day && s.status === "done")}
          style={{ height: `${Math.max(4, m.recovery_score ?? 0)}%` }}
        />
      ))}
    </div>
  );
}
