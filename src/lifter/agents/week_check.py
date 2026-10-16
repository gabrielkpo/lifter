"""The guardrail on a week as it stands in the database, for changes applied by the coach.

ADR 0002, Decision 3: an operation that changes the programme is checked before commit, on the
week as it would be. Whoever applies changes registers `violations_for_week` and `introduced`
as the catalogue's programme check first (`operations.set_programme_check`, so the domain does
not import the agents); without it, the catalogue refuses every operation on the programme. It
calls them inside the operation's transaction, before and after applying it, and
refuses the change only for the violations it **introduces** (`introduced`): a week that
already broke a rule (an old draft, imported data) must not block every unrelated change, nor
the move of the session at fault.

The stored week is turned into a `WeekPlan` (its sessions, their parts and planned lines) and
checked with the same guardrail as the week planner's plans. Checks that only make sense for a
model's answer are left out: cited numbers (no text here) and cancellations.
"""

from collections import Counter
from datetime import date

import psycopg

from lifter.agents.context import PlanningContext, build_context
from lifter.agents.guardrail import Violation, check
from lifter.agents.plan import PlanSession, WeekPlan, plan_part

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
            parts=[plan_part(part, part.planned) for part in s.parts],
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
    """Violations present after the change and not before it, counted by check and message:
    the day is left out, so moving the session at fault introduces nothing, and a second
    identical violation counts as new."""
    left = Counter((v.check, v.message) for v in before)
    new = []
    for v in after:
        key = (v.check, v.message)
        if left[key]:
            left[key] -= 1
        else:
            new.append(v)
    return new
