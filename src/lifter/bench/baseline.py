"""A planner without a model: it copies the previous week, shifted by seven days.

It is the bench's floor. An agent that does not beat "same as last week" on the scenarios is
not worth its tokens. It never reads recovery, feedback or the week's phase, on purpose.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from lifter.agents.context import LineInfo, PlanningContext
from lifter.agents.plan import PlanLine, PlanPart, PlanSession, WeekPlan
from lifter.agents.planner import Usage


def _line(line: LineInfo) -> PlanLine:
    return PlanLine(
        exercise=line.exercise,
        sets=line.sets,
        quantity=line.quantity,
        unit=line.unit,
        load_kg=line.load_kg,
        load_kg_max=line.load_kg_max,
        rir=line.rir,
    )


@dataclass
class CopyLastWeek:
    usage: Usage = field(default_factory=Usage)

    def __call__(self, ctx: PlanningContext, feedback: list[str]) -> WeekPlan:
        self.usage.calls += 1
        target = ctx.target_week
        review = ctx.previous_week
        if review is None:
            return WeekPlan(summary=f"Week {target.number}: nothing to copy.", sessions=[])
        shift = timedelta(weeks=target.number - review.number)
        sessions = [
            PlanSession(
                day=s.day + shift,
                title=s.title,
                kind=s.kind,
                rationale=f"Same as week {review.number}.",
                parts=[
                    PlanPart(
                        kind=part.kind,
                        format=part.format,
                        duration_minutes=part.duration_minutes,
                        rounds=part.rounds,
                        interval_seconds=part.interval_seconds,
                        target_seconds=part.target_seconds,
                        target_rounds=part.target_rounds,
                        lines=[_line(line) for line in (part.planned or part.done)],
                    )
                    for part in s.parts
                ],
            )
            for s in review.session_details
            if s.kind != "rest"
        ]
        return WeekPlan(
            summary=f"Week {target.number} repeats week {review.number}.", sessions=sessions
        )
