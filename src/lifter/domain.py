"""The athlete's domain, for CrossFit: sessions in parts, exercises, goals, feedback, proposals.

A session is an ordered list of parts (warm-up, weightlifting / gymnastics, strength, metcon,
or a cardio / mobility block). Each part holds exercise lines, as prescribed (`planned`) and
as done (`done`); a metcon part has a format and a target, never a time cap.

Two ways to change the domain:
- the athlete acts directly (CLI and program file today, the app later): `create_session`,
  `move_session`, ...
- an agent proposes (`propose`); nothing changes until the athlete approves the proposal
  (`decide`) and code applies it (`apply`). Agents never call the direct functions.
- the coach in conversation applies what the athlete asks through `lifter.operations` (ADR
  0002), which reuses these models and functions and adds the quote check, versions, rules
  and the trace that `undo` reverts.
"""

from datetime import date
from typing import Annotated, Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

PartKind = Literal[
    "warmup", "weightlifting", "gymnastics", "strength", "metcon", "cardio", "mobility"
]
MetconFormat = Literal["for_time", "amrap", "emom", "every_n", "rounds", "intervals", "other"]
Unit = Literal["reps", "cal", "m", "s", "min"]
PositiveInt = Annotated[int, Field(gt=0)]
PositiveNumber = Annotated[float, Field(gt=0)]


class StrictModel(BaseModel):
    """Unknown fields are refused, text is stripped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExerciseIn(StrictModel):
    name: str = Field(min_length=1)
    category: Literal[
        "weightlifting", "gymnastics", "strength", "monostructural", "mobility", "other"
    ]
    pattern: Literal[
        "olympic",
        "push",
        "pull",
        "legs",
        "hinge",
        "core",
        "carry",
        "engine",
        "full_body",
        "mobility",
        "other",
    ] = "other"
    equipment: str | None = None
    flags: list[str] = []
    notes: str | None = None


class LineIn(StrictModel):
    """One exercise line: `sets` x `quantity` `unit` at `load_kg` (to `load_kg_max`), RIR."""

    exercise: str = Field(min_length=1)
    sets: PositiveInt | None = None
    quantity: PositiveNumber | None = None
    unit: Unit = "reps"
    load_kg: Annotated[float, Field(ge=0)] | None = None
    load_kg_max: Annotated[float, Field(ge=0)] | None = None
    rir: Annotated[int, Field(ge=0, le=10)] | None = None
    rest_seconds: Annotated[int, Field(ge=0)] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _load_range(self):
        top = self.load_kg_max
        if top is not None and (self.load_kg is None or top < self.load_kg):
            raise ValueError("load_kg_max needs a load_kg and cannot be below it")
        return self


class PartIn(StrictModel):
    kind: PartKind
    title: str | None = None
    notes: str | None = None
    format: MetconFormat | None = None
    duration_minutes: PositiveNumber | None = None
    rounds: PositiveInt | None = None
    interval_seconds: PositiveInt | None = None
    target_seconds: PositiveInt | None = None
    target_rounds: PositiveNumber | None = None
    result_seconds: PositiveInt | None = None
    result_rounds: Annotated[float, Field(ge=0)] | None = None
    result_notes: str | None = None
    planned: list[LineIn] = []
    done: list[LineIn] = []


class SessionIn(StrictModel):
    day: date
    title: str = Field(min_length=1)
    kind: Literal["training", "cardio", "mobility", "rest"] = "training"
    week_id: int | None = None
    notes: str | None = None
    deviation: str | None = None
    status: Literal["planned", "cancelled"] = "planned"
    moved_from: date | None = None
    parts: list[PartIn] = []


class MoveSession(StrictModel):
    session_id: int
    new_day: date


class CancelSession(StrictModel):
    session_id: int


class MilestoneIn(StrictModel):
    day: date
    label: str | None = None
    value: float | None = None
    value_text: str | None = None

    @model_validator(mode="after")
    def _has_value(self):
        if self.value is None and self.value_text is None:
            raise ValueError("a milestone needs a value or a value_text")
        return self


class GoalIn(StrictModel):
    title: str = Field(min_length=1)
    kind: Literal["strength", "skill", "benchmark", "other"] = "strength"
    exercise: str | None = None
    cycle_id: int | None = None
    unit: str | None = None
    baseline_value: float | None = None
    baseline_text: str | None = None
    baseline_date: date | None = None
    target_value: float | None = None
    target_text: str | None = None
    target_date: date | None = None
    notes: str | None = None
    milestones: list[MilestoneIn] = []

    @model_validator(mode="after")
    def _has_target(self):
        if self.target_value is None and self.target_text is None:
            raise ValueError("a goal needs a target_value or a target_text")
        return self


class RuleIn(StrictModel):
    code: str | None = None
    text: str = Field(min_length=1)
    params: dict[str, Any] = {}


class FeedbackIn(StrictModel):
    day: date
    kind: Literal["session", "morning"] = "session"
    planned_session_id: int | None = None
    activity_id: int | None = None
    rpe: Annotated[int, Field(ge=1, le=10)] | None = None
    fatigue: Annotated[int, Field(ge=1, le=5)] | None = None
    pain: Annotated[int, Field(ge=0, le=10)] | None = None
    pain_location: str | None = None
    notes: str | None = None


PROPOSAL_PAYLOADS: dict[str, type[StrictModel]] = {
    "create_session": SessionIn,
    "move_session": MoveSession,
    "cancel_session": CancelSession,
    "create_goal": GoalIn,
}


class DomainError(ValueError):
    """The requested change is not possible (unknown id or exercise, wrong state, bad dates)."""


class _NotApproved(Exception):
    """Internal: the proposal is not in the approved state, nothing to record."""


def insert_row(conn: psycopg.Connection, table: str, values: dict[str, Any]) -> int:
    """Insert a row; table and column names come from this module, never from input."""
    columns = ", ".join(values)
    placeholders = ", ".join(["%s"] * len(values))
    params = [Jsonb(v) if isinstance(v, dict) else v for v in values.values()]
    row = conn.execute(
        f"insert into {table} ({columns}) values ({placeholders}) returning id", params
    ).fetchone()
    return row[0]


def exercise_ids(conn: psycopg.Connection, names: set[str]) -> dict[str, int]:
    """Ids of the named exercises; every name must be in the exercise bank."""
    rows = conn.execute(
        "select name, id from exercise where name = any(%s)", (sorted(names),)
    ).fetchall()
    found = dict(rows)
    missing = sorted(names - found.keys())
    if missing:
        raise DomainError(f"unknown exercises (add them to the bank first): {', '.join(missing)}")
    return found


# Direct actions (the athlete)


def upsert_exercise(conn: psycopg.Connection, exercise: ExerciseIn) -> int:
    row = conn.execute(
        """
        insert into exercise (name, category, pattern, equipment, flags, notes)
        values (%(name)s, %(category)s, %(pattern)s, %(equipment)s, %(flags)s, %(notes)s)
        on conflict (name) do update set
            category = excluded.category, pattern = excluded.pattern,
            equipment = excluded.equipment, flags = excluded.flags, notes = excluded.notes
        returning id
        """,
        exercise.model_dump(),
    ).fetchone()
    return row[0]


Source = Literal["program", "athlete", "agent"]


def create_session(conn: psycopg.Connection, session: SessionIn, source: Source = "athlete") -> int:
    """Create a session with its parts and exercise lines, all or nothing."""
    names = {line.exercise for part in session.parts for line in part.planned + part.done}
    with conn.transaction():
        ids = exercise_ids(conn, names) if names else {}
        session_id = insert_row(
            conn, "planned_session", session.model_dump(exclude={"parts"}) | {"source": source}
        )
        for position, part in enumerate(session.parts, start=1):
            part_id = insert_row(
                conn,
                "session_part",
                {"session_id": session_id, "position": position}
                | part.model_dump(exclude={"planned", "done"}),
            )
            for origin, lines in (("planned", part.planned), ("done", part.done)):
                for line_position, line in enumerate(lines, start=1):
                    values = line.model_dump(exclude={"exercise"})
                    insert_row(
                        conn,
                        "session_exercise",
                        {
                            "part_id": part_id,
                            "origin": origin,
                            "position": line_position,
                            "exercise_id": ids[line.exercise],
                        }
                        | values,
                    )
    return session_id


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


def create_goal(conn: psycopg.Connection, goal: GoalIn, source: Source = "athlete") -> int:
    with conn.transaction():
        values = goal.model_dump(exclude={"exercise", "milestones"}) | {"source": source}
        if goal.exercise is not None:
            values["exercise_id"] = exercise_ids(conn, {goal.exercise})[goal.exercise]
        goal_id = insert_row(conn, "goal", values)
        for milestone in goal.milestones:
            insert_row(conn, "goal_milestone", {"goal_id": goal_id} | milestone.model_dump())
    return goal_id


def add_rule(conn: psycopg.Connection, rule: RuleIn) -> int:
    return insert_row(conn, "athlete_rule", rule.model_dump())


def add_feedback(conn: psycopg.Connection, feedback: FeedbackIn) -> int:
    return insert_row(conn, "feedback", feedback.model_dump())


# Proposals (agents)

_APPLY = {
    "create_session": lambda conn, p: {"session_id": create_session(conn, p, "agent")},
    "move_session": lambda conn, p: move_session(conn, p) or {},
    "cancel_session": lambda conn, p: cancel_session(conn, p) or {},
    "create_goal": lambda conn, p: {"goal_id": create_goal(conn, p, "agent")},
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
            "update proposal set status = 'failed', result = %s"
            " where id = %s and status = 'approved'",
            (Jsonb({"error": str(exc)}), proposal_id),
        )
        raise DomainError(f"proposal {proposal_id} failed: {exc}") from exc
    return result
