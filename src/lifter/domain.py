"""The athlete's domain: sessions, goals, plans, feedback, and agent proposals.

Two ways to change it:
- the athlete acts directly (CLI today, the app later): `create_session`, `move_session`, ...
- an agent proposes (`propose`); nothing changes until the athlete approves the proposal
  (`decide`) and code applies it (`apply`). Agents never call the direct functions.

Garmin is not written here: pushing approved sessions to Garmin comes with step 5.
"""

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

Intensity = Literal["rest", "easy", "moderate", "hard", "race"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionIn(_Model):
    day: date
    sport: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    intensity: Intensity = "moderate"
    target_duration_minutes: Annotated[float, Field(gt=0)] | None = None
    target_load: Annotated[float, Field(ge=0)] | None = None
    structure: dict[str, Any] | None = None
    goal_id: int | None = None
    plan_id: int | None = None


class MoveSession(_Model):
    session_id: int
    new_day: date


class CancelSession(_Model):
    session_id: int


class GoalIn(_Model):
    title: str = Field(min_length=1)
    kind: Literal["event", "performance", "volume", "health", "other"] = "event"
    sport: str | None = None
    target_date: date | None = None
    target_value: float | None = None
    target_unit: str | None = None
    notes: str | None = None


class PlanIn(_Model):
    name: str = Field(min_length=1)
    goal_id: int | None = None
    phase: Literal["base", "build", "peak", "taper", "recovery", "transition"] = "base"
    start_date: date
    end_date: date
    notes: str | None = None


class FeedbackIn(_Model):
    day: date
    kind: Literal["session", "morning"] = "session"
    planned_session_id: int | None = None
    activity_id: int | None = None
    rpe: Annotated[int, Field(ge=1, le=10)] | None = None
    fatigue: Annotated[int, Field(ge=1, le=5)] | None = None
    pain: Annotated[int, Field(ge=0, le=10)] | None = None
    pain_location: str | None = None
    notes: str | None = None


PROPOSAL_PAYLOADS: dict[str, type[_Model]] = {
    "create_session": SessionIn,
    "move_session": MoveSession,
    "cancel_session": CancelSession,
    "create_goal": GoalIn,
    "create_plan": PlanIn,
}


class DomainError(ValueError):
    """The requested change is not possible (unknown id, wrong state, invalid dates)."""


class _NotApproved(Exception):
    """Internal: the proposal is not in the approved state, nothing to record."""


def _insert(conn: psycopg.Connection, table: str, values: dict[str, Any]) -> int:
    """Insert a row; table and column names come from this module's models, never from input."""
    columns = ", ".join(values)
    placeholders = ", ".join(["%s"] * len(values))
    params = [Jsonb(v) if isinstance(v, dict) else v for v in values.values()]
    row = conn.execute(
        f"insert into {table} ({columns}) values ({placeholders}) returning id", params
    ).fetchone()
    return row[0]


# Direct actions (the athlete)


def create_session(conn: psycopg.Connection, session: SessionIn) -> int:
    return _insert(conn, "planned_session", session.model_dump())


def move_session(conn: psycopg.Connection, move: MoveSession) -> None:
    row = conn.execute(
        """
        update planned_session
        set moved_from = coalesce(moved_from, day), day = %s, updated_at = now()
        where id = %s and status = 'planned'
        returning id
        """,
        (move.new_day, move.session_id),
    ).fetchone()
    if row is None:
        raise DomainError(f"session {move.session_id} does not exist or is cancelled")


def cancel_session(conn: psycopg.Connection, cancel: CancelSession) -> None:
    row = conn.execute(
        """
        update planned_session set status = 'cancelled', updated_at = now()
        where id = %s and status = 'planned' returning id
        """,
        (cancel.session_id,),
    ).fetchone()
    if row is None:
        raise DomainError(f"session {cancel.session_id} does not exist or is already cancelled")


def create_goal(conn: psycopg.Connection, goal: GoalIn) -> int:
    return _insert(conn, "goal", goal.model_dump())


def create_plan(conn: psycopg.Connection, plan: PlanIn) -> int:
    if plan.end_date < plan.start_date:
        raise DomainError("a plan cannot end before it starts")
    return _insert(conn, "training_plan", plan.model_dump())


def add_feedback(conn: psycopg.Connection, feedback: FeedbackIn) -> int:
    return _insert(conn, "feedback", feedback.model_dump())


# Proposals (agents)

_APPLY = {
    "create_session": lambda conn, p: {"session_id": create_session(conn, p)},
    "move_session": lambda conn, p: move_session(conn, p) or {},
    "cancel_session": lambda conn, p: cancel_session(conn, p) or {},
    "create_goal": lambda conn, p: {"goal_id": create_goal(conn, p)},
    "create_plan": lambda conn, p: {"plan_id": create_plan(conn, p)},
}


def propose(
    conn: psycopg.Connection, kind: str, payload: dict[str, Any], rationale: str, author: str
) -> int:
    """Record an agent's proposed change; the payload is validated now, applied only later."""
    if kind not in PROPOSAL_PAYLOADS:
        raise DomainError(f"unknown proposal kind: {kind}")
    if not rationale.strip():
        raise DomainError("a proposal needs a rationale")
    model = PROPOSAL_PAYLOADS[kind].model_validate(payload)
    row = conn.execute(
        "insert into proposal (kind, payload, rationale, author) values (%s, %s, %s, %s)"
        " returning id",
        (kind, Jsonb(model.model_dump(mode="json")), rationale, author),
    ).fetchone()
    return row[0]


def decide(conn: psycopg.Connection, proposal_id: int, approve: bool) -> None:
    """The athlete approves or rejects a pending proposal."""
    row = conn.execute(
        """
        update proposal set status = %s, decided_at = now()
        where id = %s and status = 'pending' returning id
        """,
        ("approved" if approve else "rejected", proposal_id),
    ).fetchone()
    if row is None:
        raise DomainError(f"proposal {proposal_id} is not pending")


def apply(conn: psycopg.Connection, proposal_id: int) -> dict[str, Any]:
    """Apply an approved proposal, all or nothing; a failure is recorded on the proposal."""
    try:
        with conn.transaction():
            # Locked for the whole transaction: a proposal is applied once, even if two
            # requests race.
            row = conn.execute(
                "select kind, payload from proposal where id = %s and status = 'approved'"
                " for update",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise _NotApproved(f"proposal {proposal_id} is not approved")
            kind, payload = row
            model = PROPOSAL_PAYLOADS[kind].model_validate(payload)
            result = _APPLY[kind](conn, model)
            conn.execute(
                "update proposal set status = 'applied', applied_at = now(), result = %s"
                " where id = %s",
                (Jsonb(result), proposal_id),
            )
    except _NotApproved as exc:
        raise DomainError(str(exc)) from None
    except (DomainError, psycopg.Error) as exc:
        conn.execute(
            "update proposal set status = 'failed', result = %s where id = %s",
            (Jsonb({"error": str(exc)}), proposal_id),
        )
        raise DomainError(f"proposal {proposal_id} failed: {exc}") from exc
    return result
