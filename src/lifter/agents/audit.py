"""Write an agent run to the audit log (agent_run, agent_step; migration 007).

Every run of the week planner can be replayed from its row: the context the model received,
each answer with the guardrail's verdict, tokens and seconds per attempt, and the proposals it
produced. A run that crashed (the model's API unreachable) is recorded with its error.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from lifter.agents.context import PlanningContext
from lifter.agents.guardrail import Verdict
from lifter.agents.plan import WeekPlan


@dataclass(frozen=True)
class Step:
    """One attempt: the model's answer (None when it did not parse) and what it cost."""

    attempt: int
    plan: WeekPlan | None
    input_tokens: int
    output_tokens: int
    seconds: float


def _violations(verdict: Verdict | None) -> list[dict[str, Any]]:
    return [asdict(v) for v in verdict.violations] if verdict else []


def record_run(
    conn: psycopg.Connection,
    *,
    agent: str,
    trigger: str,
    model: str | None,
    ctx: PlanningContext,
    started_at: datetime,
    steps: list[Step],
    verdicts: list[Verdict],
    final_plan: WeekPlan | None = None,
    accepted: bool = False,
    proposal_ids: list[int] | None = None,
    error: str | None = None,
) -> int:
    """Insert the run and its attempts in one transaction; returns the run id."""
    status = "error" if error else ("accepted" if accepted else "refused")
    final = verdicts[-1] if verdicts else None
    with conn.transaction():
        run_id = conn.execute(
            "insert into agent_run (agent, trigger, model, context_mode, target_week_id, status,"
            " attempts, input_tokens, output_tokens, seconds, context, plan, warnings,"
            " proposal_ids, error, started_at)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " returning id",
            (
                agent,
                trigger,
                model,
                ctx.mode,
                ctx.target_week.week_id,
                status,
                len(steps),
                sum(s.input_tokens for s in steps),
                sum(s.output_tokens for s in steps),
                round(sum(s.seconds for s in steps), 3),
                Jsonb(ctx.model_dump(mode="json")),
                Jsonb(final_plan.model_dump(mode="json")) if final_plan else None,
                Jsonb(list(final.warnings) if final else []),
                proposal_ids or [],
                error,
                started_at,
            ),
        ).fetchone()[0]
        for step, verdict in zip(steps, verdicts + [None] * len(steps), strict=False):
            conn.execute(
                "insert into agent_step (run_id, attempt, plan, violations, input_tokens,"
                " output_tokens, seconds) values (%s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    step.attempt,
                    Jsonb(step.plan.model_dump(mode="json")) if step.plan else None,
                    Jsonb(_violations(verdict)),
                    step.input_tokens,
                    step.output_tokens,
                    round(step.seconds, 3),
                ),
            )
    return run_id
