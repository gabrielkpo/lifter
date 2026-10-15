"""Bench scenarios: a situation of the synthetic athlete and the outcome expected from a good
planner, written before any run (bench/scenarios/*.yaml).

A scenario starts from the base program (lifter.bench.athlete), then its setup logs weeks as
planned, skips sessions, changes logged lines, adds feedback, overrides the target week's phase,
and generates 35 days of synthetic Garmin data with a recovery profile. Setup writes straight
into the bench's own throwaway database; agents never do.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import psycopg
import yaml
from psycopg.types.json import Jsonb
from pydantic import Field, field_validator

from lifter.bench.athlete import INTENTS, base_program, week_start
from lifter.domain import FeedbackIn, StrictModel, add_feedback
from lifter.program import Phase, load_program
from lifter.synthetic import load_days

Recovery = Literal["normal", "low", "critical", "short_sleep", "overload"]
GARMIN_DAYS = 35
TRAINING_WEEKDAYS = {0, 1, 3, 4, 5}  # Monday, Tuesday, Thursday, Friday, Saturday


class SessionRef(StrictModel):
    week: int
    title: str


class LogChange(SessionRef):
    exercise: str
    load_kg: float | None = None
    quantity: float | None = None
    rir: int | None = None


class FeedbackRef(SessionRef):
    pain: int | None = Field(default=None, ge=0, le=10)
    pain_location: str | None = None
    rpe: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None


class Setup(StrictModel):
    complete: list[int] | None = None  # weeks logged as planned (default: those before target)
    skip: list[SessionRef] = []
    log: list[LogChange] = []
    feedback: list[FeedbackRef] = []
    phase: Phase | None = None
    keep_drafts: bool = False
    recovery: Recovery = "normal"


class Expectation(StrictModel):
    check: str
    params: dict[str, Any] = {}

    @field_validator("check")
    @classmethod
    def _known(cls, check: str) -> str:
        from lifter.bench.expect import CHECKS

        if check not in CHECKS:
            raise ValueError(f"unknown check '{check}' (known: {', '.join(sorted(CHECKS))})")
        return check


class Scenario(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    category: str
    description: str
    target_week: int = Field(ge=1, le=12)
    setup: Setup = Setup()
    expect: list[Expectation]
    review: str = Field(description="What a good plan does, for the hand grading (1 to 5)")

    @property
    def today(self) -> date:
        """The Sunday before the target week: the athlete programs it on the weekend."""
        return week_start(self.target_week) - timedelta(days=1)


def read_scenarios(directory: Path) -> list[Scenario]:
    scenarios = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as f:
            scenario = Scenario.model_validate(yaml.safe_load(f))
        if scenario.name != path.stem:
            raise ValueError(f"{path.name}: the name must be the file name ({scenario.name})")
        scenarios.append(scenario)
    return scenarios


def _session_id(conn: psycopg.Connection, ref: SessionRef) -> int:
    row = conn.execute(
        "select p.id from planned_session p join training_week w on w.id = p.week_id"
        " where w.number = %s and p.title = %s",
        (ref.week, ref.title),
    ).fetchone()
    if row is None:
        raise ValueError(f"no session '{ref.title}' in week {ref.week}")
    return row[0]


def _complete(conn: psycopg.Connection, week: int) -> None:
    """Every planned line logged as done, every metcon target reached."""
    conn.execute(
        "insert into session_exercise (part_id, origin, position, exercise_id, sets, quantity,"
        " unit, load_kg, load_kg_max, rir, rest_seconds, notes)"
        " select e.part_id, 'done', e.position, e.exercise_id, e.sets, e.quantity, e.unit,"
        " e.load_kg, e.load_kg_max, e.rir, e.rest_seconds, e.notes"
        " from session_exercise e"
        " join session_part sp on sp.id = e.part_id"
        " join planned_session p on p.id = sp.session_id"
        " join training_week w on w.id = p.week_id"
        " where w.number = %s and e.origin = 'planned'",
        (week,),
    )
    conn.execute(
        "update session_part sp set result_seconds = sp.target_seconds,"
        " result_rounds = sp.target_rounds"
        " from planned_session p join training_week w on w.id = p.week_id"
        " where sp.session_id = p.id and w.number = %s and sp.kind = 'metcon'",
        (week,),
    )


def _skip(conn: psycopg.Connection, session_id: int) -> None:
    conn.execute(
        "delete from session_exercise where origin = 'done'"
        " and part_id in (select id from session_part where session_id = %s)",
        (session_id,),
    )
    conn.execute(
        "update session_part set result_seconds = null, result_rounds = null where session_id = %s",
        (session_id,),
    )


def _log(conn: psycopg.Connection, change: LogChange) -> None:
    session_id = _session_id(conn, change)
    updated = conn.execute(
        "update session_exercise e set"
        " load_kg = coalesce(%s, e.load_kg), load_kg_max = null,"
        " quantity = coalesce(%s, e.quantity), rir = coalesce(%s, e.rir)"
        " from session_part sp, exercise x"
        " where e.part_id = sp.id and sp.session_id = %s and e.origin = 'done'"
        " and x.id = e.exercise_id and x.name = %s returning e.id",
        (change.load_kg, change.quantity, change.rir, session_id, change.exercise),
    ).fetchall()
    if not updated:
        raise ValueError(f"no done '{change.exercise}' in '{change.title}' week {change.week}")


def garmin_days(today: date, recovery: Recovery) -> list[dict]:
    """35 days of synthetic Garmin data ending today, shaped by the recovery profile."""
    days = []
    first = today - timedelta(days=GARMIN_DAYS - 1)
    for i in range(GARMIN_DAYS):
        day = first + timedelta(days=i)
        from_end = (today - day).days
        d = {"hrv": 60 + (i % 3) - 1, "rhr": 52, "sleep_hours": 7.5}
        if day.weekday() in TRAINING_WEEKDAYS:
            d["load"] = 300
            d["activity_type"] = "cycling"  # counts in the load, never completes a session
        if recovery == "low" and from_end < 2:
            d.update(hrv=48, rhr=58, sleep_hours=5.5)
        elif recovery == "critical" and from_end < 1:
            d.update(hrv=38, rhr=63, sleep_hours=5.0)
        elif recovery == "short_sleep" and from_end < 3:
            d.update(sleep_hours=5.0)
        elif recovery == "overload" and from_end < 7 and "load" in d:
            d["load"] = 700
        days.append(d)
    return days


def apply_setup(conn: psycopg.Connection, scenario: Scenario) -> None:
    """The base program and the scenario's situation, in an empty database, all or nothing."""
    setup = scenario.setup
    target = scenario.target_week
    with conn.transaction():
        load_program(conn, base_program())
        if not setup.keep_drafts:
            conn.execute(
                "delete from planned_session where week_id ="
                " (select id from training_week where number = %s)",
                (target,),
            )
        for week in setup.complete if setup.complete is not None else range(1, target):
            _complete(conn, week)
        for ref in setup.skip:
            _skip(conn, _session_id(conn, ref))
        for change in setup.log:
            _log(conn, change)
        for fb in setup.feedback:
            session_id = _session_id(conn, fb)
            day = conn.execute(
                "select day from planned_session where id = %s", (session_id,)
            ).fetchone()[0]
            add_feedback(
                conn,
                FeedbackIn(
                    day=day,
                    planned_session_id=session_id,
                    pain=fb.pain,
                    pain_location=fb.pain_location,
                    rpe=fb.rpe,
                    notes=fb.notes,
                ),
            )
        if setup.phase is not None:
            conn.execute(
                "update training_week set phase = %s, intent = %s where number = %s",
                (setup.phase, Jsonb({"notes": INTENTS[setup.phase]}), target),
            )
        load_days(
            conn,
            scenario.today - timedelta(days=GARMIN_DAYS - 1),
            garmin_days(scenario.today, setup.recovery),
        )
