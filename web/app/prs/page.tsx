"use client";

import { type CSSProperties, useState } from "react";
import ApiStatus from "@/components/ApiStatus";
import TopBar from "@/components/TopBar";
import { type ApiState, useApi } from "@/lib/api";
import { label, num, shortDate } from "@/lib/format";
import type { Best, Goal } from "@/lib/types";

// Kinds of the tab, from the exercise bank's categories. The finer families of the reference
// app (squats, cleans, snatches...) need a family on each exercise: until the domain has it,
// movements are grouped by movement pattern.
const KINDS = [
  { key: "lift", label: "Lift", categories: ["weightlifting", "strength"] },
  { key: "gym", label: "Gym", categories: ["gymnastics"] },
  { key: "cardio", label: "Cardio", categories: ["monostructural"] },
  { key: "benchmarks", label: "Benchmarks", categories: [] },
] as const;

const TONES = ["--red", "--blue", "--amber", "--green", "--purple"];

type Movement = { exercise: string; pattern: string; bests: Best[] };

function movements(bests: Best[]): Movement[] {
  const byExercise = new Map<string, Movement>();
  for (const best of bests) {
    const movement = byExercise.get(best.exercise) ?? {
      exercise: best.exercise,
      pattern: best.pattern,
      bests: [],
    };
    movement.bests.push(best);
    byExercise.set(best.exercise, movement);
  }
  return [...byExercise.values()];
}

export default function PrsPage() {
  const bests = useApi<Best[]>("/bests");
  const goals = useApi<Goal[]>("/goals");
  const [kind, setKind] = useState<(typeof KINDS)[number]["key"]>("lift");
  const [family, setFamily] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const current = KINDS.find((k) => k.key === kind)!;
  const pickKind = (key: typeof kind) => {
    setKind(key);
    setFamily(null);
  };

  return (
    <>
      <TopBar title="PRs" />
      <div className="pills" role="group" aria-label="Kind">
        {KINDS.map((k) => (
          <button
            key={k.key}
            className="pill"
            aria-pressed={k.key === kind}
            onClick={() => pickKind(k.key)}
          >
            {k.label}
          </button>
        ))}
      </div>

      {kind === "benchmarks" ? (
        <Benchmarks state={goals} query={query} />
      ) : bests.status !== "ok" ? (
        <ApiStatus state={bests} />
      ) : (
        <Movements
          all={movements(
            bests.data.filter((b) => (current.categories as readonly string[]).includes(b.category)),
          )}
          family={family}
          setFamily={setFamily}
          query={query}
        />
      )}

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

function Movements({
  all,
  family,
  setFamily,
  query,
}: {
  all: Movement[];
  family: string | null;
  setFamily: (family: string | null) => void;
  query: string;
}) {
  const families = [...new Set(all.map((m) => m.pattern))].sort();
  const tone = (f: string) => `var(${TONES[families.indexOf(f) % TONES.length]})`;
  const needle = query.trim().toLowerCase();
  const shown = all.filter(
    (m) =>
      (family === null || m.pattern === family) &&
      (needle === "" || m.exercise.toLowerCase().includes(needle)),
  );

  if (all.length === 0) {
    return <p className="empty">No record yet: they come from the sets you log.</p>;
  }
  return (
    <>
      <div className="chips" role="group" aria-label="Family">
        <button className="chip" aria-pressed={family === null} onClick={() => setFamily(null)}>
          All
        </button>
        {families.map((f) => (
          <button
            key={f}
            className="chip"
            data-tone
            style={{ "--tone": tone(f) } as CSSProperties}
            aria-pressed={family === f}
            onClick={() => setFamily(family === f ? null : f)}
          >
            {label(f)}
          </button>
        ))}
      </div>

      {families
        .filter((f) => shown.some((m) => m.pattern === f))
        .map((f) => (
          <section key={f}>
            <h2 className="section-title" style={{ "--tone": tone(f) } as CSSProperties}>
              {label(f)} <span className="dot" />
            </h2>
            <ul className="list">
              {shown
                .filter((m) => m.pattern === f)
                .map((m) => (
                  <li key={m.exercise}>
                    <span>{m.exercise}</span>
                    <span className="small">
                      {m.bests.map((b, i) => (
                        <span key={b.reps} title={shortDate(b.day)}>
                          {i > 0 && " · "}
                          {num(b.reps)}RM <strong>{num(b.best_load_kg)} kg</strong>
                        </span>
                      ))}
                    </span>
                  </li>
                ))}
            </ul>
          </section>
        ))}
      {shown.length === 0 && <p className="empty">No exercise matches.</p>}
    </>
  );
}

function Benchmarks({
  state,
  query,
}: {
  state: ApiState<Goal[]>;
  query: string;
}) {
  if (state.status !== "ok") return <ApiStatus state={state} />;
  const needle = query.trim().toLowerCase();
  const benchmarks = state.data.filter(
    (g) => g.kind === "benchmark" && g.title.toLowerCase().includes(needle),
  );
  if (benchmarks.length === 0) return <p className="empty">No benchmark yet.</p>;
  return (
    <ul className="list" style={{ marginTop: 16 }}>
      {benchmarks.map((g) => (
        <li key={g.id}>
          <span>{g.title}</span>
          <span className="small">
            {g.baseline_value ?? g.baseline_text ?? "–"} →{" "}
            <strong>{g.target_value ?? g.target_text}</strong>
          </span>
        </li>
      ))}
    </ul>
  );
}
