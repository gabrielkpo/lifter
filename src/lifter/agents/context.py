"""What the week planner reads, built by code from the analytics views (no LLM involved).

The planner programs one week of the cycle, like the athlete does every weekend: from the
review of the past week (what was done, at which loads and RIR, what was skipped) and from the
week's phase. Every number it may cite is in this context, so the guardrail can check them.

Privacy: Garmin activity names never enter the context (they can contain a place). In the
default `indicators` mode, free text written by the athlete (session notes, deviations, week
reviews, goal and feedback notes) stays out too; `full` adds it (setting LIFTER_LLM_CONTEXT).
Feedback scales (RPE, fatigue, pain) and the pain location are always in: the stop rule needs
them.
"""

from datetime import date, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

ContextMode = Literal["indicators", "full"]
RECOVERY_DAYS = 7
ALERT_DAYS = 3
RECENT_LOAD_DAYS = 28
FEEDBACK_DAYS = 14


class PlanningError(ValueError):
    """There is nothing to plan (no cycle, no such week)."""


class WeekInfo(BaseModel):
    week_id: int
    number: int
    start_date: date
    end_date: date
    phase: str
    title: str | None
    intent: dict[str, str]
    block: str | None
    block_intent: str | None
    block_strength_sessions_done: int | None
    block_target_strength_sessions: int | None


class LineInfo(BaseModel):
    exercise: str
    sets: int | None
    quantity: float | None
    unit: str
    load_kg: float | None
    load_kg_max: float | None
    rir: int | None


class PartInfo(BaseModel):
    kind: str
    format: str | None
    duration_minutes: float | None
    rounds: int | None
    interval_seconds: int | None
    target_seconds: int | None
    target_rounds: float | None
    result_seconds: int | None
    result_rounds: float | None
    planned: list[LineInfo]
    done: list[LineInfo]


class SessionInfo(BaseModel):
    session_id: int
    day: date
    title: str
    kind: str
    status: str
    garmin_minutes: float | None
    garmin_z4_z5_minutes: float | None
    parts: list[PartInfo]
    notes: str | None = None
    deviation: str | None = None


class WeekReview(BaseModel):
    number: int
    phase: str
    sessions: int
    done: int
    missed: int
    cancelled: int
    strength_sessions_done: int
    patterns_done: list[str]
    session_details: list[SessionInfo]
    review: str | None = None


class DayRecovery(BaseModel):
    day: date
    recovery_score: float | None
    recovery_status: str | None
    hrv_delta_pct: float | None
    rhr_delta_bpm: float | None
    sleep_hours: float | None
    acwr: float | None
    trend: str | None
    readiness_score: float | None
    body_battery_highest: float | None


class Alert(BaseModel):
    day: date
    alert: str
    severity: str
    value: float | None
    threshold: float | None


class Rule(BaseModel):
    code: str | None
    text: str
    params: dict[str, Any]


class Exercise(BaseModel):
    name: str
    category: str
    pattern: str
    flags: list[str]


class RecentLoad(BaseModel):
    """The heaviest logged load of an exercise for a repetition count, over the last 28 days.

    Kept per repetition count, not per last session, so a deload week does not become the
    reference the week after.
    """

    exercise: str
    pattern: str
    reps: float | None
    load_kg: float
    rir: int | None
    day: date


class Feedback(BaseModel):
    """What the athlete reported after a session or in the morning (scales: docs/domain.md).

    `lines` are the loaded lines of that session (done ones, else planned): the stop rule caps
    them when the pain is high."""

    day: date
    kind: str
    session_id: int | None
    session_title: str | None
    lines: list[LineInfo] = []
    rpe: int | None
    fatigue: int | None
    pain: int | None
    pain_location: str | None
    notes: str | None = None


class Goal(BaseModel):
    title: str
    exercise: str | None
    target: str
    target_date: date | None
    next_milestone: str | None
    notes: str | None = None


class PlanningContext(BaseModel):
    today: date
    mode: ContextMode
    target_week: WeekInfo
    previous_week: WeekReview | None
    sessions_already_planned: list[SessionInfo]
    recovery: list[DayRecovery]
    alerts: list[Alert]
    rules: list[Rule]
    exercises: list[Exercise]
    recent_loads: list[RecentLoad]
    feedback: list[Feedback]
    goals: list[Goal]


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def _rows(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Rows as dicts, without changing the caller's connection."""
    return conn.cursor(row_factory=dict_row).execute(sql, params).fetchall()


def _feedback_lines(conn: psycopg.Connection, session_id: int | None) -> list[LineInfo]:
    """The loaded strength-type lines of a session: done ones, else the planned ones."""
    if session_id is None:
        return []
    rows = _rows(
        conn,
        "select origin, exercise, sets, quantity, unit, load_kg, load_kg_max, rir"
        " from session_line where session_id = %s and load_kg is not null"
        " and part_kind in ('weightlifting', 'gymnastics', 'strength')"
        " order by origin, part_position, position",
        (session_id,),
    )
    done = [r for r in rows if r["origin"] == "done"]
    return [
        LineInfo(
            exercise=r["exercise"],
            sets=r["sets"],
            quantity=_num(r["quantity"]),
            unit=r["unit"],
            load_kg=_num(r["load_kg"]),
            load_kg_max=_num(r["load_kg_max"]),
            rir=r["rir"],
        )
        for r in (done or rows)
    ]


def _week(conn: psycopg.Connection, where: str, params: tuple) -> dict | None:
    rows = _rows(
        conn,
        "select w.id as week_id, w.number, w.start_date, w.phase, w.title, w.intent,"
        " w.review, w.cycle_id, b.kind as block, b.intent as block_intent,"
        " bp.strength_sessions_done, bp.target_strength_sessions"
        " from training_week w"
        " left join block b on b.id = w.block_id"
        " left join block_progress bp on bp.block_id = w.block_id"
        f" where {where} order by w.start_date limit 1",
        params,
    )
    return rows[0] if rows else None


def _sessions(conn: psycopg.Connection, week_id: int, mode: ContextMode) -> list[SessionInfo]:
    rows = _rows(
        conn,
        "select s.planned_session_id as id, s.day, s.title, s.kind, s.status,"
        " g.duration_minutes, g.z4_z5_minutes, p.notes, p.deviation"
        " from planned_session_status s"
        " join planned_session p on p.id = s.planned_session_id"
        " left join session_garmin g using (planned_session_id)"
        " where s.week_id = %s order by s.day, s.planned_session_id",
        (week_id,),
    )
    ids = [r["id"] for r in rows]
    parts = _rows(
        conn,
        "select session_id, position, kind, format, duration_minutes, rounds, interval_seconds,"
        " target_seconds, target_rounds, result_seconds, result_rounds from session_part"
        " where session_id = any(%s) order by session_id, position",
        (ids,),
    )
    lines = _rows(
        conn,
        "select session_id, part_position, origin, exercise, sets, quantity, unit, load_kg,"
        " load_kg_max, rir from session_line where session_id = any(%s)"
        " order by session_id, part_position, origin, position",
        (ids,),
    )

    def line_infos(session_id, position, origin):
        return [
            LineInfo(
                exercise=line["exercise"],
                sets=line["sets"],
                quantity=_num(line["quantity"]),
                unit=line["unit"],
                load_kg=_num(line["load_kg"]),
                load_kg_max=_num(line["load_kg_max"]),
                rir=line["rir"],
            )
            for line in lines
            if line["session_id"] == session_id
            and line["part_position"] == position
            and line["origin"] == origin
        ]

    sessions = []
    for row in rows:
        session_parts = [
            PartInfo(
                kind=part["kind"],
                format=part["format"],
                duration_minutes=_num(part["duration_minutes"]),
                rounds=part["rounds"],
                interval_seconds=part["interval_seconds"],
                target_seconds=part["target_seconds"],
                target_rounds=_num(part["target_rounds"]),
                result_seconds=part["result_seconds"],
                result_rounds=_num(part["result_rounds"]),
                planned=line_infos(row["id"], part["position"], "planned"),
                done=line_infos(row["id"], part["position"], "done"),
            )
            for part in parts
            if part["session_id"] == row["id"]
        ]
        sessions.append(
            SessionInfo(
                session_id=row["id"],
                day=row["day"],
                title=row["title"],
                kind=row["kind"],
                status=row["status"],
                garmin_minutes=_num(row["duration_minutes"]),
                garmin_z4_z5_minutes=_num(row["z4_z5_minutes"]),
                parts=session_parts,
                notes=row["notes"] if mode == "full" else None,
                deviation=row["deviation"] if mode == "full" else None,
            )
        )
    return sessions


def build_context(
    conn: psycopg.Connection,
    *,
    week_number: int | None = None,
    today: date | None = None,
    mode: ContextMode = "indicators",
) -> PlanningContext:
    """The context to program `week_number` of the active cycle (default: next week)."""
    today = today or date.today()
    cycles = _rows(
        conn, "select id from cycle where status = 'active' order by start_date desc limit 1"
    )
    if not cycles:
        raise PlanningError("no active cycle: load a program first")
    cycle = cycles[0]
    if week_number is None:
        week = _week(conn, "w.cycle_id = %s and w.start_date > %s", (cycle["id"], today))
    else:
        week = _week(conn, "w.cycle_id = %s and w.number = %s", (cycle["id"], week_number))
    if week is None:
        raise PlanningError("no week to plan in the active cycle")

    target = WeekInfo(
        week_id=week["week_id"],
        number=week["number"],
        start_date=week["start_date"],
        end_date=week["start_date"] + timedelta(days=6),
        phase=week["phase"],
        title=week["title"],
        intent=week["intent"] or {},
        block=week["block"],
        block_intent=week["block_intent"],
        block_strength_sessions_done=week["strength_sessions_done"],
        block_target_strength_sessions=week["target_strength_sessions"],
    )

    previous = None
    prev = _week(conn, "w.cycle_id = %s and w.number = %s", (cycle["id"], week["number"] - 1))
    if prev is not None:
        summary = _rows(
            conn,
            "select sessions, done, missed, cancelled, strength_sessions_done,"
            " coalesce(patterns_done, '{}') as patterns_done"
            " from week_summary where week_id = %s",
            (prev["week_id"],),
        )[0]
        previous = WeekReview(
            number=prev["number"],
            phase=prev["phase"],
            session_details=_sessions(conn, prev["week_id"], mode),
            review=prev["review"] if mode == "full" else None,
            **summary,
        )

    recovery = _rows(
        conn,
        "select m.day, m.recovery_score, m.recovery_status, m.hrv_delta_pct, m.rhr_delta_bpm,"
        " m.sleep_hours, m.acwr, m.trend, r.readiness_score, r.body_battery_highest"
        " from daily_metrics m left join daily_recovery r using (day)"
        " where m.day between %s and %s order by m.day",
        (today - timedelta(days=RECOVERY_DAYS - 1), today),
    )
    alerts = _rows(
        conn,
        "select day, alert, severity, value, threshold from daily_alerts"
        " where day between %s and %s order by day, alert",
        (today - timedelta(days=ALERT_DAYS - 1), today),
    )
    rules = _rows(conn, "select code, text, params from athlete_rule where active order by id")
    exercises = _rows(
        conn, "select name, category, pattern, flags from exercise order by category, pattern, name"
    )
    recent = _rows(
        conn,
        "select distinct on (l.exercise, l.quantity) l.exercise, l.pattern,"
        " l.quantity as reps, l.load_kg, l.rir, p.day"
        " from session_line l join planned_session p on p.id = l.session_id"
        " where l.origin = 'done' and l.load_kg is not null and p.day between %s and %s"
        " order by l.exercise, l.quantity, l.load_kg desc, p.day desc",
        (today - timedelta(days=RECENT_LOAD_DAYS), today),
    )
    feedback = _rows(
        conn,
        "select f.day, f.kind, f.planned_session_id as session_id, p.title as session_title,"
        " f.rpe, f.fatigue, f.pain, f.pain_location, f.notes"
        " from feedback f left join planned_session p on p.id = f.planned_session_id"
        " where f.day between %s and %s order by f.day, f.id",
        (today - timedelta(days=FEEDBACK_DAYS - 1), today),
    )
    goals = _rows(
        conn,
        "select g.title, e.name as exercise,"
        " coalesce(g.target_value::text || coalesce(' ' || g.unit, ''), g.target_text) as target,"
        " g.target_date, g.notes,"
        " (select coalesce(m.value::text || coalesce(' ' || g.unit, ''), m.value_text)"
        "  || coalesce(' (' || m.label || ')', '')"
        "  from goal_milestone m where m.goal_id = g.id and m.day >= %s"
        "  order by m.day limit 1) as next_milestone"
        " from goal g left join exercise e on e.id = g.exercise_id"
        " where g.status = 'active' order by g.target_date nulls last, g.id",
        (today,),
    )

    return PlanningContext(
        today=today,
        mode=mode,
        target_week=target,
        previous_week=previous,
        sessions_already_planned=_sessions(conn, week["week_id"], mode),
        recovery=[DayRecovery(**r) for r in recovery],
        alerts=[Alert(**a) for a in alerts],
        rules=[Rule(**r) for r in rules],
        exercises=[Exercise(**e) for e in exercises],
        recent_loads=[RecentLoad(**r) for r in recent],
        feedback=[
            Feedback(
                **{**f, "notes": f["notes"] if mode == "full" else None},
                lines=_feedback_lines(conn, f["session_id"]),
            )
            for f in feedback
        ],
        goals=[Goal(**{**g, "notes": g["notes"] if mode == "full" else None}) for g in goals],
    )
