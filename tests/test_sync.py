import asyncio
import json
from datetime import date
from types import SimpleNamespace

import pytest

from lifter.garmin import McpToolCaller, ToolError
from lifter.sync import MAX_CONSECUTIVE_ERRORS, SyncAborted, parse_response, sync_range
from synthetic import (
    activity,
    daily_stats,
    hr_zones,
    hrv,
    sleep,
    training_readiness,
    training_status,
)

D1, D2 = date(2026, 3, 2), date(2026, 3, 3)

SNAPSHOT_TOOLS = {"get_scheduled_workouts"}


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
        elif "page" in arguments:
            key = arguments["page"]
        else:
            key = "snapshot"  # Garmin calendar
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
        **{("get_stats", d.isoformat()): daily_stats(d) for d in (D1, D2)},
        **{
            ("get_training_readiness", d.isoformat()): training_readiness(d, ("07:00", 70, "HIGH"))
            for d in (D1, D2)
        },
        **{("get_training_status", d.isoformat()): training_status(d) for d in (D1, D2)},
    }


def run_sync(conn, caller, today):
    return asyncio.run(sync_range(caller, conn, D1, D2, today=today))


def log_statuses(conn):
    return dict(conn.execute("select status, count(*) from sync_log group by status").fetchall())


def test_first_sync_stores_every_answer(conn):
    report = run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))

    assert report.counts == {"stored": 14, "unchanged": 0, "empty": 0, "error": 0, "skipped": 0}
    assert conn.execute("select count(*) from stg_activity").fetchone()[0] == 1
    assert conn.execute("select hrv_ms from stg_hrv order by day").fetchall() == [(60,), (58,)]


def test_old_days_are_not_fetched_twice(conn):
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))
    caller = FakeCaller(two_days())
    report = run_sync(conn, caller, today=date(2026, 6, 1))

    # only the listing and the snapshots are asked again; days and the activity are final
    assert [tool for tool, _ in caller.calls if tool not in SNAPSHOT_TOOLS] == [
        "get_activities_by_date"
    ]
    assert report.counts["skipped"] == 12  # 2 days x 5 daily tools + 2 activity tools


def test_recent_days_are_refetched(conn):
    run_sync(conn, FakeCaller(two_days()), today=D2)
    answers = two_days()
    answers[("get_sleep_summary", D2.isoformat())] = sleep(7.8, 49)  # Garmin finished the night
    report = run_sync(conn, FakeCaller(answers), today=D2)

    assert report.counts["stored"] == 1
    assert report.counts["unchanged"] == 13  # 12 + the unchanged snapshot
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
    assert log_statuses(conn) == {"stored": 11, "empty": 1, "error": 2}
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


NOT_FOUND = (
    "Error retrieving activity: Garmin Connect request failed: HTTP error: "
    "API Error 404 - HTTP 404 Not Found."
)


def test_activity_confirmed_deleted_is_tombstoned_then_restored(conn):
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))
    answers = two_days()
    answers[("get_activities_by_date", 0)] = listing([])  # no longer listed
    answers[("get_activity", 11)] = NOT_FOUND  # and Garmin confirms it is gone
    run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))

    assert conn.execute("select activity_id from activity_tombstone").fetchall() == [(11,)]
    assert conn.execute("select count(*) from stg_activity").fetchone()[0] == 0

    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))  # listed again: restored
    assert conn.execute("select count(*) from activity_tombstone").fetchone()[0] == 0
    assert conn.execute("select count(*) from stg_activity").fetchone()[0] == 1


def test_activity_missing_from_listing_but_found_is_kept(conn):
    # A paging shift or a date boundary can drop an activity from a listing: never delete
    # on that alone.
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))
    answers = two_days()
    answers[("get_activities_by_date", 0)] = listing([])
    caller = FakeCaller(answers)
    run_sync(conn, caller, today=date(2026, 6, 1))

    assert ("get_activity", {"activity_id": 11}) in caller.calls
    assert conn.execute("select count(*) from activity_tombstone").fetchone()[0] == 0
    assert conn.execute("select count(*) from stg_activity").fetchone()[0] == 1


def test_listed_activity_without_details_deleted_later_stops_counting(conn):
    answers = two_days()
    answers[("get_activity", 11)] = "Error retrieving activity: timeout"
    run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))
    answers = two_days()
    answers[("get_activities_by_date", 0)] = listing([])
    answers[("get_activity", 11)] = NOT_FOUND
    run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))

    row = conn.execute(
        "select coalesce(sum(sessions_missing_details), 0) from daily_load"
    ).fetchone()
    assert row == (0,)


def test_sync_stops_after_consecutive_failures(conn):
    class DeadCaller(FakeCaller):
        async def call(self, tool, arguments):
            self.calls.append((tool, arguments))
            raise ToolError("ConnectError: connection refused")

    caller = DeadCaller({})
    with pytest.raises(SyncAborted):
        asyncio.run(sync_range(caller, conn, D1, date(2026, 3, 31), today=date(2026, 6, 1)))
    assert len(caller.calls) == MAX_CONSECUTIVE_ERRORS


def test_incomplete_listing_tombstones_nothing(conn):
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))
    answers = two_days()
    answers[("get_activities_by_date", 0)] = "Error retrieving activities by date: timeout"
    run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))

    assert conn.execute("select count(*) from activity_tombstone").fetchone()[0] == 0


def test_activity_without_details_is_counted_as_missing(conn):
    answers = two_days()
    answers[("get_activity", 11)] = "Error retrieving activity: timeout"
    run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))

    row = conn.execute(
        "select sessions, sessions_missing_details from daily_load where day = %s", (D1,)
    ).fetchone()
    assert row == (0, 1)


def test_nan_in_a_payload_is_stored_as_null(conn):
    answers = two_days()
    answers[("get_hrv_data", D1.isoformat())] = (
        '{"date": "2026-03-02", "last_night_avg_hrv_ms": NaN}'
    )
    report = run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))

    assert report.counts["error"] == 0
    row = conn.execute("select hrv_ms from stg_hrv where day = %s", (D1,)).fetchone()
    assert row == (None,)


def test_refresh_refetches_final_days(conn):
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))
    caller = FakeCaller(two_days())
    asyncio.run(sync_range(caller, conn, D1, D2, today=date(2026, 6, 1), refresh=True))

    assert len(caller.calls) == 14  # listing, snapshot, 2 activity tools, 2 x 5 daily


class FakeSession:
    def __init__(self, result=None, exc=None):
        self.result, self.exc = result, exc

    async def call_tool(self, tool, arguments):
        if self.exc:
            raise self.exc
        return self.result


def connected_caller(session):
    caller = McpToolCaller("http://127.0.0.1:1/mcp", "unused")
    caller._session = session
    return caller


def test_mcp_client_joins_text_content():
    result = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text='{"a": '),
            SimpleNamespace(type="text", text="1}"),
        ],
        is_error=False,
    )
    assert asyncio.run(connected_caller(FakeSession(result)).call("get_hrv_data", {})) == '{"a": 1}'


def test_mcp_client_turns_failures_into_tool_errors():
    error_result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="boom")], is_error=True
    )
    with pytest.raises(ToolError, match="boom"):
        asyncio.run(connected_caller(FakeSession(error_result)).call("get_hrv_data", {}))
    with pytest.raises(ToolError, match="ConnectionError"):
        asyncio.run(
            connected_caller(FakeSession(exc=ConnectionError("reset"))).call("get_hrv_data", {})
        )


def test_transport_failure_is_logged_and_the_sync_goes_on(conn):
    class FlakyCaller(FakeCaller):
        async def call(self, tool, arguments):
            if tool == "get_sleep_summary" and arguments["date"] == D1.isoformat():
                raise ToolError("ReadTimeout: timed out")
            return await super().call(tool, arguments)

    report = run_sync(conn, FlakyCaller(two_days()), today=date(2026, 6, 1))

    assert report.counts["error"] == 1
    assert report.counts["stored"] == 13


@pytest.mark.parametrize(
    "text",
    [
        "Error retrieving activity: Read timed out",
        "Error retrieving activity: HTTP error: API Error 429 - Too Many Requests",
        "Error retrieving activity: HTTP 503 Service Unavailable (request 4040404)",
    ],
)
def test_only_a_garmin_404_counts_as_not_found(text):
    assert parse_response(text) == ("error", None)


def test_days_garmin_answered_with_no_data_are_not_asked_again(conn):
    answers = two_days()
    del answers[("get_training_status", D1.isoformat())]  # "No data found for ..."
    # answered long after the day, so the empty answer is final
    run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))
    caller = FakeCaller(answers)
    run_sync(conn, caller, today=date(2026, 6, 1))

    assert ("get_training_status", {"date": D1.isoformat()}) not in caller.calls


def test_recent_empty_days_are_asked_again(conn):
    answers = two_days()
    del answers[("get_training_status", D2.isoformat())]
    run_sync(conn, FakeCaller(answers), today=D2)
    caller = FakeCaller(answers)
    run_sync(conn, caller, today=D2)

    assert ("get_training_status", {"date": D2.isoformat()}) in caller.calls


def test_days_empty_while_recent_are_asked_again_later(conn):
    # The watch was offline: on D2 (recent), Garmin had nothing for D1 yet.
    answers = two_days()
    del answers[("get_training_status", D1.isoformat())]
    run_sync(conn, FakeCaller(answers), today=D2)
    caller = FakeCaller(two_days())  # the watch has uploaded since
    run_sync(conn, caller, today=date(2026, 6, 1))

    assert ("get_training_status", {"date": D1.isoformat()}) in caller.calls


def test_an_unreadable_activity_is_skipped_and_deletes_nothing(conn):
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))  # activity 11 is known
    answers = two_days()
    answers[("get_activities_by_date", 0)] = listing(
        [{"start_time": f"{D1} 07:00:00"}, {"id": 12, "start_time": "not a date"}]
    )
    answers[("get_activity", 12)] = activity(12, D2, load=40)
    report = run_sync(conn, FakeCaller(answers), today=date(2026, 6, 1))

    assert report.counts["error"] >= 1
    assert conn.execute("select count(*) from activity_tombstone").fetchone() == (0,)
    assert conn.execute("select count(*) from stg_activity where activity_id = 12").fetchone() == (
        1,
    )


def test_sync_reports_an_unreachable_mcp_server_without_a_traceback(monkeypatch, capsys):
    from lifter.cli import main

    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("GARMIN_MCP_URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setenv("GARMIN_MCP_TOKEN", "token")
    assert main(["sync", "--days", "1"]) == 3
    out = capsys.readouterr().out
    assert "cannot reach the Garmin MCP server at 127.0.0.1:1" in out and "token" not in out


def test_sync_reports_an_unreachable_database_without_a_traceback(monkeypatch, capsys):
    from lifter.cli import main

    class Reachable:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

    monkeypatch.setattr("lifter.garmin.McpToolCaller", Reachable)
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("GARMIN_MCP_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://lifter@127.0.0.1:1/lifter?connect_timeout=2")
    assert main(["sync", "--days", "1"]) == 3
    assert "database: OperationalError" in capsys.readouterr().out


def test_a_listing_that_does_not_move_forward_stops_and_deletes_nothing(conn):
    run_sync(conn, FakeCaller(two_days()), today=date(2026, 6, 1))  # activity 11 is known
    answers = two_days()
    stuck = listing([], has_more=True)
    stuck["next_page"] = 0  # the same page again: a buggy server would loop for ever
    answers[("get_activities_by_date", 0)] = stuck
    caller = FakeCaller(answers)
    report = run_sync(conn, caller, today=date(2026, 6, 1))

    pages = [a["page"] for tool, a in caller.calls if tool == "get_activities_by_date"]
    assert pages == [0]
    assert report.counts["error"] == 1
    assert conn.execute("select count(*) from activity_tombstone").fetchone() == (0,)


def test_the_listing_stops_at_the_page_cap(conn, monkeypatch):
    monkeypatch.setattr("lifter.sync.MAX_PAGES", 3)
    answers = two_days()
    for page in range(5):
        answers[("get_activities_by_date", page)] = listing([], page=page, has_more=True)
    caller = FakeCaller(answers)
    report = run_sync(conn, caller, today=date(2026, 6, 1))

    pages = [a["page"] for tool, a in caller.calls if tool == "get_activities_by_date"]
    assert pages == [0, 1, 2]
    assert report.counts["error"] == 1


def test_a_page_number_sent_as_text_is_followed(conn):
    answers = two_days()
    first = listing([{"id": 11, "start_time": f"{D1} 07:00:00"}], has_more=True)
    first["next_page"] = "1"
    answers[("get_activities_by_date", 0)] = first
    answers[("get_activities_by_date", 1)] = listing([], page=1)
    caller = FakeCaller(answers)
    report = run_sync(conn, caller, today=date(2026, 6, 1))

    pages = [a["page"] for tool, a in caller.calls if tool == "get_activities_by_date"]
    assert pages == [0, 1]
    assert report.counts["error"] == 0
