"""Run a planner on the bench's scenarios and measure it.

For each scenario the bench database is emptied, the scenario's situation is set up, then the
planner runs `runs` times on it (the model's answers vary; the spread is measured). Nothing is
proposed: plans are only checked.

Measured per run (docs/bench.md): accepted or not, attempts, constraint violations of the
first plan (before any correction) and of the final one, answers that did not parse, numbers
cited without a source, expectations met, tokens and seconds.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import psycopg

from lifter.agents.planner import Planner
from lifter.agents.week import run_week_planner
from lifter.bench.expect import Outcome, evaluate
from lifter.bench.scenario import Scenario, apply_setup

KEEP_TABLES = ("schema_migrations", "schema_views")


@dataclass
class RunResult:
    scenario: str
    category: str
    run: int
    accepted: bool
    attempts: int
    first_violations: int
    final_violations: int
    schema_failures: int
    unsourced_numbers: int
    expectations_met: int
    expectations: int
    outcomes: list[Outcome]
    input_tokens: int
    output_tokens: int
    seconds: float


def reset(conn: psycopg.Connection) -> None:
    """Empty every table of the bench database, whatever migrations added."""
    tables = [
        row[0]
        for row in conn.execute(
            "select tablename from pg_tables where schemaname = 'public' and tablename <> all(%s)",
            (list(KEEP_TABLES),),
        ).fetchall()
    ]
    if tables:
        names = ", ".join(f'public."{t}"' for t in tables)  # names read from the catalog
        conn.execute(f"truncate {names} restart identity cascade")


def run_scenario(
    conn: psycopg.Connection, scenario: Scenario, make_planner: Callable[[], Planner], runs: int
) -> list[RunResult]:
    reset(conn)
    apply_setup(conn, scenario)
    results = []
    for run in range(1, runs + 1):
        planner = make_planner()
        result = run_week_planner(
            conn,
            planner,
            week_number=scenario.target_week,
            today=scenario.today,
            trigger="bench",
        )
        outcomes = evaluate(scenario.expect, result)
        first = result.verdicts[0].violations if result.verdicts else []
        every = [v for verdict in result.verdicts for v in verdict.violations]
        results.append(
            RunResult(
                scenario=scenario.name,
                category=scenario.category,
                run=run,
                accepted=result.accepted,
                attempts=result.attempts,
                # rule breaks only: an answer that did not parse is counted apart
                first_violations=sum(1 for v in first if v.check != "schema"),
                final_violations=sum(1 for v in result.verdict.violations if v.check != "schema"),
                schema_failures=sum(1 for v in every if v.check == "schema"),
                unsourced_numbers=sum(len(v.items) for v in every if v.check == "sources"),
                expectations_met=sum(o.passed for o in outcomes),
                expectations=len(outcomes),
                outcomes=outcomes,
                input_tokens=planner.usage.input_tokens,
                output_tokens=planner.usage.output_tokens,
                seconds=round(result.seconds, 2),
            )
        )
    return results


def summary(results: list[RunResult]) -> dict:
    runs = len(results) or 1
    met = sum(r.expectations_met for r in results)
    total = sum(r.expectations for r in results) or 1
    return {
        "runs": len(results),
        "accepted_rate": round(sum(r.accepted for r in results) / runs, 3),
        "first_plan_violations": sum(r.first_violations for r in results),
        "final_violations": sum(r.final_violations for r in results),
        "schema_failures": sum(r.schema_failures for r in results),
        "unsourced_numbers": sum(r.unsourced_numbers for r in results),
        "expectations_met_rate": round(met / total, 3),
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
        "seconds": round(sum(r.seconds for r in results), 1),
    }


def write_results(path: Path, planner: str, model: str | None, results: list[RunResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "planner": planner,
        "model": model,
        "summary": summary(results),
        "runs": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
