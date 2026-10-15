"""The week planner as a LangGraph graph: plan (LLM) → guardrail (code) → retry or finish.

    START → plan → guard ─ok──────────────► END
                     └─refused, retries left → plan (with the reasons)

Nothing is written unless asked: `run_week_planner(..., propose=True)` turns an accepted plan
into proposals (create_session, cancel_session) that the athlete approves or rejects; code
applies them (lifter.domain). A plan still refused after the retries proposes nothing. With a
`trigger`, the run is recorded in the audit log (lifter.agents.audit), errors included.
"""

import operator
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, TypedDict

import psycopg
from langgraph.graph import END, START, StateGraph

from lifter import domain
from lifter.agents.audit import Step, record_run
from lifter.agents.context import ContextMode, PlanningContext, build_context
from lifter.agents.guardrail import Verdict, Violation, check
from lifter.agents.plan import WeekPlan
from lifter.agents.planner import Planner, PlannerOutputError

MAX_ATTEMPTS = 3  # the first plan and two corrections
AUTHOR = "week_planner"


class State(TypedDict, total=False):
    context: PlanningContext
    plan: WeekPlan | None
    verdict: Verdict | None
    verdicts: Annotated[list[Verdict], operator.add]  # one per attempt, for the bench
    feedback: list[str]
    attempts: int


def build_graph(planner: Planner, steps: list[Step] | None = None):
    """The graph; `steps` collects each attempt's answer, tokens and seconds for the audit."""
    steps = steps if steps is not None else []

    def plan_node(state: State) -> State:
        attempts = state.get("attempts", 0) + 1
        tokens_in, tokens_out = planner.usage.input_tokens, planner.usage.output_tokens
        started = time.monotonic()

        def step(plan):
            steps.append(
                Step(
                    attempt=attempts,
                    plan=plan,
                    input_tokens=planner.usage.input_tokens - tokens_in,
                    output_tokens=planner.usage.output_tokens - tokens_out,
                    seconds=time.monotonic() - started,
                )
            )

        try:
            plan = planner(state["context"], state.get("feedback", []))
        except PlannerOutputError as exc:
            step(None)
            refused = Verdict([Violation("schema", str(exc))], [], [])
            return {"plan": None, "verdict": refused, "attempts": attempts}
        step(plan)
        return {"plan": plan, "verdict": None, "attempts": attempts}

    def guard_node(state: State) -> State:
        if state["plan"] is None:  # the model's output did not even parse
            verdict = state["verdict"]
        else:
            verdict = check(state["plan"], state["context"])
        return {
            "verdict": verdict,
            "verdicts": [verdict],
            "feedback": [str(v) for v in verdict.violations],
        }

    def route(state: State) -> str:
        if state["verdict"].ok or state["attempts"] >= MAX_ATTEMPTS:
            return END
        return "plan"

    graph = StateGraph(State)
    graph.add_node("plan", plan_node)
    graph.add_node("guard", guard_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "guard")
    graph.add_conditional_edges("guard", route, ["plan", END])
    return graph.compile()


@dataclass
class WeekPlannerResult:
    context: PlanningContext
    plan: WeekPlan | None
    verdict: Verdict
    attempts: int
    verdicts: list[Verdict] = field(default_factory=list)
    seconds: float = 0.0
    proposal_ids: list[int] = field(default_factory=list)
    run_id: int | None = None

    @property
    def accepted(self) -> bool:
        return self.plan is not None and self.verdict.ok


def run_week_planner(
    conn: psycopg.Connection,
    planner: Planner,
    *,
    week_number: int | None = None,
    today: date | None = None,
    mode: ContextMode = "indicators",
    propose: bool = False,
    trigger: str | None = None,
) -> WeekPlannerResult:
    """Plan a week; `trigger` (cli, app, job, bench) records the run in the audit log."""
    ctx = build_context(conn, week_number=week_number, today=today, mode=mode)
    started_at = datetime.now(UTC)
    started = time.monotonic()
    steps: list[Step] = []
    audit = {
        "agent": AUTHOR,
        "trigger": trigger,
        "model": getattr(planner, "model", None),
        "ctx": ctx,
        "started_at": started_at,
        "steps": steps,
    }
    try:
        state = build_graph(planner, steps).invoke(
            {"context": ctx, "attempts": 0, "feedback": [], "verdicts": []}
        )
    except Exception as exc:
        if trigger:  # the error's type and message only: never the request or its headers
            record_run(conn, **audit, verdicts=[], error=f"{type(exc).__name__}: {exc}")
        raise
    result = WeekPlannerResult(
        context=ctx,
        plan=state.get("plan"),
        verdict=state["verdict"],
        attempts=state["attempts"],
        verdicts=state["verdicts"],
        seconds=time.monotonic() - started,
    )
    if propose and result.accepted:
        result.proposal_ids = propose_plan(conn, result.plan, ctx)
    if trigger:
        result.run_id = record_run(
            conn,
            **audit,
            verdicts=result.verdicts,
            final_plan=result.plan,
            accepted=result.accepted,
            proposal_ids=result.proposal_ids,
        )
    return result


def propose_plan(conn: psycopg.Connection, plan: WeekPlan, ctx: PlanningContext) -> list[int]:
    """One proposal per change, all or nothing; the athlete decides each one."""
    week_id = ctx.target_week.week_id
    ids = []
    with conn.transaction():
        for session_id in plan.cancel_session_ids:
            ids.append(
                domain.propose(
                    conn,
                    "cancel_session",
                    {"session_id": session_id},
                    rationale=f"Replaced by the plan of week {ctx.target_week.number}: "
                    + plan.summary,
                    author=AUTHOR,
                )
            )
        for session in plan.sessions:
            ids.append(
                domain.propose(
                    conn,
                    "create_session",
                    session.to_session_in(week_id).model_dump(mode="json"),
                    rationale=session.rationale,
                    author=AUTHOR,
                )
            )
    return ids
