"use client";

import Link from "next/link";
import ApiStatus from "@/components/ApiStatus";
import PlanningTabs from "@/components/PlanningTabs";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { addDays, label, shortDate, today } from "@/lib/format";
import type { Program, Week } from "@/lib/types";

/** Every planned week, by cycle, with its sessions done. */
export default function WeeksPage() {
  const program = useApi<Program>("/program");
  const weeks = useApi<Week[]>("/weeks");

  return (
    <>
      <TopBar title="Planning" />
      <PlanningTabs />
      {weeks.status !== "ok" ? (
        <ApiStatus state={weeks} />
      ) : program.status === "loading" ? (
        // The cycles' names come with it: wait, so the weeks do not jump under them.
        <ApiStatus state={program} />
      ) : weeks.data.length === 0 ? (
        <p className="empty">No week planned yet.</p>
      ) : (
        groups(weeks.data, program.status === "ok" ? program.data : null).map((group) => (
          <section key={group.key}>
            {group.name && <h2 className="section-title">{group.name}</h2>}
            <ul className="list">
              {group.weeks.map((w) => {
                const now = w.start_date <= today() && today() <= addDays(w.start_date, 6);
                return (
                  <li key={w.id} style={{ fontSize: 16 }}>
                    <Link href={`/planning/weeks/${w.id}`} className="row" style={{ width: "100%" }}>
                      <span>
                        <strong>Week {w.number}</strong> · {label(w.phase)}
                        {now && (
                          <>
                            {" "}
                            <span className="badge">now</span>
                          </>
                        )}
                        <br />
                        <span className="small">{shortDate(w.start_date)}</span>
                      </span>
                      <span className="small">
                        {w.done}/{w.sessions} done ›
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </>
  );
}

/** Weeks under their cycle's name, in the program's order; a cycle the program lacks keeps
 * its weeks under no name rather than dropping them. */
function groups(weeks: Week[], program: Program | null) {
  const cycles = program?.cycles ?? [];
  const known = new Set(cycles.map((c) => c.id));
  const named = cycles
    .map((c) => ({ key: `c${c.id}`, name: c.name, weeks: weeks.filter((w) => w.cycle_id === c.id) }))
    .filter((g) => g.weeks.length > 0);
  const rest = weeks.filter((w) => !known.has(w.cycle_id));
  return rest.length > 0 ? [...named, { key: "rest", name: null, weeks: rest }] : named;
}
