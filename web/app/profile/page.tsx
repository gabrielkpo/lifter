"use client";

import ApiStatus from "@/components/ApiStatus";
import Stat from "@/components/Stat";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { label, shortDate } from "@/lib/format";
import type { Athlete, Goal, HealthIssue, Profile } from "@/lib/types";

/** Everything the coach knows about the athlete: who they are, what hurts, the rules. */
export default function ProfilePage() {
  const profile = useApi<Profile>("/profile");
  const goals = useApi<Goal[]>("/goals");

  if (profile.status !== "ok") {
    return (
      <>
        <TopBar title="Profile" />
        <ApiStatus state={profile} />
      </>
    );
  }
  const { athlete, health_issues: issues, rules } = profile.data;
  const open = issues.filter((i) => i.status !== "resolved");
  const resolved = issues.filter((i) => i.status === "resolved");
  const active =
    goals.status === "ok"
      ? goals.data.filter((g) => g.status === "active")
      : [];

  return (
    <>
      <TopBar eyebrow={athlete?.first_name ?? undefined} title="Profile" />

      {athlete ? (
        <AthleteCard athlete={athlete} />
      ) : (
        <p className="empty">No profile yet.</p>
      )}

      {active.length > 0 && (
        <>
          <h2 className="section-title">Goals</h2>
          <section className="card">
            <dl className="facts" style={{ marginTop: 0 }}>
              {active.map((goal) => (
                <Fact
                  key={goal.id}
                  name={goal.title}
                  value={goal.target_date ? monthYear(goal.target_date) : ""}
                />
              ))}
            </dl>
          </section>
        </>
      )}

      <h2 className="section-title">Health</h2>
      {open.length === 0 && (
        <p className="empty">
          Nothing declared. Tell the coach about a pain and it lands here.
        </p>
      )}
      {open.map((issue) => (
        <IssueCard key={issue.id} issue={issue} />
      ))}
      {resolved.length > 0 && (
        <details className="card">
          <summary className="muted">Resolved ({resolved.length})</summary>
          {resolved.map((issue) => (
            <p key={issue.id} className="small" style={{ marginTop: 8 }}>
              {where(issue)} · {issue.description}
              {issue.resolved_on &&
                ` · resolved ${shortDate(issue.resolved_on)}`}
            </p>
          ))}
        </details>
      )}

      {rules.length > 0 && (
        <>
          <h2 className="section-title">Rules</h2>
          <section className="card">
            {rules.map((rule, i) => (
              <p key={i} style={{ marginTop: i ? 10 : 0 }}>
                {rule.text}
              </p>
            ))}
          </section>
        </>
      )}
    </>
  );
}

function AthleteCard({ athlete }: { athlete: Athlete }) {
  const facts: [string, string | null][] = [
    ["Sex", athlete.sex && label(athlete.sex)],
    ["Handedness", athlete.handedness && label(athlete.handedness)],
    [
      "Training since",
      athlete.practice_since && monthYear(athlete.practice_since),
    ],
    ["Sessions per week", athlete.sessions_per_week?.toString() ?? null],
    ["Trains at", athlete.training_places.join(", ") || null],
    ["Weighed", athlete.weight_date && shortDate(athlete.weight_date)],
  ];
  return (
    <section className="card">
      <div className="row">
        <h2>Athlete</h2>
        {athlete.level && <span className="badge">{label(athlete.level)}</span>}
      </div>
      <div className="stats">
        <Stat value={athlete.age} name="Age" />
        <Stat value={athlete.height_cm} unit="cm" name="Height" />
        <Stat value={athlete.weight_kg} unit="kg" name="Weight" />
      </div>
      <dl className="facts">
        {facts
          .filter(([, value]) => value)
          .map(([name, value]) => (
            <Fact key={name} name={name} value={value as string} />
          ))}
      </dl>
      {athlete.context && (
        <p className="small" style={{ marginTop: 12 }}>
          {athlete.context}
        </p>
      )}
    </section>
  );
}

function Fact({ name, value }: { name: string; value: string }) {
  return (
    <>
      <dt>{name}</dt>
      <dd>{value}</dd>
    </>
  );
}

function IssueCard({ issue }: { issue: HealthIssue }) {
  return (
    <section className="card">
      <div className="row">
        <h2>{where(issue)}</h2>
        <span className="badge" data-status={issue.status}>
          {issue.status}
        </span>
      </div>
      <p>
        {label(issue.kind)}
        {issue.since && ` since ${shortDate(issue.since)}`}. {issue.description}
      </p>
      {issue.guidance && (
        <p className="small" style={{ marginTop: 8 }}>
          Coach: {issue.guidance}
        </p>
      )}
      {issue.reported_quote && (
        <p className="small" style={{ marginTop: 8 }}>
          You said: “{issue.reported_quote}”
        </p>
      )}
    </section>
  );
}

/** "Wrist (right)", "Ankle (both sides)", "Knee". */
function where(issue: HealthIssue): string {
  const side = issue.side === "both" ? "both sides" : issue.side;
  return label(issue.body_part) + (side ? ` (${side})` : "");
}

function monthYear(day: string): string {
  const [y, m] = day.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en", {
    month: "short",
    year: "numeric",
  });
}
