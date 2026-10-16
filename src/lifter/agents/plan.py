"""What the week planner returns: a typed week of sessions, never free text alone.

The planner's output is validated against these models (unknown fields refused, a metcon has a
target and no time cap) before the guardrail even looks at it. Results and done lines cannot be
expressed: an agent plans, only the athlete logs.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from lifter.agents.context import LineInfo, PartInfo
from lifter.domain import LineIn, MetconFormat, PartIn, PartKind, SessionIn, StrictModel

PositiveInt = Annotated[int, Field(gt=0)]
PositiveNumber = Annotated[float, Field(gt=0)]


class PlanLine(LineIn):
    """A prescribed line: `sets` x `quantity` `unit` at `load_kg` (to `load_kg_max`), RIR."""


class PlanPart(StrictModel):
    kind: PartKind
    title: str | None = None
    notes: str | None = None
    format: MetconFormat | None = None
    duration_minutes: PositiveNumber | None = None
    rounds: PositiveInt | None = None
    interval_seconds: PositiveInt | None = None
    target_seconds: PositiveInt | None = None
    target_rounds: PositiveNumber | None = None
    lines: list[PlanLine] = []


def plan_line(line: LineInfo) -> PlanLine:
    """A stored line as a prescribed one."""
    return PlanLine(
        exercise=line.exercise,
        sets=line.sets,
        quantity=line.quantity,
        unit=line.unit,
        load_kg=line.load_kg,
        load_kg_max=line.load_kg_max,
        rir=line.rir,
    )


def plan_part(part: PartInfo, lines: list[LineInfo]) -> PlanPart:
    """A stored part, with the given lines (planned or done), as a prescribed one."""
    return PlanPart(
        kind=part.kind,
        format=part.format,
        duration_minutes=part.duration_minutes,
        rounds=part.rounds,
        interval_seconds=part.interval_seconds,
        target_seconds=part.target_seconds,
        target_rounds=part.target_rounds,
        lines=[plan_line(line) for line in lines],
    )


class PlanSession(StrictModel):
    day: date
    title: str = Field(min_length=1)
    kind: Literal["training", "cardio", "mobility", "rest"] = "training"
    rationale: str = Field(min_length=1, description="Why this session, citing context numbers")
    parts: list[PlanPart] = []

    def to_session_in(self, week_id: int | None) -> SessionIn:
        parts = [
            PartIn(**part.model_dump(exclude={"lines"}), planned=part.lines) for part in self.parts
        ]
        return SessionIn(
            day=self.day, title=self.title, kind=self.kind, week_id=week_id, parts=parts
        )


class WeekPlan(StrictModel):
    summary: str = Field(
        min_length=1, description="The week in a few sentences, citing context numbers"
    )
    sessions: list[PlanSession]
    cancel_session_ids: list[int] = Field(
        default=[],
        description="Sessions already planned in the target week that this plan replaces",
    )
