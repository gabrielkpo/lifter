"""The week planner as a LangGraph graph: plan (LLM) → guardrail (code) → retry or finish.

    START → plan → guard ─ok──────────────► END
                     └─refused, retries left → plan (with the reasons)

Nothing is written unless asked: `run_week_planner(..., propose=True)` turns an accepted plan
into proposals (create_session, cancel_session) that the athlete approves or rejects; code
applies them (lifter.domain). A plan still refused after the retries proposes nothing.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict

import psycopg
from langgraph.graph import END, START, StateGraph

from lifter import domain
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
    feedback: list[str]
    attempts: int


def build_graph(planner: Planner):
    def plan_node(state: State) -> State:
        attempts = state.get("attempts", 0) + 1
        try:
            plan = planner(state["context"], state.get("feedback", []))
        except PlannerOutputError as exc:
            refused = Verdict([Violation("schema", str(exc))], [], [])
            return {"plan": None, "verdict": refused, "attempts": attempts}
        return {"plan": plan, "verdict": None, "attempts": attempts}

    def guard_node(state: State) -> State:
        if state["plan"] is None:  # the model's output did not even parse
            verdict = state["verdict"]
        else:
            verdict = check(state["plan"], state["context"])
        return {"verdict": verdict, "feedback": [str(v) for v in verdict.violations]}

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
    proposal_ids: list[int] = field(default_factory=list)

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
) -> WeekPlannerResult:
    ctx = build_context(conn, week_number=week_number, today=today, mode=mode)
    state = build_graph(planner).invoke({"context": ctx, "attempts": 0, "feedback": []})
    result = WeekPlannerResult(
        context=ctx, plan=state.get("plan"), verdict=state["verdict"], attempts=state["attempts"]
    )
    if propose and result.accepted:
        result.proposal_ids = propose_plan(conn, result.plan, ctx)
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
