"""Read-only HTTP API of the app: every endpoint reads the analytics views, nothing is computed.

Slice 1 of the app (docs: README, section App). The connection is opened read-only, so no
endpoint can write even by mistake; writes (approving proposals) come in slice 2, through
lifter.domain only.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from lifter import __version__
from lifter.api import models
from lifter.db import connect

# Host headers the API answers: without this check, a page whose name a DNS server rebinds to
# 127.0.0.1 would be same-origin with the API and could read it, CORS or not.
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
MAX_CALENDAR_DAYS = 366
MAX_HEALTH_DAYS = 90


def read_only_url(url: str) -> str:
    """The same database URL, with every transaction read-only (appended to any options)."""
    options = conninfo_to_dict(url).get("options", "")
    return make_conninfo(url, options=f"{options} -c default_transaction_read_only=on".strip())


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    with connect(request.app.state.database_url) as conn:
        conn.row_factory = dict_row
        yield conn


Conn = Annotated[psycopg.Connection, Depends(get_conn)]


def garmin_line(row: dict[str, Any]) -> models.GarminLine | None:
    """The Garmin columns of a row joined to session_garmin; None when no activity matched."""
    if row["activities"] is None:
        return None
    return models.GarminLine.model_validate(row)


WEEK_SQL = """
    select ws.week_id as id, w.cycle_id, ws.block_id, ws.block, ws.number, ws.start_date,
        ws.phase, w.title, w.intent, w.review, ws.sessions, ws.done, ws.missed, ws.cancelled,
        ws.strength_sessions_done, coalesce(ws.patterns_done, '{}') as patterns_done,
        b.intent as block_intent
    from week_summary ws
    join training_week w on w.id = ws.week_id
    left join block b on b.id = ws.block_id
"""

GARMIN_COLUMNS = (
    "g.activities, g.duration_minutes, g.avg_hr_bpm, g.max_hr_bpm, g.calories,"
    " g.training_load, g.z4_z5_minutes"
)


def week_detail(conn: psycopg.Connection, week: dict[str, Any]) -> models.WeekDetail:
    # The week's sessions, plus those outside any week (added by the athlete or an agent) on
    # one of its days.
    rows = conn.execute(
        "select s.planned_session_id as id, s.day, s.title, s.kind, s.status, s.moved_from,"
        f" s.logged, {GARMIN_COLUMNS}"
        " from planned_session_status s"
        " left join session_garmin g using (planned_session_id)"
        " where s.week_id = %s"
        " or (s.week_id is null and s.day between %s and %s::date + 6)"
        " order by s.day, s.planned_session_id",
        (week["id"], week["start_date"], week["start_date"]),
    ).fetchall()
    return models.WeekDetail(
        week=models.Week.model_validate(week),
        block_intent=week["block_intent"],
        sessions=[models.SessionSummary(**row, garmin=garmin_line(row)) for row in rows],
    )


def create_app(database_url: str, app_origins: list[str] | None = None) -> FastAPI:
    """The API on `database_url`, opened read-only; `app_origins` may call it from a browser."""
    app = FastAPI(title="Lifter API", version=__version__)
    app.state.database_url = read_only_url(database_url)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_origins or [],
        allow_methods=["GET"],
        allow_headers=[],
    )

    @app.get("/program")
    def program(conn: Conn) -> models.Program:
        """Cycles and their blocks, with each block's strength-session count."""
        cycles = conn.execute(
            "select id, name, start_date, end_date, status, notes from cycle"
            " order by start_date, id"
        ).fetchall()
        blocks = conn.execute(
            "select bp.block_id as id, bp.cycle_id, bp.position, bp.kind, bp.start_date,"
            " bp.end_date, b.intent, bp.target_strength_sessions, bp.strength_sessions_done"
            " from block_progress bp join block b on b.id = bp.block_id"
            " order by bp.cycle_id, bp.position"
        ).fetchall()
        return models.Program(
            cycles=[
                models.Cycle(**cycle, blocks=[b for b in blocks if b["cycle_id"] == cycle["id"]])
                for cycle in cycles
            ]
        )

    @app.get("/weeks")
    def weeks(conn: Conn) -> list[models.Week]:
        """The review of every week, in calendar order."""
        return conn.execute(WEEK_SQL + " order by ws.start_date, ws.week_id").fetchall()

    @app.get("/weeks/current")
    def current_week(conn: Conn) -> models.WeekDetail:
        """The week of the cycle that contains today, with its sessions."""
        week = conn.execute(
            WEEK_SQL + " where ws.start_date <= current_date"
            " and current_date < ws.start_date + 7 order by ws.start_date desc limit 1"
        ).fetchone()
        if week is None:
            raise HTTPException(404, "no week of the program contains today")
        return week_detail(conn, week)

    @app.get("/weeks/{week_id}")
    def week(conn: Conn, week_id: int) -> models.WeekDetail:
        """A week's review and its sessions, with their status and Garmin line."""
        row = conn.execute(WEEK_SQL + " where ws.week_id = %s", (week_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"week {week_id} does not exist")
        return week_detail(conn, row)

    @app.get("/calendar")
    def calendar(
        conn: Conn, start: date | None = None, end: date | None = None
    ) -> list[models.CalendarItem]:
        """Sessions and activities between two days (default: a week ago to two weeks ahead)."""
        start = start or date.today() - timedelta(days=7)
        end = end or start + timedelta(days=21)
        if end < start:
            raise HTTPException(422, "end is before start")
        if (end - start).days >= MAX_CALENDAR_DAYS:
            raise HTTPException(422, f"at most {MAX_CALENDAR_DAYS} days at once")
        return conn.execute(
            "select day, kind, source, title, detail, status,"
            " planned_session_id as session_id, activity_id"
            " from calendar where day between %s and %s"
            " order by day, kind desc, planned_session_id nulls last, title",
            (start, end),
        ).fetchall()

    @app.get("/sessions/{session_id}")
    def session(conn: Conn, session_id: int) -> models.SessionDetail:
        """A session: its parts, planned and done lines side by side, and its Garmin line."""
        head = conn.execute(
            "select s.planned_session_id as id, s.day, s.title, s.kind, s.status, s.week_id,"
            f" s.moved_from, p.notes, p.deviation, {GARMIN_COLUMNS}"
            " from planned_session_status s join planned_session p on p.id = s.planned_session_id"
            " left join session_garmin g using (planned_session_id)"
            " where s.planned_session_id = %s",
            (session_id,),
        ).fetchone()
        if head is None:
            raise HTTPException(404, f"session {session_id} does not exist")
        parts = conn.execute(
            "select position, kind, title, notes, format, duration_minutes, rounds,"
            " interval_seconds, target_seconds, target_rounds, result_seconds, result_rounds,"
            " result_notes from session_part where session_id = %s order by position",
            (session_id,),
        ).fetchall()
        lines = conn.execute(
            "select part_position, origin, position, exercise, category, pattern, sets,"
            " quantity, unit, load_kg, load_kg_max, rir, rest_seconds, notes"
            " from session_line where session_id = %s order by part_position, position",
            (session_id,),
        ).fetchall()
        return models.SessionDetail(
            **head,
            garmin=garmin_line(head),
            parts=[
                models.Part(
                    **part,
                    **{
                        origin: [
                            line
                            for line in lines
                            if line["part_position"] == part["position"]
                            and line["origin"] == origin
                        ]
                        for origin in ("planned", "done")
                    },
                )
                for part in parts
            ],
        )

    @app.get("/health")
    def health(
        conn: Conn, days: Annotated[int, Query(ge=1, le=MAX_HEALTH_DAYS)] = 14
    ) -> models.Health:
        """The last `days` days with data: Lifter's metrics, Garmin's recovery, alerts."""
        metrics = conn.execute(
            "select * from daily_metrics order by day desc limit %s", (days,)
        ).fetchall()
        recovery = conn.execute(
            "select * from daily_recovery order by day desc limit %s", (days,)
        ).fetchall()
        first_day = min((row["day"] for row in metrics), default=None)
        alerts = (
            conn.execute(
                "select day, alert, severity, value, threshold from daily_alerts"
                " where day >= %s order by day, alert",
                (first_day,),
            ).fetchall()
            if first_day
            else []
        )
        return models.Health(
            metrics=list(reversed(metrics)), recovery=list(reversed(recovery)), alerts=alerts
        )

    @app.get("/goals")
    def goals(conn: Conn) -> list[models.Goal]:
        """Goals, active first, with their milestones in date order."""
        goals = conn.execute(
            "select g.id, g.title, g.kind, e.name as exercise, g.unit, g.baseline_value,"
            " g.baseline_text, g.baseline_date, g.target_value, g.target_text, g.target_date,"
            " g.status, g.notes"
            " from goal g left join exercise e on e.id = g.exercise_id"
            " order by g.status <> 'active', g.status, g.target_date nulls last, g.id"
        ).fetchall()
        milestones = conn.execute(
            "select goal_id, day, label, value, value_text from goal_milestone"
            " order by goal_id, day, id"
        ).fetchall()
        return [
            models.Goal(**goal, milestones=[m for m in milestones if m["goal_id"] == goal["id"]])
            for goal in goals
        ]

    @app.get("/bests")
    def bests(conn: Conn) -> list[models.Best]:
        """Best logged load per exercise and repetition count."""
        return conn.execute(
            "select exercise, reps, best_load_kg, day from exercise_best order by exercise, reps"
        ).fetchall()

    @app.get("/proposals")
    def proposals(conn: Conn, status: models.ProposalStatus = "pending") -> list[models.Proposal]:
        """The agents' proposals with a given status, oldest first."""
        return conn.execute(
            "select id, kind, payload, rationale, author, status, result, created_at,"
            " decided_at, applied_at from proposal where status = %s order by id",
            (status,),
        ).fetchall()

    return app
