"""Command line entry point."""

import argparse
import asyncio
from datetime import date, timedelta
from pathlib import Path

from lifter import __version__
from lifter.config import Settings
from lifter.db import connect, migrate

METRIC_COLUMNS = (
    "day",
    "load",
    "acute_load_7d",
    "chronic_load_28d",
    "acwr",
    "hrv_delta_pct",
    "rhr_delta_bpm",
    "sleep_hours",
    "recovery_score",
    "recovery_status",
    "trend",
)

RECOVERY_COLUMNS = (
    "day",
    "sleep_hours",
    "sleep_score",
    "body_battery_highest",
    "body_battery_lowest",
    "avg_stress",
    "readiness_score",
    "readiness_level",
    "garmin_acute_load",
    "garmin_chronic_load",
    "garmin_training_status",
    "vo2_max",
)


def cmd_migrate(settings: Settings, args: argparse.Namespace) -> int:
    with connect(settings.database_url) as conn:
        applied = migrate(conn)
    print("applied: " + (", ".join(applied) if applied else "nothing, schema up to date"))
    return 0


def cmd_sync(settings: Settings, args: argparse.Namespace) -> int:
    from lifter.garmin import McpToolCaller
    from lifter.sync import SyncAborted, sync_range

    if not settings.garmin_mcp_token:
        print("GARMIN_MCP_TOKEN is not set (see .env.example)")
        return 2
    end = args.end or date.today()
    start = args.start or end - timedelta(days=args.days - 1)

    async def run():
        async with McpToolCaller(settings.garmin_mcp_url, settings.garmin_mcp_token) as caller:
            with connect(settings.database_url) as conn:
                migrate(conn)
                return await sync_range(
                    caller,
                    conn,
                    start,
                    end,
                    delay_seconds=settings.sync_delay_seconds,
                    refresh=args.refresh,
                )

    try:
        report = asyncio.run(run())
    except SyncAborted as exc:
        print(f"sync stopped: {exc}")
        return 1
    print(f"sync {start} -> {end}: " + ", ".join(f"{k}={v}" for k, v in report.counts.items()))
    return 1 if report.counts["error"] else 0


def printable(value: object) -> str:
    """Text safe to print: control characters (terminal escapes, newlines) are shown escaped.

    Agent rationales and Garmin names are untrusted: an escape sequence must never be able to
    hide or rewrite what the athlete reads before approving.
    """
    text = "-" if value is None else str(value)
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in text)


def format_table(columns: tuple[str, ...], rows: list[tuple]) -> str:
    """Align columns with two spaces; a missing value is shown as "-" so columns never shift."""
    cells = [list(columns)] + [[printable(v) for v in row] for row in rows]
    widths = [max(len(line[i]) for line in cells) for i in range(len(columns))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in cells
    )


def print_last_days(settings: Settings, view: str, columns: tuple[str, ...], days: int) -> int:
    """Print the last `days` rows of an analytics view, oldest first."""
    with connect(settings.database_url) as conn:
        rows = conn.execute(
            f"select {', '.join(columns)} from {view} order by day desc limit %s", (days,)
        ).fetchall()
    print(format_table(columns, list(reversed(rows))))
    return 0


def cmd_metrics(settings: Settings, args: argparse.Namespace) -> int:
    return print_last_days(settings, "daily_metrics", METRIC_COLUMNS, args.days)


def cmd_recovery(settings: Settings, args: argparse.Namespace) -> int:
    return print_last_days(settings, "daily_recovery", RECOVERY_COLUMNS, args.days)


def print_query(settings: Settings, sql: str, params: tuple = ()) -> int:
    """Print a fixed query of this module as an aligned table."""
    with connect(settings.database_url) as conn:
        cur = conn.execute(sql, params)
        columns = tuple(c.name for c in cur.description)
        rows = cur.fetchall()
    print(format_table(columns, rows))
    return 0


def cmd_calendar(settings: Settings, args: argparse.Namespace) -> int:
    start = args.start or date.today() - timedelta(days=args.past)
    end = start + timedelta(days=args.past + args.ahead)
    return print_query(
        settings,
        "select day, kind, source, status, detail, title, planned_session_id as session"
        " from calendar where day between %s and %s order by day, kind, title",
        (start, end),
    )


def cmd_program(settings: Settings, args: argparse.Namespace) -> int:
    return print_query(
        settings,
        "select c.name as cycle, b.position as block, b.kind, b.start_date, b.end_date,"
        " b.strength_sessions_done as done, b.target_strength_sessions as target"
        " from block_progress b join cycle c on c.id = b.cycle_id"
        " order by c.start_date, b.position",
    )


def cmd_program_load(settings: Settings, args: argparse.Namespace) -> int:
    import yaml

    from lifter.program import load_program, read_program

    try:
        program = read_program(args.file)
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot read {args.file}: {exc}")
        return 2

    def load(conn):
        migrate(conn)
        counts = load_program(conn, program, replace=args.replace)
        return "loaded: " + ", ".join(f"{k}={v}" for k, v in counts.items())

    return _with_domain(settings, load)


def cmd_weeks(settings: Settings, args: argparse.Namespace) -> int:
    return print_query(
        settings,
        "select number as week, start_date, block, phase, sessions, done, missed, cancelled,"
        " strength_sessions_done as strength, array_to_string(patterns_done, ' ') as patterns"
        " from week_summary order by number",
    )


def cmd_week(settings: Settings, args: argparse.Namespace) -> int:
    return print_query(
        settings,
        "select s.day, s.planned_session_id as session, s.kind, s.status, s.title,"
        " g.duration_minutes as minutes, g.avg_hr_bpm as avg_hr, g.z4_z5_minutes as z4_z5"
        " from planned_session_status s"
        " join training_week w on w.id = s.week_id"
        " left join session_garmin g using (planned_session_id)"
        " where w.number = %s order by s.day, s.planned_session_id",
        (args.number,),
    )


def _line(row: tuple) -> str:
    """'Bench 4x8 @ 60-62.5 kg RIR 2, rest 120 s' from a session_line row."""
    exercise, sets, quantity, unit, load, load_max, rir, rest, notes = row

    def num(x):
        return f"{x:g}"

    text = exercise
    if quantity is not None:
        amount = num(quantity) + ("" if unit == "reps" else f" {unit}")
        text += f" {sets}x{amount}" if sets else f" {amount}"
    elif sets:
        text += f" {sets} sets"
    if load is not None:
        text += f" @ {num(load)}" + (f"-{num(load_max)}" if load_max is not None else "") + " kg"
    if rir is not None:
        text += f" RIR {rir}"
    if rest is not None:
        text += f", rest {rest} s"
    if notes:
        text += f" ({notes})"
    return printable(text)


def cmd_session(settings: Settings, args: argparse.Namespace) -> int:
    with connect(settings.database_url) as conn:
        head = conn.execute(
            "select s.day, s.title, s.kind, s.status, s.moved_from, p.notes, p.deviation,"
            " g.duration_minutes, g.avg_hr_bpm, g.max_hr_bpm, g.calories, g.z4_z5_minutes"
            " from planned_session_status s join planned_session p on p.id = s.planned_session_id"
            " left join session_garmin g using (planned_session_id)"
            " where s.planned_session_id = %s",
            (args.id,),
        ).fetchone()
        if head is None:
            print(f"session {args.id} does not exist")
            return 1
        parts = conn.execute(
            "select id, position, kind, title, format, duration_minutes, rounds, interval_seconds,"
            " target_seconds, target_rounds, result_seconds, result_rounds, result_notes, notes"
            " from session_part where session_id = %s order by position",
            (args.id,),
        ).fetchall()
        lines = conn.execute(
            "select part_position, origin, exercise, sets, quantity, unit, load_kg, load_kg_max,"
            " rir, rest_seconds, notes from session_line where session_id = %s"
            " order by part_position, origin desc, position",
            (args.id,),
        ).fetchall()
    day, title, kind, status, moved_from, notes, deviation, *garmin = head
    out = [printable(f"{day} {title} ({kind}, {status})")]
    if moved_from:
        out.append(f"  moved from {moved_from}")
    if garmin[0] is not None:
        labels = ("min", "avg HR", "max HR", "kcal", "min in Z4-Z5")
        values = zip(garmin, labels, strict=True)
        out.append("  Garmin: " + ", ".join(f"{printable(v)} {k}" for v, k in values))
    for part in parts:
        _, position, part_kind, part_title, fmt, minutes, rounds, interval, *rest = part
        target_s, target_r, result_s, result_r, result_notes, part_notes = rest
        header = f"{position}. {part_kind}" + (f": {part_title}" if part_title else "")
        details = [
            fmt and fmt.replace("_", " "),
            minutes and f"{minutes:g} min",
            rounds and f"{rounds} rounds",
            interval and f"every {interval} s",
            target_s and f"target {target_s // 60}'{target_s % 60:02d}",
            target_r and f"target {target_r:g} rounds",
            result_s and f"done in {result_s // 60}'{result_s % 60:02d}",
            result_r is not None and f"{result_r:g} rounds done",
        ]
        details = [d for d in details if d]
        out.append(printable(header + (f" [{', '.join(details)}]" if details else "")))
        for origin in ("planned", "done"):
            for line in lines:
                if line[0] == position and line[1] == origin:
                    out.append(f"   {origin:<7} {_line(line[2:])}")
        for label, text in (("result", result_notes), ("notes", part_notes)):
            if text:
                out.append(f"   {label:<7} {printable(text)}")
    for label, text in (("notes", notes), ("deviation", deviation)):
        if text:
            out.append(f"  {label}: {printable(text)}")
    print("\n".join(out))
    return 0


def cmd_exercises(settings: Settings, args: argparse.Namespace) -> int:
    return print_query(
        settings,
        "select name, category, pattern, equipment, array_to_string(flags, ' ') as flags"
        " from exercise order by category, pattern, name",
    )


def cmd_bests(settings: Settings, args: argparse.Namespace) -> int:
    return print_query(
        settings,
        "select exercise, reps, best_load_kg, day from exercise_best order by exercise, reps",
    )


def cmd_goals(settings: Settings, args: argparse.Namespace) -> int:
    return print_query(
        settings,
        "select g.id, g.status, g.kind, g.title, e.name as exercise,"
        " coalesce(g.baseline_value::text, g.baseline_text) as baseline,"
        " coalesce(g.target_value::text, g.target_text) as target, g.unit, g.target_date"
        " from goal g left join exercise e on e.id = g.exercise_id"
        " order by g.status, g.target_date nulls last, g.id",
    )


def cmd_proposals(settings: Settings, args: argparse.Namespace) -> int:
    return print_query(
        settings,
        "select id, status, kind, author, created_at::date as day, rationale, payload::text"
        " from proposal where status = any(%s) order by id",
        (
            ["pending"]
            if not args.all
            else ["pending", "approved", "rejected", "applied", "failed"],
        ),
    )


def _with_domain(settings: Settings, action) -> int:
    from lifter.domain import DomainError

    try:
        with connect(settings.database_url) as conn:
            message = action(conn)
    except DomainError as exc:
        print(f"refused: {exc}")
        return 1
    print(message)
    return 0


def cmd_goal_add(settings: Settings, args: argparse.Namespace) -> int:
    from lifter import domain

    goal = domain.GoalIn(
        title=args.title,
        kind=args.kind,
        exercise=args.exercise,
        target_date=args.date,
        target_value=args.target,
        target_text=args.text,
        unit=args.unit,
        notes=args.notes,
    )
    return _with_domain(settings, lambda conn: f"goal {domain.create_goal(conn, goal)} created")


def cmd_session_add(settings: Settings, args: argparse.Namespace) -> int:
    from lifter import domain

    session = domain.SessionIn(day=args.day, title=args.title, kind=args.kind, notes=args.notes)
    return _with_domain(
        settings, lambda conn: f"session {domain.create_session(conn, session)} created"
    )


def cmd_session_move(settings: Settings, args: argparse.Namespace) -> int:
    from lifter import domain

    move = domain.MoveSession(session_id=args.id, new_day=args.day)
    return _with_domain(
        settings, lambda conn: domain.move_session(conn, move) or f"session {args.id} moved"
    )


def cmd_session_cancel(settings: Settings, args: argparse.Namespace) -> int:
    from lifter import domain

    cancel = domain.CancelSession(session_id=args.id)
    return _with_domain(
        settings, lambda conn: domain.cancel_session(conn, cancel) or f"session {args.id} cancelled"
    )


def cmd_feedback(settings: Settings, args: argparse.Namespace) -> int:
    from lifter import domain

    feedback = domain.FeedbackIn(
        day=args.day,
        kind=args.kind,
        planned_session_id=args.session,
        rpe=args.rpe,
        fatigue=args.fatigue,
        pain=args.pain,
        pain_location=args.where,
        notes=args.notes,
    )
    return _with_domain(
        settings, lambda conn: f"feedback {domain.add_feedback(conn, feedback)} saved"
    )


def cmd_proposal_decide(settings: Settings, args: argparse.Namespace) -> int:
    from lifter import domain

    def decide(conn):
        domain.decide(conn, args.id, approve=args.decision == "approve")
        if args.decision == "reject":
            return f"proposal {args.id} rejected"
        return f"proposal {args.id} applied: {domain.apply(conn, args.id)}"

    return _with_domain(settings, decide)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lifter", description="CrossFit coach on Garmin data.")
    parser.add_argument("--version", action="version", version=f"lifter {__version__}")
    sub = parser.add_subparsers(dest="command")

    migrate_cmd = sub.add_parser("migrate", help="create or update the database schema")
    migrate_cmd.set_defaults(func=cmd_migrate)

    sync = sub.add_parser("sync", help="copy Garmin data into Postgres (read-only on Garmin)")
    sync.add_argument("--days", type=int, default=30, help="days back from --end (default 30)")
    sync.add_argument("--start", type=date.fromisoformat, help="first day, YYYY-MM-DD")
    sync.add_argument("--end", type=date.fromisoformat, help="last day, YYYY-MM-DD (default today)")
    sync.add_argument(
        "--refresh", action="store_true", help="refetch days and activities already stored"
    )
    sync.set_defaults(func=cmd_sync)

    metrics = sub.add_parser("metrics", help="print the daily metrics of the last days")
    metrics.add_argument("--days", type=int, default=14)
    metrics.set_defaults(func=cmd_metrics)

    recovery = sub.add_parser("recovery", help="print Garmin's recovery and form values")
    recovery.add_argument("--days", type=int, default=14)
    recovery.set_defaults(func=cmd_recovery)

    cal = sub.add_parser("calendar", help="print the calendar: sessions and activities")
    cal.add_argument("--start", type=date.fromisoformat, help="first day (default: --past ago)")
    cal.add_argument("--past", type=int, default=7, help="days before today (default 7)")
    cal.add_argument("--ahead", type=int, default=14, help="days after the start (default 14)")
    cal.set_defaults(func=cmd_calendar)

    program = sub.add_parser("program", help="print the cycle's blocks and their progress")
    program.set_defaults(func=cmd_program)
    program_sub = program.add_subparsers(dest="program_command")
    load = program_sub.add_parser("load", help="load a program file (YAML)")
    load.add_argument("file", type=Path)
    load.add_argument(
        "--replace", action="store_true", help="delete the loaded program first, then load"
    )
    load.set_defaults(func=cmd_program_load)

    sub.add_parser("weeks", help="print the review of every week").set_defaults(func=cmd_weeks)
    week = sub.add_parser("week", help="print the sessions of a week")
    week.add_argument("number", type=int)
    week.set_defaults(func=cmd_week)

    show = sub.add_parser("session", help="print a session: parts, planned and done, Garmin")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_session)

    sub.add_parser("exercises", help="print the exercise bank").set_defaults(func=cmd_exercises)
    sub.add_parser("bests", help="print the best logged loads").set_defaults(func=cmd_bests)
    sub.add_parser("goals", help="print goals").set_defaults(func=cmd_goals)

    goal = sub.add_parser("goal-add", help="add a goal")
    goal.add_argument("title")
    goal.add_argument("--kind", default="strength")
    goal.add_argument("--exercise", help="exercise name, from the bank")
    goal.add_argument("--target", type=float, help="target value")
    goal.add_argument("--text", help="target as text, e.g. 'first rep without a band'")
    goal.add_argument("--unit")
    goal.add_argument("--date", type=date.fromisoformat)
    goal.add_argument("--notes")
    goal.set_defaults(func=cmd_goal_add)

    sess = sub.add_parser("session-add", help="add an empty session to the calendar")
    sess.add_argument("day", type=date.fromisoformat)
    sess.add_argument("title")
    sess.add_argument("--kind", default="training")
    sess.add_argument("--notes")
    sess.set_defaults(func=cmd_session_add)

    move = sub.add_parser("session-move", help="move a planned session to another day")
    move.add_argument("id", type=int)
    move.add_argument("day", type=date.fromisoformat)
    move.set_defaults(func=cmd_session_move)

    cancel = sub.add_parser("session-cancel", help="cancel a planned session")
    cancel.add_argument("id", type=int)
    cancel.set_defaults(func=cmd_session_cancel)

    fb = sub.add_parser("feedback", help="report how a session or a morning went")
    fb.add_argument("--day", type=date.fromisoformat, default=date.today())
    fb.add_argument("--kind", choices=["session", "morning"], default="session")
    fb.add_argument("--session", type=int, help="planned session id")
    fb.add_argument("--rpe", type=int, help="1 to 10")
    fb.add_argument("--fatigue", type=int, help="1 to 5")
    fb.add_argument("--pain", type=int, help="0 to 10")
    fb.add_argument("--where", help="where it hurts")
    fb.add_argument("--notes")
    fb.set_defaults(func=cmd_feedback)

    props = sub.add_parser("proposals", help="print the agents' pending proposals")
    props.add_argument("--all", action="store_true", help="include decided proposals")
    props.set_defaults(func=cmd_proposals)

    decide = sub.add_parser("proposal", help="approve (and apply) or reject a proposal")
    decide.add_argument("decision", choices=["approve", "reject"])
    decide.add_argument("id", type=int)
    decide.set_defaults(func=cmd_proposal_decide)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    from pydantic import ValidationError

    try:
        return args.func(Settings.from_env(), args)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()
        )
        print(f"invalid input: {problems}")
        return 2
