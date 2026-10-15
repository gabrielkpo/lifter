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


def cmd_migrate(settings: Settings, args: argparse.Namespace) -> int:
    with connect(settings.database_url) as conn:
        applied = migrate(conn)
    print("applied: " + (", ".join(applied) if applied else "nothing, schema up to date"))
    return 0


def cmd_sync(settings: Settings, args: argparse.Namespace) -> int:
    from lifter.garmin import McpToolCaller
    from lifter.sync import sync_range

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

    report = asyncio.run(run())
    print(f"sync {start} -> {end}: " + ", ".join(f"{k}={v}" for k, v in report.counts.items()))
    return 1 if report.counts["error"] else 0


def cmd_metrics(settings: Settings, args: argparse.Namespace) -> int:
    with connect(settings.database_url) as conn:
        rows = conn.execute(
            f"select {', '.join(METRIC_COLUMNS)} from daily_metrics order by day desc limit %s",
            (args.days,),
        ).fetchall()
    print("\t".join(METRIC_COLUMNS))
    for row in reversed(rows):
        print("\t".join("" if v is None else str(v) for v in row))
    return 0


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(Settings.from_env(), args)
