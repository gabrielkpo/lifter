"""The guardrail: deterministic checks of a planned week, in code, never by an LLM.

A plan that breaks a check is sent back to the planner with the reasons; a plan still broken
after the retries is refused, nothing is proposed. Checks come from two sources:
- generic ones: days inside the week, exercises from the bank, every number cited in the text
  found in the context or in the plan (agents read numbers, they never compute them), and no
  intense work while a critical health alert is on;
- the athlete's rules that carry a `code` (athlete_rule). A rule without a code, or with a code
  this module does not know, is context for the planner only and is listed as not checked.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from lifter.agents.context import PlanningContext, Rule
from lifter.agents.plan import PlanLine, PlanPart, PlanSession, WeekPlan

LOWER_BODY = {"legs", "hinge"}
MAX_TERMS = re.compile(r"\b(1 ?RM|max(imum)?)\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Violation:
    check: str
    message: str
    day: str | None = None
    items: tuple[str, ...] = ()  # what is at fault, when countable (e.g. unsourced numbers)

    def __str__(self) -> str:
        where = f" ({self.day})" if self.day else ""
        return f"[{self.check}]{where} {self.message}"


@dataclass(frozen=True)
class Verdict:
    violations: list[Violation]
    warnings: list[str]
    unchecked_rules: list[str]

    @property
    def ok(self) -> bool:
        return not self.violations


def _lines(session: PlanSession) -> Iterator[tuple[PlanPart, PlanLine]]:
    for part in session.parts:
        for line in part.lines:
            yield part, line


def kept_sessions(plan: WeekPlan, ctx: PlanningContext):
    """Sessions already planned in the week that the plan keeps (does not cancel)."""
    return [
        s
        for s in ctx.sessions_already_planned
        if s.session_id not in plan.cancel_session_ids and s.status in ("planned", "missed")
    ]


def top_load(line: PlanLine) -> float | None:
    return line.load_kg_max if line.load_kg_max is not None else line.load_kg


def normalize(number: str) -> str:
    """'62,50' and '62.5' are the same number."""
    value = float(number.replace(",", "."))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def numbers_in(text: str) -> set[str]:
    return {normalize(n) for n in NUMBER.findall(text)}


# Generic checks


def check_days(plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    week = ctx.target_week
    for s in plan.sessions:
        if not week.start_date <= s.day <= week.end_date:
            yield Violation(
                "days",
                f"'{s.title}' is outside week {week.number} ({week.start_date}..{week.end_date})",
                str(s.day),
            )


def check_exercises(plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    bank = {e.name for e in ctx.exercises}
    for s in plan.sessions:
        for _, line in _lines(s):
            if line.exercise not in bank:
                yield Violation(
                    "exercise_bank", f"'{line.exercise}' is not in the exercise bank", str(s.day)
                )


# Free text of a plan: never a source for the numbers of its summary and rationales, or a number
# invented in a note could be cited in a rationale.
PLAN_FREE_TEXT = {
    "summary": True,
    "sessions": {
        "__all__": {
            "title": True,
            "rationale": True,
            "parts": {"__all__": {"title": True, "notes": True, "lines": {"__all__": {"notes"}}}},
        }
    },
}


def check_sources(plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    """Every number of the summary and rationales exists in the context or in the plan."""
    known = numbers_in(ctx.model_dump_json())
    # The plan's own values (loads, reps, targets, days), not its free text.
    known |= numbers_in(plan.model_dump_json(exclude=PLAN_FREE_TEXT))
    texts = [("summary", None, plan.summary)] + [
        ("rationale", str(s.day), s.rationale) for s in plan.sessions
    ]
    for label, day, text in texts:
        unsourced = sorted(numbers_in(text) - known, key=float)
        if unsourced:
            yield Violation(
                "sources",
                f"the {label} cites numbers found nowhere in the context: {', '.join(unsourced)}",
                day,
                tuple(unsourced),
            )


def check_critical_alerts(plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    """A critical health signal: no metcon and nothing close to failure until it clears."""
    critical = [a for a in ctx.alerts if a.severity == "critical"]
    if not critical:
        return
    names = ", ".join(sorted({a.alert for a in critical}))
    for kept in kept_sessions(plan, ctx):
        hard = any(p.kind == "metcon" for p in kept.parts) or any(
            line.rir is not None and line.rir < 3 for p in kept.parts for line in p.planned
        )
        if hard:
            yield Violation(
                "critical_alert",
                f"critical health alert ({names}): the planned session {kept.session_id}"
                f" '{kept.title}' is hard, cancel or replace it",
                str(kept.day),
            )
    for s in plan.sessions:
        hard = any(p.kind == "metcon" for p in s.parts) or any(
            line.rir is not None and line.rir < 3 for _, line in _lines(s)
        )
        if hard:
            yield Violation(
                "critical_alert",
                f"critical health alert ({names}): only easy work (no metcon, RIR 3 or more)",
                str(s.day),
            )


# Rules of the athlete (athlete_rule.code)


def rule_forbid_flag(rule: Rule, plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    flags = set(rule.params.get("flags", []))
    flagged = {e.name: set(e.flags) & flags for e in ctx.exercises}
    for s in plan.sessions:
        for _, line in _lines(s):
            if flagged.get(line.exercise):
                flags_hit = ", ".join(sorted(flagged[line.exercise]))
                yield Violation(
                    "forbid_flag", f"'{line.exercise}' is {flags_hit}: {rule.text}", str(s.day)
                )


def rule_no_failure_on_legs(
    rule: Rule, plan: WeekPlan, ctx: PlanningContext
) -> Iterator[Violation]:
    patterns = {e.name: e.pattern for e in ctx.exercises}
    for s in plan.sessions:
        for part, line in _lines(s):
            if part.kind == "metcon" or patterns.get(line.exercise) not in LOWER_BODY:
                continue
            if line.rir == 0 or (line.notes and MAX_TERMS.search(line.notes)):
                yield Violation(
                    "no_failure_on_legs", f"'{line.exercise}' to failure or max", str(s.day)
                )


def rule_weekly_pattern(rule: Rule, plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    pattern = rule.params.get("pattern")
    patterns = {e.name: e.pattern for e in ctx.exercises}
    trained = any(
        patterns.get(line.exercise) == pattern
        for s in plan.sessions
        for part, line in _lines(s)
        if part.kind == "strength"
    ) or any(
        patterns.get(line.exercise) == pattern
        for kept in kept_sessions(plan, ctx)
        for part in kept.parts
        if part.kind == "strength"
        for line in part.planned
    )
    if pattern and not trained:
        yield Violation("weekly_pattern", f"no strength work on '{pattern}': {rule.text}")


def rule_no_max_before_test(
    rule: Rule, plan: WeekPlan, ctx: PlanningContext
) -> Iterator[Violation]:
    if ctx.target_week.phase in ("peak", "test"):
        return
    for s in plan.sessions:
        for _, line in _lines(s):
            single_to_failure = line.quantity == 1 and line.unit == "reps" and line.rir == 0
            if single_to_failure or (line.notes and MAX_TERMS.search(line.notes)):
                yield Violation(
                    "no_max_before_test",
                    f"'{line.exercise}' is a max attempt in a {ctx.target_week.phase} week",
                    str(s.day),
                )


def rule_fresh_first(rule: Rule, plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    for s in plan.sessions:
        seen_metcon = False
        for part in s.parts:
            if part.kind == "metcon":
                seen_metcon = True
            elif seen_metcon and part.kind in ("weightlifting", "gymnastics"):
                yield Violation("fresh_first", f"{part.kind} comes after the metcon", str(s.day))


def rule_metcon_no_row(rule: Rule, plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    banned = set(rule.params.get("exercises", []))
    for s in plan.sessions:
        for part, line in _lines(s):
            if part.kind == "metcon" and line.exercise in banned:
                yield Violation(
                    "metcon_no_row", f"'{line.exercise}' in a metcon: {rule.text}", str(s.day)
                )


def rule_metcon_light_barbell(
    rule: Rule, plan: WeekPlan, ctx: PlanningContext
) -> Iterator[Violation]:
    max_kg = rule.params.get("max_kg")
    categories = {e.name: e.category for e in ctx.exercises}
    for s in plan.sessions:
        for part, line in _lines(s):
            top = top_load(line)
            if (
                part.kind == "metcon"
                and categories.get(line.exercise) == "weightlifting"
                and max_kg is not None
                and top is not None
                and top > max_kg
            ):
                yield Violation(
                    "metcon_light_barbell",
                    f"'{line.exercise}' at {top:g} kg in a metcon (at most {max_kg} kg)",
                    str(s.day),
                )


def rule_progression(rule: Rule, plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    """Loads go up by one step at most from the heaviest set logged at as many reps or more."""
    upper = rule.params.get("upper_kg", 2.5)
    lower = rule.params.get("lower_kg", 5)
    for s in plan.sessions:
        for part, line in _lines(s):
            top = top_load(line)
            if part.kind == "metcon" or top is None:
                continue
            refs = [r for r in ctx.recent_loads if r.exercise == line.exercise]
            if line.unit == "reps" and line.quantity is not None:
                # Sets logged at fewer reps say nothing about this load: a heavier one is expected.
                refs = [r for r in refs if r.reps is not None and r.reps >= line.quantity]
            # Otherwise (seconds, metres, no count) the reps cannot be compared: the heaviest set
            # logged at any reps is the reference, so a change of unit does not skip the rule.
            if not refs:
                continue
            ref = max(refs, key=lambda r: r.load_kg)
            step = lower if ref.pattern in LOWER_BODY else upper
            if top > ref.load_kg + step:
                yield Violation(
                    "progression",
                    f"'{line.exercise}' at {top:g} kg: heaviest logged {ref.load_kg:g} kg"
                    f" x {ref.reps:g} ({ref.day}), so at most {ref.load_kg + step:g} kg",
                    str(s.day),
                )


def _painful(rule: Rule, ctx: PlanningContext):
    """Feedback above the rule's pain threshold, most recent last."""
    pain_max = rule.params.get("pain_max", 3)
    return [f for f in ctx.feedback if f.pain is not None and f.pain > pain_max]


def rule_stop_rule(rule: Rule, plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    """Pain above the threshold after a session: two load steps back on what it loaded.

    Every loaded exercise of the painful session is capped at its load that day minus `steps`
    steps (2.5 kg upper body, 5 kg lower body by default), until a later session loading it is
    reported without such pain. Pain reported without a session, or on a session without
    loads, cannot be checked by code: it is a warning (see `check`).
    """
    steps = rule.params.get("steps", 2)
    upper = rule.params.get("upper_kg", 2.5)
    lower = rule.params.get("lower_kg", 5)
    patterns = {e.name: e.pattern for e in ctx.exercises}
    pain_max = rule.params.get("pain_max", 3)
    # The latest reported session that loaded each exercise decides: a later session reported
    # without pain lifts the cap (feedback is ordered by day).
    latest: dict[str, tuple] = {}  # exercise -> (feedback, heaviest load that day)
    for fb in ctx.feedback:
        if fb.pain is None:
            continue
        heaviest: dict[str, float] = {}
        for line in fb.lines:
            load = line.load_kg_max if line.load_kg_max is not None else line.load_kg
            heaviest[line.exercise] = max(load, heaviest.get(line.exercise, load))
        for exercise, load in heaviest.items():
            latest[exercise] = (fb, load)
    caps: dict[str, tuple[float, str]] = {}
    for exercise, (fb, top) in latest.items():
        if fb.pain <= pain_max:
            continue
        step = lower if patterns.get(exercise) in LOWER_BODY else upper
        where = f"pain {fb.pain}/10" + (f" ({fb.pain_location})" if fb.pain_location else "")
        reason = f"{where} after '{fb.session_title}' on {fb.day}, {top:g} kg that day"
        caps[exercise] = (top - steps * step, reason)
    for s in plan.sessions:
        for part, line in _lines(s):
            top = top_load(line)
            if part.kind == "metcon" or top is None or line.exercise not in caps:
                continue
            cap, reason = caps[line.exercise]
            if top > cap:
                yield Violation(
                    "stop_rule",
                    f"'{line.exercise}' at {top:g} kg: {reason}, so at most {max(cap, 0):g} kg"
                    f" ({rule.text})",
                    str(s.day),
                )


RULE_CHECKS: dict[str, Callable[[Rule, WeekPlan, PlanningContext], Iterator[Violation]]] = {
    "forbid_flag": rule_forbid_flag,
    "no_failure_on_legs": rule_no_failure_on_legs,
    "weekly_pattern": rule_weekly_pattern,
    "no_max_before_test": rule_no_max_before_test,
    "fresh_first": rule_fresh_first,
    "metcon_no_row": rule_metcon_no_row,
    "metcon_light_barbell": rule_metcon_light_barbell,
    "progression": rule_progression,
    "stop_rule": rule_stop_rule,
}


def check_cancellations(plan: WeekPlan, ctx: PlanningContext) -> Iterator[Violation]:
    """The plan may only cancel sessions of the target week that are still planned."""
    cancellable = {
        s.session_id for s in ctx.sessions_already_planned if s.status in ("planned", "missed")
    }
    for session_id in plan.cancel_session_ids:
        if session_id not in cancellable:
            yield Violation(
                "cancellations",
                f"session {session_id} is not a planned session of week {ctx.target_week.number}",
            )


GENERIC_CHECKS = (
    check_days,
    check_exercises,
    check_cancellations,
    check_sources,
    check_critical_alerts,
)


def check(plan: WeekPlan, ctx: PlanningContext) -> Verdict:
    violations = [v for checker in GENERIC_CHECKS for v in checker(plan, ctx)]
    unchecked = []
    for rule in ctx.rules:
        checker = RULE_CHECKS.get(rule.code or "")
        if checker is None:
            unchecked.append(rule.text)
            continue
        violations.extend(checker(rule, plan, ctx))
    warnings = []
    for rule in ctx.rules:
        if rule.code == "stop_rule":
            for fb in _painful(rule, ctx):
                if not fb.lines:
                    warnings.append(
                        f"pain {fb.pain}/10 reported on {fb.day}"
                        + (f" ({fb.pain_location})" if fb.pain_location else "")
                        + " without a loaded session to cap: not checked by code"
                    )
    latest = ctx.recovery[-1] if ctx.recovery else None
    if latest and latest.recovery_status == "low":
        warnings.append(
            f"recovery is low on {latest.day} (score {latest.recovery_score}):"
            " the first days of the week should stay light"
        )
    return Verdict(violations=violations, warnings=warnings, unchecked_rules=unchecked)
