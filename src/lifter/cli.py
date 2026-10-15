"""Command line entry point."""

import argparse
import asyncio
from datetime import date, timedelta

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


def format_table(columns: tuple[str, ...], rows: list[tuple]) -> str:
    """Align columns with two spaces; a missing value is shown as "-" so columns never shift."""
    cells = [list(columns)] + [["-" if v is None else str(v) for v in row] for row in rows]
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lifter", description="Training coach on Garmin data.")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(Settings.from_env(), args)
