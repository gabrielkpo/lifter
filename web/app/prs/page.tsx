"use client";

import { type CSSProperties, useState } from "react";
import TopBar from "@/components/TopBar";
import { useApi } from "@/lib/api";
import { CATALOGUE, type Family, type Kind, matches, type Movement } from "@/lib/catalogue";
import { num, shortDate } from "@/lib/format";
import type { Best, Goal } from "@/lib/types";

const SHOWN_REP_MAXES = [1, 3, 5];

export default function PrsPage() {
  const bests = useApi<Best[]>("/bests");
  const goals = useApi<Goal[]>("/goals");
  const [kindKey, setKindKey] = useState<Kind["key"]>("lift");
  const [family, setFamily] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const logged = bests.status === "ok" ? bests.data : [];
  // The athlete's own benchmarks (goals of kind benchmark) join the public ones.
  const own: Family[] =
    goals.status === "ok" && goals.data.some((g) => g.kind === "benchmark")
      ? [
          {
            key: "own",
            label: "Mine",
            tone: "--purple",
            movements: goals.data
              .filter((g) => g.kind === "benchmark")
              .map((g) => ({ name: g.title, record: "time", description: g.notes ?? undefined })),
          },
        ]
      : [];
  const kind = CATALOGUE.find((k) => k.key === kindKey)!;
  const families = kind.key === "benchmarks" ? [...kind.families, ...own] : kind.families;
  const needle = query.trim().toLowerCase();
  const shown = families
    .filter((f) => family === null || f.key === family)
    .map((f) => ({
      ...f,
      movements: f.movements.filter((m) => needle === "" || m.name.toLowerCase().includes(needle)),
    }))
    .filter((f) => f.movements.length > 0);

  return (
    <>
      <TopBar title="PRs" />
      <div className="pills" role="group" aria-label="Kind">
        {CATALOGUE.map((k) => (
          <button
            key={k.key}
            className="pill"
            aria-pressed={k.key === kindKey}
            onClick={() => {
              setKindKey(k.key);
              setFamily(null);
            }}
          >
            {k.label}
          </button>
        ))}
      </div>
      <div className="chips" role="group" aria-label="Family">
        <button className="chip" aria-pressed={family === null} onClick={() => setFamily(null)}>
          All
        </button>
        {families.map((f) => (
          <button
            key={f.key}
            className="chip"
            data-tone
            style={{ "--tone": `var(${f.tone})` } as CSSProperties}
            aria-pressed={family === f.key}
            onClick={() => setFamily(family === f.key ? null : f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {shown.map((f) => (
        <section key={f.key}>
          <h2 className="section-title" style={{ "--tone": `var(${f.tone})` } as CSSProperties}>
            {f.label} <span className="dot" />
          </h2>
          <ul className="list">
            {f.movements.map((m) => (
              <li key={m.name}>
                <span>
                  {m.name}
                  {m.description && (
                    <>
                      <br />
                      <span className="small">{m.description}</span>
                    </>
                  )}
                </span>
                <Record movement={m} bests={logged} />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {shown.length === 0 && <p className="empty">No exercise matches.</p>}

      <div className="search-spacer" />
      <div className="search">
        <input
          type="search"
          placeholder="Search an exercise"
          aria-label="Search an exercise"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
    </>
  );
}

/** The movement's records: rep maxes from logged sets for a lift, nothing yet for the rest. */
function Record({ movement, bests }: { movement: Movement; bests: Best[] }) {
  if (movement.record !== "rep_max") return <span className="small">–</span>;
  const own = bests.filter((b) => matches(movement, b.exercise));
  const rms = SHOWN_REP_MAXES.map((reps) =>
    own.filter((b) => b.reps === reps).sort((a, b) => b.best_load_kg - a.best_load_kg)[0],
  ).filter((b): b is Best => b !== undefined);
  if (rms.length === 0) return <span className="small">–</span>;
  return (
    <span className="small" style={{ textAlign: "right" }}>
      {rms.map((b, i) => (
        <span key={b.reps} title={shortDate(b.day)}>
          {i > 0 && " · "}
          {b.reps}RM <strong>{num(b.best_load_kg)} kg</strong>
        </span>
      ))}
    </span>
  );
}
