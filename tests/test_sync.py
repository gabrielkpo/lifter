import asyncio
import json
from datetime import date

import pytest

from lifter.garmin import McpToolCaller, ToolError
from lifter.sync import sync_range
from synthetic import activity, hr_zones, hrv, sleep

D1, D2 = date(2026, 3, 2), date(2026, 3, 3)


class FakeCaller:
    """Answers like the Garmin MCP server, from a dict keyed by (tool, natural key)."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if "date" in arguments:
            key = arguments["date"]
        elif "activity_id" in arguments:
            key = arguments["activity_id"]
        else:
            key = arguments["page"]
        answer = self.answers.get((tool, key), f"No data found for {key}")
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)


def listing(activities, *, page=0, has_more=False):
    data = {"count": len(activities), "page": page, "has_more": has_more, "activities": activities}
    if has_more:
        data["next_page"] = page + 1
    return data


def two_days():
    run = activity(11, D1, load=90)
    return {
        ("get_activities_by_date", 0): listing([{"id": 11, "start_time": run["start_time_local"]}]),
        ("get_activity", 11): run,
        ("get_activity_hr_in_timezones", 11): hr_zones([60, 120, 0, 0, 0]),
        ("get_sleep_summary", D1.isoformat()): sleep(7.5, 50),
        ("get_sleep_summary", D2.isoformat()): sleep(7.0, 51),
        ("get_hrv_data", D1.isoformat()): hrv(D1, 60),
        ("get_hrv_data", D2.isoformat()): hrv(D2, 58),
    }


def run_sync(conn, caller, today):
    return asyncio.run(sync_range(caller, conn, D1, D2, today=today))


def log_statuses(conn):
    return dict(conn.execute("select status, count(*) from sync_log group by status").fetchall())


def test_first_sync_stores_every_answer(conn):
    report = run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))

    assert report.counts == {"stored": 7, "unchanged": 0, "empty": 0, "error": 0, "skipped": 0}
    assert conn.execute("select count(*) from stg_activity").fetchone()[0] == 1
    assert conn.execute("select hrv_ms from stg_hrv order by day").fetchall() == [(60,), (58,)]


def test_old_days_are_not_fetched_twice(conn):
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))
    caller = FakeCaller(two_days())
    report = run_sync(conn, caller, today=date(2026, 6, 1))

    # only the activity listing is asked again; days and the activity are final
    assert [tool for tool, _ in caller.calls] == ["get_activities_by_date"]
    assert report.counts["skipped"] == 6


def test_recent_days_are_refetched(conn):
    run_sync(conn, FakeCaller(two_days()), today=D2)
    answers = two_days()
    answers[("get_sleep_summary", D2.isoformat())] = sleep(7.8, 49)  # Garmin finished the night
    report = run_sync(conn, FakeCaller(answers), today=D2)

    assert report.counts["stored"] == 1
    assert report.counts["unchanged"] == 6
    row = conn.execute("select sleep_seconds from stg_sleep where day = %s", (D2,)).fetchone()
    assert row == (round(7.8 * 3600),)


def test_empty_and_error_answers_are_logged_not_stored(conn):
    answers = two_days()
    del answers[("get_hrv_data", D1.isoformat())]  # "No data found for ..."
    answers[("get_hrv_data", D2.isoformat())] = "Error retrieving HRV data: timeout"
    answers[("get_sleep_summary", D2.isoformat())] = ToolError("server failure")
    report = run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))

    assert report.counts["empty"] == 1
    assert report.counts["error"] == 2
    assert log_statuses(conn) == {"stored": 4, "empty": 1, "error": 2}
    assert conn.execute("select count(*) from stg_hrv").fetchone()[0] == 0


def test_activity_listing_is_paginated(conn):
    answers = two_days()
    answers[("get_activities_by_date", 0)] = listing(
        [{"id": 11, "start_time": f"{D1} 07:00:00"}], has_more=True
    )
    answers[("get_activities_by_date", 1)] = listing(
        [{"id": 12, "start_time": f"{D2} 18:00:00"}], page=1
    )
    answers[("get_activity", 12)] = activity(12, D2, load=40)
    caller = FakeCaller(answers)
    run_sync(conn, caller, today=date(2026, 6, 1))

    pages = [a["page"] for tool, a in caller.calls if tool == "get_activities_by_date"]
    assert pages == [0, 1]
    assert conn.execute("select count(*) from stg_activity").fetchone()[0] == 2


def test_latest_payload_wins_even_when_it_reverts(conn):
    first, second = two_days(), two_days()
    second[("get_hrv_data", D1.isoformat())] = hrv(D1, 61)
    for answers in (first, second, first):  # 60 -> 61 -> 60
        run_sync(conn, FakeCaller(answers), today=D1)

    row = conn.execute("select hrv_ms from stg_hrv where day = %s", (D1,)).fetchone()
    assert row == (60,)


def test_mcp_client_refuses_write_tools():
    caller = McpToolCaller("http://127.0.0.1:1/mcp", "unused")
    with pytest.raises(PermissionError):
        asyncio.run(caller.call("schedule_workout", {"workout_id": 1, "date": "2026-03-02"}))
