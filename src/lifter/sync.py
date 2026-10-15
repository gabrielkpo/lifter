"""Copy Garmin data from the MCP server into the raw layer of Postgres.

Each answer is stored as received (see sql/001_raw.sql). Days and activities already stored
are not fetched again, except the most recent days: Garmin often completes a day late
(sleep synced in the morning, training load computed after upload). `refresh=True` refetches
everything in the range, for edits made in Garmin after that window.

An activity that a complete listing no longer returns was deleted or merged in Garmin: it is
tombstoned so the metrics stop counting it (sql/002_activity_tombstone.sql).
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from lifter.garmin import ToolCaller, ToolError

DAILY_TOOLS = ("get_sleep_summary", "get_hrv_data")
ACTIVITY_TOOLS = ("get_activity", "get_activity_hr_in_timezones")
REFRESH_DAYS = 3
PAGE_SIZE = 100


@dataclass
class SyncReport:
    counts: dict[str, int] = field(
        default_factory=lambda: {"stored": 0, "unchanged": 0, "empty": 0, "error": 0, "skipped": 0}
    )

    def add(self, status: str) -> None:
        self.counts[status] += 1


def parse_response(text: str) -> tuple[str, Any]:
    """Classify a tool answer: ("ok", payload), ("empty", None) or ("error", None).

    The server answers JSON on success and plain sentences otherwise
    ("No HRV data found for ...", "Error retrieving ...").
    """
    try:
        # NaN and Infinity are valid for Python's json but rejected by Postgres jsonb.
        return "ok", json.loads(text, parse_constant=lambda _: None)
    except json.JSONDecodeError:
        return ("empty" if text.startswith("No ") else "error"), None


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
    conn: psycopg.Connection, tool: str, natural_key: str, status: str, message: str | None
) -> None:
    conn.execute(
        "insert into sync_log (tool, natural_key, status, message) values (%s, %s, %s, %s)",
        (tool, natural_key, status, message),
    )


def is_stored(conn: psycopg.Connection, tool: str, natural_key: str) -> bool:
    row = conn.execute(
        "select 1 from raw_garmin_payload where tool = %s and natural_key = %s limit 1",
        (tool, natural_key),
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

    def _is_final(self, day: date | None) -> bool:
        """A stored answer for this day is trusted as final and not fetched again."""
        if self.refresh or day is None:
            return False
        return day < self.today - timedelta(days=REFRESH_DAYS)

    async def _fetch(self, tool: str, natural_key: str, params: dict) -> Any:
        """Call one tool, store and log the answer. Returns the payload, or None."""
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
                log_call(self.conn, tool, natural_key, status, None)
            else:
                status = kind
                log_call(self.conn, tool, natural_key, status, text[:500])
        self.report.add(status)
        return payload

    async def sync(self, start: date, end: date) -> SyncReport:
        listed_ids = await self._sync_activities(start, end)
        if listed_ids is not None:
            self._update_tombstones(start, end, listed_ids)
        day = start
        while day <= end:
            for tool in DAILY_TOOLS:
                key = day.isoformat()
                if self._is_final(day) and is_stored(self.conn, tool, key):
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
            listing = await self._fetch("get_activities_by_date", key, params)
            if not isinstance(listing, dict):
                return None
            for activity in listing.get("activities", []):
                listed_ids.add(int(activity["id"]))
                await self._sync_activity(activity)
            if not listing.get("has_more"):
                return listed_ids
            page = listing.get("next_page", page + 1)

    def _update_tombstones(self, start: date, end: date, listed_ids: set[int]) -> None:
        """Tombstone stored activities of the range missing from a complete listing."""
        ids = list(listed_ids)
        with self.conn.transaction():
            self.conn.execute("delete from activity_tombstone where activity_id = any(%s)", (ids,))
            self.conn.execute(
                """
                insert into activity_tombstone (activity_id)
                select activity_id from stg_activity
                where activity_date between %s and %s and not (activity_id = any(%s))
                on conflict do nothing
                """,
                (start, end, ids),
            )

    async def _sync_activity(self, activity: dict) -> None:
        activity_id = str(activity["id"])
        start_time = activity.get("start_time")  # "YYYY-MM-DD HH:MM:SS", local time
        # An activity without a start time is always refetched rather than trusted as final.
        final = self._is_final(date.fromisoformat(start_time[:10]) if start_time else None)
        for tool in ACTIVITY_TOOLS:
            if final and is_stored(self.conn, tool, activity_id):
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
