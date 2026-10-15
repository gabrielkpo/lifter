"""Loading a program file (lifter.program) and the cycle views: week review, block progress."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from lifter.domain import DomainError
from lifter.program import ProgramIn, load_program, read_program

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"


def example() -> dict:
    return yaml.safe_load(EXAMPLE.read_text())


def test_the_example_program_loads(conn):
    counts = load_program(conn, read_program(EXAMPLE))

    assert counts == {
        "exercises": 23,
        "blocks": 3,
        "weeks": 2,
        "sessions": 5,
        "goals": 3,
        "rules": 5,
    }
    assert conn.execute("select count(*) from goal_milestone").fetchone() == (2,)


def test_the_week_review_counts_sessions_and_patterns(conn):
    load_program(conn, read_program(EXAMPLE))

    week = conn.execute(
        "select sessions, done, missed, strength_sessions_done, patterns_done"
        " from week_summary where number = 1"
    ).fetchone()
    # done: Monday (logged) and the moved legs session (logged); missed: Wednesday, benchmark
    assert week == (4, 2, 2, 2, ["legs", "olympic", "push"])


def test_block_progress_counts_strength_sessions_done(conn):
    load_program(conn, read_program(EXAMPLE))

    rows = conn.execute(
        "select position, strength_sessions_done, target_strength_sessions"
        " from block_progress order by position"
    ).fetchall()
    assert rows == [(1, 2, 12), (2, 0, 11), (3, 0, 9)]


def test_history_sessions_belong_to_no_week(conn):
    load_program(conn, read_program(EXAMPLE))

    row = conn.execute("select week_id from planned_session where day = '2026-02-23'").fetchone()
    assert row == (None,)
    best = conn.execute(
        "select best_load_kg from exercise_best where exercise = 'Bench press' and reps = 1"
    ).fetchone()
    assert best == (70,)


def test_loading_twice_needs_replace(conn):
    load_program(conn, read_program(EXAMPLE))
    with pytest.raises(DomainError, match="already loaded"):
        load_program(conn, read_program(EXAMPLE))

    load_program(conn, read_program(EXAMPLE), replace=True)
    assert conn.execute("select count(*) from cycle").fetchone() == (1,)
    assert conn.execute("select count(*) from planned_session").fetchone() == (5,)


def test_an_exercise_missing_from_the_bank_is_refused_before_writing(conn):
    data = example()
    data["weeks"][0]["sessions"][0]["parts"][1]["planned"][0]["exercise"] = "Squat snatch"

    with pytest.raises(ValidationError, match="Squat snatch"):
        ProgramIn.model_validate(data)


def test_a_week_in_an_unknown_block_is_refused():
    data = example()
    data["weeks"][0]["block"] = 9

    with pytest.raises(ValidationError, match="unknown blocks"):
        ProgramIn.model_validate(data)


def test_a_typo_in_a_field_is_refused():
    data = example()
    data["weeks"][0]["sessions"][0]["parts"][3]["time_cap"] = 15

    with pytest.raises(ValidationError, match="time_cap"):
        ProgramIn.model_validate(data)


def test_a_failed_load_writes_nothing(conn):
    program = read_program(EXAMPLE)
    # dropped after validation: the file check passes, the first session insert fails
    program.exercises = [e for e in program.exercises if e.name != "Bench press"]

    with pytest.raises(DomainError):
        load_program(conn, program)
    assert conn.execute("select count(*) from cycle").fetchone() == (0,)
    assert conn.execute("select count(*) from exercise").fetchone() == (0,)


def test_a_done_session_without_a_strength_part_does_not_count_for_the_block(conn):
    load_program(conn, read_program(EXAMPLE))
    conn.execute(
        "update session_part set result_rounds = 6 where session_id ="
        " (select id from planned_session where title = 'Benchmark metcon')"
    )

    week = conn.execute(
        "select done, strength_sessions_done from week_summary where number = 1"
    ).fetchone()
    assert week == (3, 2)


def test_replace_keeps_what_the_athlete_and_the_agents_added(conn):
    from lifter import domain

    load_program(conn, read_program(EXAMPLE))
    own = domain.create_session(conn, domain.SessionIn(day="2026-03-10", title="Extra"))
    domain.create_goal(conn, domain.GoalIn(title="Agent goal", target_text="x"), "agent")

    load_program(conn, read_program(EXAMPLE), replace=True)

    row = conn.execute("select title, week_id from planned_session where id = %s", (own,))
    assert row.fetchone() == ("Extra", None)
    assert conn.execute("select count(*) from planned_session").fetchone() == (6,)
    titles = {t for (t,) in conn.execute("select title from goal").fetchall()}
    assert "Agent goal" in titles and len(titles) == 4
