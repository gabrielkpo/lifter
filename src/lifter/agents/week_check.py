"""The guardrail on a week as it stands in the database, for changes applied by the coach.

ADR 0002, Decision 3: an operation that changes the programme is checked before commit, on the
week as it would be. The catalogue calls `violations_for_week` inside the operation's
transaction, before and after applying it, and refuses the change only for the violations it
**introduces** (`introduced`): a week that already broke a rule (an old draft, imported data)
must not block every unrelated change.

The stored week is turned into a `WeekPlan` (its sessions, their parts and planned lines) and
checked with the same guardrail as the week planner's plans. Checks that only make sense for a
model's answer are left out: cited numbers (no text here) and cancellations.
"""

from datetime import date

import psycopg

from lifter.agents.context import PlanningContext, build_context
from lifter.agents.guardrail import Violation, check
from lifter.agents.plan import PlanLine, PlanPart, PlanSession, WeekPlan

MODEL_ONLY_CHECKS = ("sources", "cancellations")
OPEN = ("planned", "missed")


def plan_from_context(ctx: PlanningContext) -> WeekPlan:
    """The week's stored sessions as a plan; open sessions are listed as replaced, so the
    guardrail does not count them twice (once in the plan, once as kept)."""
    stored = [s for s in ctx.sessions_already_planned if s.status not in ("cancelled", "rest")]
    sessions = [
        PlanSession(
            day=s.day,
            title=s.title,
            kind=s.kind,
            rationale="As stored.",
            parts=[
                PlanPart(
                    kind=part.kind,
                    format=part.format,
                    duration_minutes=part.duration_minutes,
                    rounds=part.rounds,
                    interval_seconds=part.interval_seconds,
                    target_seconds=part.target_seconds,
                    target_rounds=part.target_rounds,
                    lines=[
                        PlanLine(
                            exercise=line.exercise,
                            sets=line.sets,
                            quantity=line.quantity,
                            unit=line.unit,
                            load_kg=line.load_kg,
                            load_kg_max=line.load_kg_max,
                            rir=line.rir,
                        )
                        for line in part.planned
                    ],
                )
                for part in s.parts
            ],
        )
        for s in stored
    ]
    return WeekPlan(
        summary="The week as stored.",
        sessions=sessions,
        cancel_session_ids=[s.session_id for s in stored if s.status in OPEN],
    )


def violations_for_week(
    conn: psycopg.Connection, week_id: int, *, today: date | None = None
) -> list[Violation]:
    """The guardrail's violations on week `week_id` as it is in the database right now."""
    ctx = build_context(conn, week_id=week_id, today=today)
    verdict = check(plan_from_context(ctx), ctx)
    return [v for v in verdict.violations if v.check not in MODEL_ONLY_CHECKS]


def introduced(before: list[Violation], after: list[Violation]) -> list[Violation]:
    """Violations present after the change and not before it."""
    seen = {(v.check, v.day, v.message) for v in before}
    return [v for v in after if (v.check, v.day, v.message) not in seen]
