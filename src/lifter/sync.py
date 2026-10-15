"""Copy Garmin data from the MCP server into the raw layer of Postgres.

Each answer is stored as received (see sql/001_raw.sql). Days and activities Garmin already
answered (with data, or with "no data") are not fetched again, except the most recent days:
Garmin often completes a day late (sleep synced in the morning, training load computed after
upload). `refresh=True` refetches
everything in the range, for edits made in Garmin after that window.

A stored activity that a complete listing no longer returns is checked with get_activity:
only a confirmed "not found" tombstones it, so the metrics stop counting it
(sql/004_activity_tombstone.sql). Paging shifts or date boundaries never delete anything.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from lifter.garmin import ToolCaller, ToolError

# One call per day and tool. get_stats carries Body Battery, stress, resting HR, SpO2,
# respiration and intensity minutes; get_training_status carries Garmin's own load and VO2max.
DAILY_TOOLS = (
    "get_sleep_summary",
    "get_hrv_data",
    "get_stats",
    "get_training_readiness",
    "get_training_status",
)
ACTIVITY_TOOLS = ("get_activity", "get_activity_hr_in_timezones")
REFRESH_DAYS = 3
PAGE_SIZE = 100
MAX_CONSECUTIVE_ERRORS = 5  # the server is down or unreachable: stop instead of hammering it
# The Garmin client reports a missing resource as "API Error 404" / "HTTP 404 Not Found".
NOT_FOUND = re.compile(r"\bHTTP 404\b|\bAPI Error 404\b")


class SyncAborted(RuntimeError):
    """Too many consecutive failed calls: the sync stopped early."""


@dataclass
class SyncReport:
    counts: dict[str, int] = field(
        default_factory=lambda: {"stored": 0, "unchanged": 0, "empty": 0, "error": 0, "skipped": 0}
    )

    def add(self, status: str) -> None:
        self.counts[status] += 1


def parse_response(text: str) -> tuple[str, Any]:
    """Classify a tool answer: ("ok", payload), ("empty", None) or ("error", None).

    The server answers JSON on success and plain sentences otherwise: "No HRV data found
    for ...", or "Error retrieving ...". An error carrying HTTP 404 means the resource does
    not exist (a deleted activity), so it is "empty", not a failure.
    """
    try:
        # NaN and Infinity are valid for Python's json but rejected by Postgres jsonb.
        return "ok", json.loads(text, parse_constant=lambda _: None)
    except json.JSONDecodeError:
        if text.startswith("No ") or NOT_FOUND.search(text):
            return "empty", None
        return "error", None


def payload_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def store_payload(
    conn: psycopg.Connection, tool: str, natural_key: str, params: dict, payload: Any
) -> str:
    """Insert a payload, or only bump last_seen_at if this exact payload is known."""
    row = conn.execute(
        """
        insert into raw_garmin_payload (tool, natural_key, params, payload, payload_sha256)
        values (%s, %s, %s, %s, %s)
        on conflict (tool, natural_key, payload_sha256)
            do update set last_seen_at = now()
        returning (xmax = 0) as inserted
        """,
        (
            tool,
            natural_key,
            Jsonb(params),
            Jsonb(payload),
            payload_sha256(payload),
        ),
    ).fetchone()
    return "stored" if row[0] else "unchanged"


def log_call(
    conn: psycopg.Connection,
    tool: str,
    natural_key: str,
    status: str,
    message: str | None,
    as_of: date | None = None,
) -> None:
    conn.execute(
        "insert into sync_log (tool, natural_key, status, message, as_of)"
        " values (%s, %s, %s, %s, %s)",
        (tool, natural_key, status, message, as_of),
    )


def is_known(
    conn: psycopg.Connection, tool: str, natural_key: str, day: date | None = None
) -> bool:
    """Garmin already answered for this key: a stored payload, or a final "no data".

    For a day, "no data" only counts once it was answered after the refetch window: a watch
    that stayed offline for a few days uploads them later, and they must be asked again.
    """
    row = conn.execute(
        """
        select 1 from raw_garmin_payload where tool = %s and natural_key = %s
        union all
        select 1 from sync_log
        where tool = %s and natural_key = %s and status = 'empty'
            and (%s::date is null or coalesce(as_of, at::date) > %s::date + %s)
        limit 1
        """,
        (tool, natural_key, tool, natural_key, day, day, REFRESH_DAYS),
    ).fetchone()
    return row is not None


class Syncer:
    def __init__(
        self,
        caller: ToolCaller,
        conn: psycopg.Connection,
        *,
        today: date | None = None,
        delay_seconds: float = 0.0,
        refresh: bool = False,
    ):
        self.caller = caller
        self.conn = conn
        self.today = today or date.today()
        self.delay_seconds = delay_seconds
        self.refresh = refresh
        self.report = SyncReport()
        self.consecutive_errors = 0

    def _is_final(self, day: date | None) -> bool:
        """A stored answer for this day is trusted as final and not fetched again."""
        if self.refresh or day is None:
            return False
        return day < self.today - timedelta(days=REFRESH_DAYS)

    async def _fetch(self, tool: str, natural_key: str, params: dict) -> tuple[str, Any]:
        """Call one tool, store and log the answer. Returns (status, payload or None)."""
        try:
            text = await self.caller.call(tool, params)
            kind, payload = parse_response(text)
        except ToolError as exc:
            kind, payload, text = "error", None, str(exc)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)  # stay gentle with Garmin Connect
        with self.conn.transaction():
            if kind == "ok":
                status = store_payload(self.conn, tool, natural_key, params, payload)
                log_call(self.conn, tool, natural_key, status, None, self.today)
            else:
                status = kind
                log_call(self.conn, tool, natural_key, status, text[:500], self.today)
        self.report.add(status)
        self.consecutive_errors = self.consecutive_errors + 1 if status == "error" else 0
        if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            raise SyncAborted(f"{MAX_CONSECUTIVE_ERRORS} failed calls in a row, last: {text[:200]}")
        return status, payload

    async def sync(self, start: date, end: date) -> SyncReport:
        listed_ids = await self._sync_activities(start, end)
        if listed_ids is not None:
            await self._reconcile_deleted(start, end, listed_ids)
        day = start
        while day <= end:
            for tool in DAILY_TOOLS:
                key = day.isoformat()
                if self._is_final(day) and is_known(self.conn, tool, key, day):
                    self.report.add("skipped")
                    continue
                await self._fetch(tool, key, {"date": key})
            day += timedelta(days=1)
        return self.report

    async def _sync_activities(self, start: date, end: date) -> set[int] | None:
        """Fetch the listing and the details of each activity.

        Returns the ids listed in the range, or None if the listing is incomplete.
        """
        listed_ids: set[int] = set()
        page = 0
        while True:
            params = {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "page": page,
                "page_size": PAGE_SIZE,
            }
            key = f"{start.isoformat()}..{end.isoformat()}#{page}"
            _, listing = await self._fetch("get_activities_by_date", key, params)
            if not isinstance(listing, dict):
                return None
            for activity in listing.get("activities", []):
                listed_ids.add(int(activity["id"]))
                await self._sync_activity(activity)
            if not listing.get("has_more"):
                return listed_ids
            page = listing.get("next_page", page + 1)

    async def _reconcile_deleted(self, start: date, end: date, listed_ids: set[int]) -> None:
        """Ask Garmin about each known activity of the range missing from a complete listing.

        Only a confirmed "not found" tombstones it; an activity found again is restored.
        """
        self._restore(listed_ids)
        known = self.conn.execute(
            """
            select activity_id from stg_activity where activity_date between %s and %s
            union
            select activity_id from stg_activity_listed where activity_date between %s and %s
            """,
            (start, end, start, end),
        ).fetchall()
        for (activity_id,) in known:
            if activity_id in listed_ids:
                continue
            status, _ = await self._fetch(
                "get_activity", str(activity_id), {"activity_id": activity_id}
            )
            if status == "empty":
                self.conn.execute(
                    "insert into activity_tombstone (activity_id) values (%s)"
                    " on conflict do nothing",
                    (activity_id,),
                )
            elif status != "error":
                self._restore({activity_id})

    def _restore(self, activity_ids: set[int]) -> None:
        self.conn.execute(
            "delete from activity_tombstone where activity_id = any(%s)", (list(activity_ids),)
        )

    async def _sync_activity(self, activity: dict) -> None:
        activity_id = str(activity["id"])
        start_time = activity.get("start_time")  # "YYYY-MM-DD HH:MM:SS", local time
        # An activity without a start time is always refetched rather than trusted as final.
        final = self._is_final(date.fromisoformat(start_time[:10]) if start_time else None)
        for tool in ACTIVITY_TOOLS:
            if final and is_known(self.conn, tool, activity_id):
                self.report.add("skipped")
                continue
            await self._fetch(tool, activity_id, {"activity_id": int(activity_id)})


async def sync_range(
    caller: ToolCaller,
    conn: psycopg.Connection,
    start: date,
    end: date,
    *,
    today: date | None = None,
    delay_seconds: float = 0.0,
    refresh: bool = False,
) -> SyncReport:
    syncer = Syncer(caller, conn, today=today, delay_seconds=delay_seconds, refresh=refresh)
    return await syncer.sync(start, end)
