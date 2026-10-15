"""Sessions, goals, plans, feedback and agent proposals (lifter.domain), and the calendar."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from lifter import domain
from lifter.sync import store_payload
from synthetic import activity

PAST = date(2026, 3, 2)  # a Monday, long gone: no "planned" status left


def session(day=PAST, sport="cycling", **extra) -> domain.SessionIn:
    return domain.SessionIn(day=day, sport=sport, title="Endurance ride", **extra)


def calendar(conn, day):
    return conn.execute(
        "select kind, source, title, sport, status from calendar where day = %s order by kind",
        (day,),
    ).fetchall()


def test_a_planned_session_is_done_when_an_activity_of_its_family_happens(conn):
    domain.create_session(conn, session(sport="cycling"))
    store_payload(
        conn, "get_activity", "1", {}, activity(1, PAST, load=80, activity_type="road_biking")
    )

    assert calendar(conn, PAST) == [("session", "lifter", "Endurance ride", "cycling", "done")]


def test_a_past_session_without_activity_is_missed(conn):
    domain.create_session(conn, session())
    assert calendar(conn, PAST)[0][-1] == "missed"


def test_a_future_session_is_planned(conn):
    future = date.today() + timedelta(days=3)
    domain.create_session(conn, session(day=future))
    assert calendar(conn, future)[0][-1] == "planned"


def test_an_activity_of_another_sport_shows_as_unplanned(conn):
    domain.create_session(conn, session(sport="running"))
    store_payload(
        conn, "get_activity", "1", {}, activity(1, PAST, load=80, activity_type="cycling")
    )

    rows = calendar(conn, PAST)
    assert ("activity", "garmin", "Synthetic cycling", "cycling", "done (unplanned)") in rows
    assert ("session", "lifter", "Endurance ride", "running", "missed") in rows


def test_garmin_calendar_items_appear(conn):
    store_payload(
        conn,
        "get_scheduled_workouts",
        "window",
        {},
        {
            "scheduled_workouts": [
                {
                    "date": "2026-03-02",
                    "scheduled_workout_id": 9,
                    "name": "Garmin intervals",
                    "sport": "CYCLING",
                    "completed": False,
                }
            ]
        },
    )
    store_payload(
        conn,
        "get_calendar_events",
        "window",
        {},
        {"events": [{"date": "2026-03-02", "title": "Gran fondo", "is_race": True}]},
    )

    rows = calendar(conn, PAST)
    assert ("event", "garmin", "Gran fondo", None, "race") in rows
    assert ("session", "garmin", "Garmin intervals", "cycling", "missed") in rows


def test_an_empty_garmin_snapshot_clears_the_garmin_items(conn):
    workouts = {
        "scheduled_workouts": [
            {
                "date": "2026-03-02",
                "scheduled_workout_id": 9,
                "name": "Old",
                "sport": "cycling",
                "completed": False,
            }
        ]
    }
    store_payload(conn, "get_scheduled_workouts", "window", {}, workouts)
    store_payload(conn, "get_scheduled_workouts", "window", {}, {"empty": True})

    assert calendar(conn, PAST) == []


def test_moving_and_cancelling_a_session(conn):
    sid = domain.create_session(conn, session())
    domain.move_session(conn, domain.MoveSession(session_id=sid, new_day=PAST + timedelta(1)))
    row = conn.execute("select day, moved_from from planned_session where id = %s", (sid,))
    assert row.fetchone() == (PAST + timedelta(1), PAST)

    domain.cancel_session(conn, domain.CancelSession(session_id=sid))
    assert calendar(conn, PAST + timedelta(1))[0][-1] == "cancelled"
    with pytest.raises(domain.DomainError):
        domain.move_session(conn, domain.MoveSession(session_id=sid, new_day=PAST))


def test_feedback_validates_its_scales(conn):
    domain.add_feedback(conn, domain.FeedbackIn(day=PAST, rpe=7, fatigue=3, pain=0))
    with pytest.raises(ValidationError):
        domain.FeedbackIn(day=PAST, rpe=11)


def test_a_proposal_changes_nothing_until_approved_and_applied(conn):
    pid = domain.propose(
        conn,
        "create_session",
        {"day": "2026-03-03", "sport": "running", "title": "Easy run", "intensity": "easy"},
        rationale="Recovery is low: an easy run instead of intervals.",
        author="week_planner",
    )
    assert conn.execute("select count(*) from planned_session").fetchone() == (0,)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)  # still pending

    domain.decide(conn, pid, approve=True)
    result = domain.apply(conn, pid)

    assert conn.execute("select title from planned_session").fetchall() == [("Easy run",)]
    status = conn.execute("select status, result from proposal where id = %s", (pid,)).fetchone()
    assert status == ("applied", result)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)  # applied once only


def test_a_rejected_proposal_is_never_applied(conn):
    pid = domain.propose(
        conn,
        "create_goal",
        {"title": "Gran fondo", "target_date": "2026-06-01"},
        rationale="Goal mentioned in chat.",
        author="coach",
    )
    domain.decide(conn, pid, approve=False)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)
    assert conn.execute("select count(*) from goal").fetchone() == (0,)


def test_a_proposal_that_fails_is_recorded_as_failed(conn):
    pid = domain.propose(
        conn,
        "move_session",
        {"session_id": 999, "new_day": "2026-03-05"},
        rationale="Move the long ride.",
        author="week_planner",
    )
    domain.decide(conn, pid, approve=True)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)
    status = conn.execute("select status from proposal where id = %s", (pid,)).fetchone()
    assert status == ("failed",)


def test_proposals_are_validated_before_being_stored(conn):
    with pytest.raises(ValidationError):
        domain.propose(conn, "create_session", {"day": "2026-03-03"}, "No sport.", "coach")
    with pytest.raises(ValidationError):
        domain.propose(
            conn,
            "move_session",
            {"session_id": 1, "new_day": "2026-03-03", "sql": "drop"},
            "Extra field.",
            "coach",
        )
    with pytest.raises(domain.DomainError):
        domain.propose(conn, "delete_everything", {}, "Unknown kind.", "coach")
    with pytest.raises(domain.DomainError):
        domain.propose(conn, "cancel_session", {"session_id": 1}, "  ", "coach")
    assert conn.execute("select count(*) from proposal").fetchone() == (0,)


def test_a_cancelled_session_leaves_the_activity_unplanned(conn):
    sid = domain.create_session(conn, session())
    domain.cancel_session(conn, domain.CancelSession(session_id=sid))
    store_payload(
        conn, "get_activity", "1", {}, activity(1, PAST, load=80, activity_type="cycling")
    )

    rows = calendar(conn, PAST)
    assert ("session", "lifter", "Endurance ride", "cycling", "cancelled") in rows
    assert ("activity", "garmin", "Synthetic cycling", "cycling", "done (unplanned)") in rows


def test_one_activity_completes_only_one_session(conn):
    domain.create_session(conn, session())
    domain.create_session(conn, session())  # a second ride planned the same day
    store_payload(
        conn, "get_activity", "1", {}, activity(1, PAST, load=80, activity_type="cycling")
    )

    statuses = sorted(r[-1] for r in calendar(conn, PAST))
    assert statuses == ["done", "missed"]
