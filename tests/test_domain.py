"""CrossFit sessions in parts, exercises, goals, feedback and agent proposals (lifter.domain),
and the views that read them: session status, Garmin line, calendar, bests."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from lifter import domain
from lifter.sync import store_payload
from synthetic import activity, hr_zones

PAST = date(2026, 3, 2)  # a Monday, long gone: no "planned" status left


@pytest.fixture
def bank(conn):
    for name, category, pattern in (
        ("Bench press", "strength", "push"),
        ("Power clean", "weightlifting", "olympic"),
        ("Ski erg", "monostructural", "engine"),
        ("Burpee", "gymnastics", "full_body"),
        ("Leg press", "strength", "legs"),
    ):
        domain.upsert_exercise(
            conn, domain.ExerciseIn(name=name, category=category, pattern=pattern)
        )


def push_session(day=PAST, **extra) -> domain.SessionIn:
    return domain.SessionIn(
        day=day,
        title="Weightlifting + Push + Metcon",
        parts=[
            domain.PartIn(
                kind="weightlifting",
                planned=[domain.LineIn(exercise="Power clean", sets=5, quantity=3, load_kg=50)],
            ),
            domain.PartIn(
                kind="strength",
                planned=[
                    domain.LineIn(exercise="Bench press", sets=4, quantity=8, load_kg=60, rir=2)
                ],
            ),
            domain.PartIn(
                kind="metcon",
                format="for_time",
                rounds=3,
                target_seconds=600,
                planned=[
                    domain.LineIn(exercise="Ski erg", quantity=15, unit="cal"),
                    domain.LineIn(exercise="Burpee", quantity=10),
                ],
            ),
        ],
        **extra,
    )


def status(conn, session_id):
    return conn.execute(
        "select status from planned_session_status where planned_session_id = %s", (session_id,)
    ).fetchone()[0]


def calendar(conn, day):
    return conn.execute(
        "select kind, source, title, detail, status from calendar where day = %s"
        " order by kind, title",
        (day,),
    ).fetchall()


def test_a_session_is_stored_with_its_parts_in_order(conn, bank):
    sid = domain.create_session(conn, push_session())

    parts = conn.execute(
        "select position, kind, format, target_seconds from session_part"
        " where session_id = %s order by position",
        (sid,),
    ).fetchall()
    assert parts == [
        (1, "weightlifting", None, None),
        (2, "strength", None, None),
        (3, "metcon", "for_time", 600),
    ]
    lines = conn.execute(
        "select part_kind, origin, exercise, sets, quantity, unit, load_kg, rir"
        " from session_line where session_id = %s order by part_position, position",
        (sid,),
    ).fetchall()
    assert lines[1] == ("strength", "planned", "Bench press", 4, 8, "reps", 60, 2)
    assert lines[2][2:6] == ("Ski erg", None, 15, "cal")


def test_an_unknown_exercise_refuses_the_whole_session(conn, bank):
    session = push_session()
    session.parts[1].planned.append(domain.LineIn(exercise="Bench pres", sets=3, quantity=8))

    with pytest.raises(domain.DomainError, match="Bench pres"):
        domain.create_session(conn, session)
    assert conn.execute("select count(*) from planned_session").fetchone() == (0,)


def test_a_load_range_must_be_ordered():
    with pytest.raises(ValidationError):
        domain.LineIn(exercise="Bench press", load_kg=60, load_kg_max=55)
    with pytest.raises(ValidationError):
        domain.LineIn(exercise="Bench press", load_kg_max=55)


def test_a_session_with_a_garmin_activity_is_done_with_its_garmin_line(conn, bank):
    sid = domain.create_session(conn, push_session())
    store_payload(
        conn, "get_activity", "1", {}, activity(1, PAST, load=80, minutes=60, activity_type="hiit")
    )
    store_payload(
        conn, "get_activity_hr_in_timezones", "1", {}, hr_zones([600, 1200, 900, 480, 420])
    )

    assert status(conn, sid) == "done"
    line = conn.execute(
        "select activities, duration_minutes, avg_hr_bpm, z4_z5_minutes from session_garmin"
        " where planned_session_id = %s",
        (sid,),
    ).fetchone()
    assert line == (1, 60, 145, 15)  # zones 4 and 5: 480 + 420 s


def test_a_session_recorded_in_two_parts_gets_both_activities(conn, bank):
    sid = domain.create_session(conn, push_session())
    store_payload(conn, "get_activity", "1", {}, activity(1, PAST, load=60, activity_type="hiit"))
    store_payload(
        conn,
        "get_activity",
        "2",
        {},
        activity(2, PAST, load=40, minutes=15, activity_type="stop_watch"),
    )

    line = conn.execute(
        "select activities, duration_minutes, training_load from session_garmin"
        " where planned_session_id = %s",
        (sid,),
    ).fetchone()
    assert line == (2, 75, 100)
    assert [r for r in calendar(conn, PAST) if r[0] == "activity"] == []


def test_a_bike_commute_never_completes_a_session(conn, bank):
    sid = domain.create_session(conn, push_session())
    store_payload(
        conn, "get_activity", "1", {}, activity(1, PAST, load=20, activity_type="cycling")
    )

    assert status(conn, sid) == "missed"
    assert ("activity", "garmin", "Synthetic cycling", "cycling", "other") in calendar(conn, PAST)


def test_a_logged_session_is_done_without_the_watch(conn, bank):
    session = push_session()
    session.parts[1].done = [domain.LineIn(exercise="Bench press", sets=4, quantity=8, load_kg=60)]
    logged = domain.create_session(conn, session)
    metcon_only = domain.create_session(
        conn,
        domain.SessionIn(
            day=PAST,
            title="Metcon",
            parts=[domain.PartIn(kind="metcon", format="amrap", result_rounds=5)],
        ),
    )
    with_feedback = domain.create_session(conn, domain.SessionIn(day=PAST, title="Mobility"))
    domain.add_feedback(conn, domain.FeedbackIn(day=PAST, planned_session_id=with_feedback, rpe=3))
    nothing = domain.create_session(conn, push_session())

    assert [status(conn, s) for s in (logged, metcon_only, with_feedback, nothing)] == [
        "done",
        "done",
        "done",
        "missed",
    ]


def test_a_future_session_is_planned_and_a_rest_day_is_rest(conn, bank):
    future = date.today() + timedelta(days=3)
    sid = domain.create_session(conn, push_session(day=future))
    rest = domain.create_session(conn, domain.SessionIn(day=PAST, title="Rest", kind="rest"))
    assert (status(conn, sid), status(conn, rest)) == ("planned", "rest")


def test_one_activity_completes_only_one_session(conn, bank):
    first = domain.create_session(conn, push_session())
    second = domain.create_session(conn, push_session())
    store_payload(conn, "get_activity", "1", {}, activity(1, PAST, load=80, activity_type="hiit"))

    assert (status(conn, first), status(conn, second)) == ("done", "missed")


def test_a_cancelled_session_leaves_the_activity_unplanned(conn, bank):
    sid = domain.create_session(conn, push_session())
    domain.cancel_session(conn, domain.CancelSession(session_id=sid))
    store_payload(conn, "get_activity", "1", {}, activity(1, PAST, load=80, activity_type="hiit"))

    rows = calendar(conn, PAST)
    assert ("session", "lifter", "Weightlifting + Push + Metcon", "training", "cancelled") in rows
    assert ("activity", "garmin", "Synthetic hiit", "hiit", "done (unplanned)") in rows


def test_garmin_scheduled_workouts_appear_until_a_snapshot_clears_them(conn):
    workouts = {
        "scheduled_workouts": [
            {
                "date": "2026-03-02",
                "scheduled_workout_id": 9,
                "name": "Garmin workout",
                "sport": "STRENGTH_TRAINING",
                "completed": False,
            }
        ]
    }
    store_payload(conn, "get_scheduled_workouts", "window", {}, workouts)
    assert calendar(conn, PAST) == [
        ("session", "garmin", "Garmin workout", "strength_training", "missed")
    ]

    store_payload(conn, "get_scheduled_workouts", "window", {}, {"empty": True})
    assert calendar(conn, PAST) == []


def test_moving_and_cancelling_a_session(conn, bank):
    sid = domain.create_session(conn, push_session())
    domain.move_session(conn, domain.MoveSession(session_id=sid, new_day=PAST + timedelta(1)))
    row = conn.execute("select day, moved_from from planned_session where id = %s", (sid,))
    assert row.fetchone() == (PAST + timedelta(1), PAST)

    domain.cancel_session(conn, domain.CancelSession(session_id=sid))
    assert status(conn, sid) == "cancelled"
    with pytest.raises(domain.DomainError):
        domain.move_session(conn, domain.MoveSession(session_id=sid, new_day=PAST))


def test_best_loads_come_from_logged_sets(conn, bank):
    session = push_session()
    session.parts[1].done = [
        domain.LineIn(exercise="Bench press", sets=1, quantity=1, load_kg=90),
        domain.LineIn(exercise="Bench press", sets=3, quantity=8, load_kg=65),
    ]
    session.parts[1].planned = [
        domain.LineIn(exercise="Bench press", sets=1, quantity=1, load_kg=95)
    ]
    domain.create_session(conn, session)

    bests = conn.execute("select exercise, reps, best_load_kg, day from exercise_best").fetchall()
    assert bests == [("Bench press", 1, 90, PAST), ("Bench press", 8, 65, PAST)]


def test_a_goal_names_an_exercise_of_the_bank_and_has_milestones(conn, bank):
    gid = domain.create_goal(
        conn,
        domain.GoalIn(
            title="Bench 100",
            exercise="Bench press",
            unit="kg",
            baseline_value=90,
            target_value=100,
            target_date=date(2026, 12, 20),
            milestones=[domain.MilestoneIn(day=date(2026, 10, 25), value=92.5)],
        ),
    )
    assert conn.execute(
        "select count(*) from goal_milestone where goal_id = %s", (gid,)
    ).fetchone() == (1,)
    with pytest.raises(domain.DomainError):
        domain.create_goal(conn, domain.GoalIn(title="Squat", exercise="Squat", target_value=1))
    with pytest.raises(ValidationError):
        domain.GoalIn(title="No target")


def test_feedback_validates_its_scales(conn):
    domain.add_feedback(conn, domain.FeedbackIn(day=PAST, rpe=7, fatigue=3, pain=0))
    with pytest.raises(ValidationError):
        domain.FeedbackIn(day=PAST, rpe=11)


def test_a_proposal_changes_nothing_until_approved_and_applied(conn, bank):
    pid = domain.propose(
        conn,
        "create_session",
        push_session().model_dump(mode="json"),
        rationale="Recovery is back to normal: the planned push session.",
        author="week_planner",
    )
    assert conn.execute("select count(*) from planned_session").fetchone() == (0,)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)  # still pending

    domain.decide(conn, pid, approve=True)
    result = domain.apply(conn, pid)

    assert conn.execute("select count(*) from session_part").fetchone() == (3,)
    row = conn.execute("select status, result from proposal where id = %s", (pid,)).fetchone()
    assert row == ("applied", result)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)  # applied once only


def test_a_rejected_proposal_is_never_applied(conn):
    pid = domain.propose(
        conn,
        "create_goal",
        {"title": "First muscle-up", "kind": "skill", "target_text": "one rep"},
        rationale="Goal mentioned in chat.",
        author="coach",
    )
    domain.decide(conn, pid, approve=False)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)
    assert conn.execute("select count(*) from goal").fetchone() == (0,)


def test_a_proposal_that_fails_is_recorded_as_failed(conn, bank):
    session = push_session().model_dump(mode="json")
    session["parts"][0]["planned"][0]["exercise"] = "Unknown lift"
    pid = domain.propose(conn, "create_session", session, "An exercise not in the bank.", "coach")
    domain.decide(conn, pid, approve=True)
    with pytest.raises(domain.DomainError):
        domain.apply(conn, pid)
    row = conn.execute("select status, result from proposal where id = %s", (pid,)).fetchone()
    assert row[0] == "failed" and "Unknown lift" in row[1]["error"]
    assert conn.execute("select count(*) from planned_session").fetchone() == (0,)


def test_proposals_are_validated_before_being_stored(conn):
    with pytest.raises(ValidationError):
        domain.propose(conn, "create_session", {"day": "2026-03-03"}, "No title.", "coach")
    with pytest.raises(ValidationError):
        domain.propose(
            conn,
            "move_session",
            {"session_id": 1, "new_day": "2026-03-03", "sql": "drop"},
            "Extra field.",
            "coach",
        )
    with pytest.raises(ValidationError):
        domain.propose(
            conn,
            "create_session",
            {"day": "2026-03-03", "title": "Metcon", "parts": [{"kind": "metcon", "time_cap": 12}]},
            "Metcons have a target, never a time cap.",
            "coach",
        )
    with pytest.raises(domain.DomainError):
        domain.propose(conn, "delete_everything", {}, "Unknown kind.", "coach")
    with pytest.raises(domain.DomainError):
        domain.propose(conn, "cancel_session", {"session_id": 1}, "  ", "coach")
    assert conn.execute("select count(*) from proposal").fetchone() == (0,)
