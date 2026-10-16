"use client";

import ApiStatus from "@/components/ApiStatus";
import PlanningTabs from "@/components/PlanningTabs";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { num, shortDate, today } from "@/lib/format";
import type { Goal } from "@/lib/types";

/** The goals as a table: the target and its date first (all a phone shows before scrolling),
 * then where each started and the next milestone. */
export default function GoalsPage() {
  const goals = useApi<Goal[]>("/goals");

  return (
    <>
      <TopBar title="Planning" />
      <PlanningTabs />
      {goals.status !== "ok" ? (
        <ApiStatus state={goals} />
      ) : goals.data.length === 0 ? (
        <p className="empty">No goal yet.</p>
      ) : (
        // Scrolls sideways on a phone rather than squeezing the columns; the goal stays put.
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Goal</th>
                <th scope="col">Target</th>
                <th scope="col">By</th>
                <th scope="col">Start</th>
                <th scope="col">Next milestone</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {goals.data.map((g) => {
                const next = g.milestones.find((m) => m.day >= today());
                return (
                  <tr key={g.id}>
                    <th scope="row">{g.title}</th>
                    <td className={g.target_value === null ? "strong text" : "strong"}>
                      {value(g.target_value, g.target_text, g.unit)}
                    </td>
                    <td>{g.target_date ? shortDate(g.target_date) : "–"}</td>
                    <td className={g.baseline_value === null ? "text" : undefined}>
                      {value(g.baseline_value, g.baseline_text, g.unit)}
                    </td>
                    <td className={next && next.value === null ? "text" : undefined}>
                      {next
                        ? `${value(next.value, next.value_text, g.unit)} · ${shortDate(next.day)}`
                        : "–"}
                    </td>
                    <td>
                      <span
                        className="badge"
                        data-status={g.status === "achieved" ? "done" : undefined}
                      >
                        {g.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function value(n: number | null, text: string | null, unit: string | null): string {
  if (n !== null) return unit ? `${num(n)} ${unit}` : num(n);
  return text ?? "–";
}
