"""The read-only API (lifter.api), on the synthetic program and synthetic Garmin data."""

from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from lifter import domain
from lifter.api.app import create_app, read_only_url
from lifter.db import connect
from lifter.program import load_program, read_program
from lifter.sync import store_payload
from synthetic import activity, load_days

EXAMPLE = Path(__file__).parents[2] / "examples" / "program.yaml"
APP_ORIGIN = "http://localhost:3000"


@pytest.fixture
def api(conn, database_url):
    return TestClient(create_app(database_url, [APP_ORIGIN]), base_url="http://127.0.0.1:8000")


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


def session_id(conn, title: str) -> int:
    return conn.execute("select id from planned_session where title = %s", (title,)).fetchone()[0]


def test_the_program_shows_each_block_with_its_strength_sessions(api, program):
    (cycle,) = api.get("/program").json()["cycles"]

    assert cycle["name"] == "Synthetic cycle 1"
    blocks = [
        (b["position"], b["kind"], b["strength_sessions_done"], b["target_strength_sessions"])
        for b in cycle["blocks"]
    ]
    assert blocks == [
        (1, "accumulation", 2, 12),
        (2, "transmutation", 0, 11),
        (3, "realisation", 0, 9),
    ]
    assert cycle["blocks"][0]["intent"].startswith("Volume")


def test_a_block_shows_its_weeks_and_each_exercise_week_by_week(api, program):
    block_id = api.get("/program").json()["cycles"][0]["blocks"][0]["id"]

    body = api.get(f"/blocks/{block_id}").json()

    assert body["block"]["kind"] == "accumulation"
    assert [w["number"] for w in body["weeks"]] == [1, 2]
    bench = {
        (p["week_number"], p["origin"]): p
        for p in body["progress"]
        if p["exercise"] == "Bench press"
    }
    # week 1: planned 3x10 @ 50 RIR 3, done 3x10 @ 52.5 RIR 2
    assert (bench[1, "planned"]["reps"], bench[1, "planned"]["top_load_kg"]) == (30, 50)
    assert (bench[1, "done"]["top_load_kg"], bench[1, "done"]["avg_rir"]) == (52.5, 2)
    assert not any(p["exercise"] == "Row" for p in body["progress"])  # warm-up left out
    assert api.get("/blocks/999999").status_code == 404


def test_weeks_list_the_review_of_each_week(api, program):
    weeks = api.get("/weeks").json()

    assert [w["number"] for w in weeks] == [1, 2]
    first = weeks[0]
    assert (first["sessions"], first["done"], first["missed"]) == (4, 2, 2)
    assert first["strength_sessions_done"] == 2
    assert first["patterns_done"] == ["legs", "olympic", "push"]
    assert first["intent"]["metcon"] == "Long, sustainable, continuous."
    assert weeks[1]["patterns_done"] == []  # a week without logs: an empty list, not null


def test_a_week_lists_its_sessions_with_status_and_garmin_line(api, conn, program):
    store_payload(
        conn,
        "get_activity",
        "1",
        {},
        activity(1, date(2026, 3, 2), load=80, activity_type="hiit"),
    )
    week_id = api.get("/weeks").json()[0]["id"]

    body = api.get(f"/weeks/{week_id}").json()

    assert body["week"]["number"] == 1
    assert body["block_intent"].startswith("Volume")
    sessions = [(s["day"], s["status"], s["moved_from"]) for s in body["sessions"]]
    assert sessions == [
        ("2026-03-02", "done", None),
        ("2026-03-04", "missed", None),
        ("2026-03-06", "missed", None),
        ("2026-03-07", "done", "2026-03-05"),
    ]
    garmin = body["sessions"][0]["garmin"]
    assert garmin["activities"] == 1 and garmin["duration_minutes"] == 60
    assert body["sessions"][1]["garmin"] is None


def test_a_session_shows_planned_and_done_side_by_side(api, conn, program):
    body = api.get(f"/sessions/{session_id(conn, 'Weightlifting + Push + Metcon')}").json()

    assert body["notes"] == "Bench felt easy, metcon hard."
    assert [p["kind"] for p in body["parts"]] == ["warmup", "weightlifting", "strength", "metcon"]
    strength = body["parts"][2]
    assert [line["exercise"] for line in strength["planned"]] == ["Bench press", "Dips"]
    bench_planned, bench_done = strength["planned"][0], strength["done"][0]
    assert (bench_planned["load_kg"], bench_planned["rir"]) == (50, 3)
    assert (bench_done["load_kg"], bench_done["rir"]) == (52.5, 2)  # numbers, not strings
    metcon = body["parts"][3]
    assert (metcon["format"], metcon["target_rounds"], metcon["result_rounds"]) == (
        "amrap",
        5,
        5.5,
    )
    assert metcon["done"] == []
    assert body["garmin"] is None


def test_a_moved_session_shows_where_it_came_from_and_the_deviation(api, conn, program):
    body = api.get(f"/sessions/{session_id(conn, 'Legs + Metcon')}").json()

    assert body["moved_from"] == "2026-03-05"
    assert body["deviation"] == "Moved from Thursday; leg curl not done."
    assert [line["exercise"] for line in body["parts"][0]["done"]] == ["Leg press"]


def test_unknown_ids_are_not_found(api, program):
    assert api.get("/sessions/999999").status_code == 404
    assert api.get("/weeks/999999").status_code == 404


def test_the_calendar_shows_sessions_and_unplanned_activities(api, conn, program):
    store_payload(
        conn, "get_activity", "2", {}, activity(2, date(2026, 3, 3), load=40, activity_type="hiit")
    )

    items = api.get("/calendar", params={"start": "2026-03-02", "end": "2026-03-03"}).json()

    assert [(i["day"], i["kind"], i["source"], i["status"]) for i in items] == [
        ("2026-03-02", "session", "lifter", "done"),
        ("2026-03-03", "activity", "garmin", "done (unplanned)"),
    ]
    assert items[0]["session_id"] == session_id(conn, "Weightlifting + Push + Metcon")
    assert items[1]["activity_id"] == 2


def test_the_calendar_refuses_a_reversed_or_too_long_range(api):
    reversed_range = {"start": "2026-03-10", "end": "2026-03-01"}
    assert api.get("/calendar", params=reversed_range).status_code == 422
    too_long = {"start": "2026-01-01", "end": "2027-01-02"}  # 367 days
    assert api.get("/calendar", params=too_long).status_code == 422


def test_the_current_week_is_the_one_containing_today(api, conn, program):
    assert api.get("/weeks/current").status_code == 404  # the synthetic weeks are past

    monday = date.today() - timedelta(days=date.today().weekday())
    conn.execute(
        "insert into training_week (cycle_id, number, start_date, phase)"
        " select id, 3, %s, 'volume' from cycle",
        (monday,),
    )
    body = api.get("/weeks/current").json()
    assert body["week"]["number"] == 3
    assert body["sessions"] == [] and body["block_intent"] is None

    # a session outside any week, on a day of this one, belongs to it on screen
    domain.create_session(conn, domain.SessionIn(day=monday + timedelta(days=2), title="Extra"))
    assert [s["title"] for s in api.get("/weeks/current").json()["sessions"]] == ["Extra"]


def test_health_returns_the_last_days_oldest_first_with_alerts(api, conn):
    first_day = date(2026, 3, 1)
    days = [{"load": 50, "hrv": 60, "rhr": 50, "sleep_hours": 7.5} for _ in range(30)]
    days[-1]["sleep_hours"] = 5  # a short night on the last day
    load_days(conn, first_day, days)

    body = api.get("/health", params={"days": 7}).json()

    last_day = (first_day + timedelta(days=29)).isoformat()
    assert len(body["metrics"]) == 7
    assert body["metrics"][-1]["day"] == last_day
    assert body["metrics"][-1]["acwr"] == 1.0
    assert body["recovery"][-1]["sleep_hours"] == 5
    assert [(a["day"], a["alert"]) for a in body["alerts"]] == [(last_day, "short_sleep")]


def test_health_without_data_is_empty_and_days_are_bounded(api):
    assert api.get("/health").json() == {"metrics": [], "recovery": [], "alerts": []}
    assert api.get("/health", params={"days": 0}).status_code == 422
    assert api.get("/health", params={"days": 91}).status_code == 422


def test_goals_come_with_their_milestones_in_order(api, program):
    goals = {g["title"]: g for g in api.get("/goals").json()}

    bench = goals["Bench press 80 kg"]
    assert bench["exercise"] == "Bench press"
    assert [(m["day"], m["value"]) for m in bench["milestones"]] == [
        ("2026-03-29", 72.5),
        ("2026-04-26", 77.5),
    ]
    assert len(goals) == 3


def test_active_goals_come_first(api, conn):
    for title, status in (("A", "abandoned"), ("B", "achieved"), ("C", "active")):
        conn.execute(
            "insert into goal (title, status, target_text) values (%s, %s, 'x')", (title, status)
        )

    assert [g["status"] for g in api.get("/goals").json()] == ["active", "abandoned", "achieved"]


def test_the_profile_is_empty_until_the_athlete_is_described(api):
    assert api.get("/profile").json() == {"athlete": None, "health_issues": [], "rules": []}


def test_the_profile_shows_the_athlete_their_issues_active_first_and_their_rules(api, conn):
    # A synthetic athlete: real values only ever live in the database.
    born = date.today().replace(year=date.today().year - 30) - timedelta(days=1)
    conn.execute(
        "insert into athlete (first_name, birth_date, sex, height_cm, weight_kg, level,"
        " training_places) values ('Sam', %s, 'female', 168, 64.5, 'intermediate',"
        " array['Gym A', 'Club B'])",
        (born,),
    )
    conn.execute(
        "insert into health_issue (body_part, kind, description, status, resolved_on, since)"
        " values ('ankle', 'injury', 'Sprain', 'resolved', '2026-01-20', '2026-01-02'),"
        " ('shoulder', 'limitation', 'Limited external rotation', 'monitoring', null, null),"
        " ('wrist', 'pain', 'Pain in the front rack', 'active', null, '2026-03-01')"
    )
    conn.execute(
        "insert into athlete_rule (code, text, active) values"
        " (null, 'Machines only for the legs', true), ('stop_rule', 'Stop above 3/10', true),"
        " ('old', 'An inactive rule', false)"
    )

    body = api.get("/profile").json()

    assert body["athlete"]["age"] == 30
    assert body["athlete"]["weight_kg"] == 64.5
    assert body["athlete"]["training_places"] == ["Gym A", "Club B"]
    assert [(i["body_part"], i["status"]) for i in body["health_issues"]] == [
        ("wrist", "active"),
        ("shoulder", "monitoring"),
        ("ankle", "resolved"),
    ]
    assert [r["text"] for r in body["rules"]] == ["Stop above 3/10", "Machines only for the legs"]


def test_a_resolved_issue_needs_its_date(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into health_issue (body_part, kind, description, status)"
            " values ('knee', 'pain', 'x', 'resolved')"
        )


def test_bests_list_the_best_load_per_exercise_and_reps(api, program):
    bests = api.get("/bests").json()

    assert {
        "exercise": "Bench press",
        "category": "strength",
        "pattern": "push",
        "reps": 1,
        "best_load_kg": 70,
        "day": "2026-02-23",
    } in bests


def test_history_gives_the_heaviest_set_per_day_of_an_exercise(api, program):
    points = api.get("/history", params={"exercise": ["bench PRESS", "Unknown"]}).json()

    assert [(p["day"], p["top_load_kg"], p["reps"]) for p in points] == [
        ("2026-02-23", 70, 1),  # history session: a single
        ("2026-03-02", 52.5, 10),
    ]
    assert api.get("/history").status_code == 422  # at least one name


def test_proposals_are_filtered_by_status(api, conn):
    pid = domain.propose(
        conn,
        "create_goal",
        domain.GoalIn(title="Strict press 50 kg", target_value=50, unit="kg").model_dump(
            mode="json"
        ),
        rationale="Synthetic rationale.",
        author="week_planner",
    )

    (pending,) = api.get("/proposals").json()
    assert (pending["id"], pending["status"], pending["kind"]) == (pid, "pending", "create_goal")
    assert pending["payload"]["title"] == "Strict press 50 kg"
    assert api.get("/proposals", params={"status": "applied"}).json() == []
    assert api.get("/proposals", params={"status": "whatever"}).status_code == 422


def test_the_api_connection_cannot_write(database_url):
    with connect(read_only_url(database_url)) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("insert into exercise (name, category) values ('X', 'other')")


def test_only_the_app_origin_may_call_the_api_from_a_browser(api):
    allowed = api.get("/bests", headers={"Origin": APP_ORIGIN})
    assert allowed.headers.get("access-control-allow-origin") == APP_ORIGIN

    other = api.get("/bests", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in other.headers
    assert api.post("/bests").status_code == 405


def test_a_rebound_host_name_is_refused(api):
    # DNS rebinding: a page on evil.example rebinds its name to 127.0.0.1; the Host stays its own
    response = api.get("/health", headers={"Host": "evil.example:8000"})
    assert response.status_code == 400
    assert api.get("/health", headers={"Host": "localhost:8000"}).status_code == 200
