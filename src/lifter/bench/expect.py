"""Expected outcomes of a scenario, checked by code on the planner's final plan.

Each check reads the plan, the context it was built from, and the sessions of the week the plan
keeps. They measure plan quality beyond the guardrail: the guardrail refuses what breaks a
rule; these say whether the plan does what a good coach would in that situation.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lifter.agents.context import PlanningContext
from lifter.agents.guardrail import kept_sessions, top_load
from lifter.agents.plan import PlanLine, PlanPart, WeekPlan

STRENGTH_PARTS = ("strength", "weightlifting")


@dataclass(frozen=True)
class Outcome:
    check: str
    passed: bool
    detail: str


def _lines(plan: WeekPlan, kinds: tuple[str, ...] | None = None):
    for s in plan.sessions:
        for part in s.parts:
            if kinds is None or part.kind in kinds:
                for line in part.lines:
                    yield s, part, line


def _sets(line: PlanLine) -> int:
    return line.sets or 1


def _volume(plan: WeekPlan) -> int:
    return sum(_sets(line) for _, _, line in _lines(plan, STRENGTH_PARTS))


def _previous_volume(ctx: PlanningContext) -> int:
    review = ctx.previous_week
    if review is None:
        return 0
    return sum(
        (line.sets or 1)
        for s in review.session_details
        for part in s.parts
        if part.kind in STRENGTH_PARTS
        for line in part.planned
    )


def _is_metcon(part: PlanPart) -> bool:
    return part.kind == "metcon"


def accepted(plan, ctx, p, result) -> Outcome:
    return Outcome("accepted", result.accepted, f"{result.attempts} attempt(s)")


def sessions(plan, ctx, p, result) -> Outcome:
    count = sum(1 for s in plan.sessions if s.kind != "rest") + sum(
        1 for s in kept_sessions(plan, ctx) if s.kind != "rest"
    )
    ok = p.get("min", 0) <= count <= p.get("max", 99)
    return Outcome("sessions", ok, f"{count} sessions (expected {p.get('min')}..{p.get('max')})")


def has_pattern(plan, ctx, p, result) -> Outcome:
    patterns = {e.name: e.pattern for e in ctx.exercises}
    kinds = tuple(p.get("parts", ["strength"]))
    found = any(patterns.get(line.exercise) == p["pattern"] for _, _, line in _lines(plan, kinds))
    found = found or any(
        patterns.get(line.exercise) == p["pattern"]
        for s in kept_sessions(plan, ctx)
        for part in s.parts
        if part.kind in kinds
        for line in part.planned
    )
    return Outcome(f"has_pattern {p['pattern']}", found, "found" if found else "missing")


def excludes_exercises(plan, ctx, p, result) -> Outcome:
    hits = sorted({line.exercise for _, _, line in _lines(plan) if line.exercise in p["names"]})
    return Outcome("excludes_exercises", not hits, ", ".join(hits) or "none")


def excludes_flags(plan, ctx, p, result) -> Outcome:
    flags = {e.name: set(e.flags) for e in ctx.exercises}
    hits = sorted(
        {
            line.exercise
            for _, _, line in _lines(plan)
            if flags.get(line.exercise, set()) & set(p["flags"])
        }
    )
    return Outcome("excludes_flags", not hits, ", ".join(hits) or "none")


def volume_vs_previous(plan, ctx, p, result) -> Outcome:
    previous = _previous_volume(ctx)
    if previous == 0:
        return Outcome("volume_vs_previous", False, "no planned volume in the previous week")
    ratio = _volume(plan) / previous
    ok = p.get("min", 0) <= ratio <= p.get("max", 99)
    return Outcome(
        "volume_vs_previous",
        ok,
        f"{_volume(plan)} sets vs {previous} ({ratio:.2f},"
        f" expected {p.get('min')}..{p.get('max')})",
    )


def rir_at_least(plan, ctx, p, result) -> Outcome:
    low = sorted(
        {
            f"{line.exercise} RIR {line.rir}"
            for _, _, line in _lines(plan, STRENGTH_PARTS)
            if line.rir is not None and line.rir < p["value"]
        }
    )
    return Outcome(f"rir_at_least {p['value']}", not low, ", ".join(low) or "ok")


def no_metcon(plan, ctx, p, result) -> Outcome:
    days = sorted({str(s.day) for s in plan.sessions for part in s.parts if _is_metcon(part)})
    return Outcome("no_metcon", not days, ", ".join(days) or "none")


def max_metcons(plan, ctx, p, result) -> Outcome:
    count = sum(1 for s in plan.sessions for part in s.parts if _is_metcon(part))
    return Outcome("max_metcons", count <= p["value"], f"{count} metcon(s)")


def light_first_days(plan, ctx, p, result) -> Outcome:
    """The first `days` days of the week: no metcon, nothing under RIR 3."""
    start = ctx.target_week.start_date
    hard = []
    for s in plan.sessions:
        if (s.day - start).days >= p["days"]:
            continue
        if any(_is_metcon(part) for part in s.parts) or any(
            line.rir is not None and line.rir < 3 for part in s.parts for line in part.lines
        ):
            hard.append(f"{s.day} {s.title}")
    return Outcome(f"light_first_days {p['days']}", not hard, ", ".join(hard) or "ok")


def _loads(plan: WeekPlan, exercise: str) -> list[float]:
    return [
        top
        for _, part, line in _lines(plan)
        if line.exercise == exercise and not _is_metcon(part)
        if (top := top_load(line)) is not None
    ]


def load_at_most(plan, ctx, p, result) -> Outcome:
    loads = _loads(plan, p["exercise"])
    ok = all(load <= p["kg"] for load in loads)
    return Outcome(f"load_at_most {p['exercise']} {p['kg']}", ok, f"loads {loads or 'none'}")


def load_at_least(plan, ctx, p, result) -> Outcome:
    loads = _loads(plan, p["exercise"])
    ok = bool(loads) and max(loads) >= p["kg"]
    return Outcome(f"load_at_least {p['exercise']} {p['kg']}", ok, f"loads {loads or 'none'}")


def includes_exercise(plan, ctx, p, result) -> Outcome:
    found = any(line.exercise == p["name"] for _, _, line in _lines(plan))
    return Outcome(f"includes {p['name']}", found, "found" if found else "missing")


def includes_single(plan, ctx, p, result) -> Outcome:
    found = any(
        line.exercise == p["exercise"] and line.quantity == 1 and line.unit == "reps"
        for _, _, line in _lines(plan, STRENGTH_PARTS)
    )
    return Outcome(f"includes_single {p['exercise']}", found, "found" if found else "missing")


def includes_metcon(plan, ctx, p, result) -> Outcome:
    for s in plan.sessions:
        for part in s.parts:
            if (
                _is_metcon(part)
                and part.format == p["format"]
                and ("duration_minutes" not in p or part.duration_minutes == p["duration_minutes"])
            ):
                return Outcome(f"includes_metcon {p['format']}", True, str(s.day))
    return Outcome(f"includes_metcon {p['format']}", False, "missing")


def strength_reps_at_most(plan, ctx, p, result) -> Outcome:
    names = set(p.get("exercises", []))
    high = sorted(
        {
            f"{line.exercise} x{line.quantity:g}"
            for _, part, line in _lines(plan, ("strength",))
            if line.unit == "reps"
            and line.quantity is not None
            and line.quantity > p["value"]
            and (not names or line.exercise in names)
        }
    )
    return Outcome(f"strength_reps_at_most {p['value']}", not high, ", ".join(high) or "ok")


def prescribed_rir(plan, ctx, p, result) -> Outcome:
    """Every strength or weightlifting line in reps carries a target RIR."""
    from lifter.agents.guardrail import needs_rir

    missing = [
        f"{s.day} {line.exercise}"
        for s in plan.sessions
        for part in s.parts
        for line in part.lines
        if needs_rir(part.kind, line) and line.rir is None
    ]
    return Outcome("prescribed_rir", not missing, ", ".join(missing) or "ok")


def no_violation(plan, ctx, p, result) -> Outcome:
    """The final plan breaks no rule of that check (the guardrail run again, on the plan only)."""
    from lifter.agents.guardrail import check

    found = [v.message for v in check(plan, ctx).violations if v.check == p["check"]]
    return Outcome(f"no_violation {p['check']}", not found, "; ".join(found) or "ok")


CHECKS: dict[str, Callable[[WeekPlan, PlanningContext, dict[str, Any], Any], Outcome]] = {
    "accepted": accepted,
    "sessions": sessions,
    "has_pattern": has_pattern,
    "excludes_exercises": excludes_exercises,
    "excludes_flags": excludes_flags,
    "volume_vs_previous": volume_vs_previous,
    "rir_at_least": rir_at_least,
    "no_metcon": no_metcon,
    "max_metcons": max_metcons,
    "light_first_days": light_first_days,
    "load_at_most": load_at_most,
    "load_at_least": load_at_least,
    "includes_exercise": includes_exercise,
    "includes_single": includes_single,
    "includes_metcon": includes_metcon,
    "strength_reps_at_most": strength_reps_at_most,
    "prescribed_rir": prescribed_rir,
    "no_violation": no_violation,
}


def evaluate(expectations, result) -> list[Outcome]:
    """Every expectation on the final plan; without a plan, every one fails."""
    if result.plan is None:
        return [Outcome(e.check, False, "no plan") for e in expectations]
    return [CHECKS[e.check](result.plan, result.context, e.params, result) for e in expectations]
