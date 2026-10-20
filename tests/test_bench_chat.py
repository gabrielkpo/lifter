"""The conversation bench (lifter.bench.conversation): scenarios, checks, and the silent floor."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from lifter import operations
from lifter.bench.conversation import (
    Conversation,
    SilentCoach,
    no_forbidden_suggestion,
    read_conversations,
    run_conversation,
    summary,
)

SCENARIOS = Path(__file__).parent.parent / "bench" / "conversations"


@pytest.fixture(autouse=True)
def no_leftover_rule_check():
    yield
    operations._programme_check = None


@pytest.fixture(scope="module")
def conversations():
    return {c.name: c for c in read_conversations(SCENARIOS)}


def test_fifteen_scenarios_with_known_checks(conversations):
    assert len(conversations) == 15
    assert {c.category for c in conversations.values()} == {
        "instruction",
        "question",
        "health",
        "report",
        "rules",
        "injection",
    }


def test_an_unknown_check_is_refused():
    with pytest.raises(ValueError, match="unknown check"):
        Conversation.model_validate(
            {
                "name": "x",
                "category": "question",
                "description": "x",
                "today": "2026-01-18",
                "messages": ["x"],
                "expect": [{"check": "looks_fine"}],
                "review": "x",
            }
        )


def test_the_silent_floor(conn, conversations):
    results = [r for c in conversations.values() for r in run_conversation(conn, c, SilentCoach, 1)]
    totals = summary(results)
    # it never changes anything: every "nothing changed" expectation passes, no other one
    assert totals["expectations_met_rate"] == 0.5 and totals["scenarios_fully_met"] == 5
    met = {r.scenario for r in results if r.expectations_met == r.expectations}
    assert met == {
        "question",
        "ideas_only",
        "planted_note",
        "forbidden_exercise",
        "record_without_reps",
    }


def test_a_coach_that_does_the_job_meets_the_move_scenario(conn, conversations):
    move = conversations["move_session"]

    class Mover:
        def bind_tools(self, tools):
            return self

        def __init__(self):
            self.turn = 0

        def invoke(self, messages):
            self.turn += 1
            if self.turn > 1:
                return AIMessage("Déplacée au jeudi 22 janvier, semaine 3 seulement.")
            sid, version = conn.execute(
                "select p.id, p.version from planned_session p"
                " join training_week w on w.id = p.week_id"
                " where w.number = 3 and p.title = 'Legs + Metcon'"
            ).fetchone()
            call = {
                "name": "apply_change",
                "id": "call_1",
                "args": {
                    "operation": "move_session",
                    "payload": {
                        "session_id": sid,
                        "new_day": "2026-01-22",
                        "expected_version": version,
                    },
                    "quote": "Décale la séance Legs + Metcon de cette semaine au jeudi 22 janvier",
                },
            }
            return AIMessage("", tool_calls=[call])

    (result,) = run_conversation(conn, move, Mover, 1)
    assert result.expectations_met == result.expectations == 2
    assert result.refused_quotes == 0


def test_bench_chat_refuses_a_database_that_is_not_a_bench_one(monkeypatch, capsys):
    from lifter.cli import main

    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("BENCH_DATABASE_URL", "postgresql:///lifter")
    assert main(["bench-chat"]) == 2
    assert "lifter_bench" in capsys.readouterr().out


def test_a_suggestion_of_a_forbidden_exercise_fails_its_check(conn, conversations):
    run_conversation(conn, conversations["forbidden_exercise"], SilentCoach, 1)
    assert no_forbidden_suggestion(conn, {}) == (True, "forbidden in suggestions: none")
    conn.execute(
        "insert into proposal (kind, payload, rationale, author)"
        " values ('add_line', %s, 'idea', 'coach')",
        ('{"line": {"exercise": "Back squat", "sets": 5}}',),
    )
    assert no_forbidden_suggestion(conn, {}) == (False, "forbidden in suggestions: Back squat")


def test_an_empty_new_part_fails_the_add_mobility_check(conn, conversations):
    from lifter.bench.conversation import planned_line_in_part

    run_conversation(conn, conversations["add_mobility"], SilentCoach, 1)
    params = {"week": 3, "title": "Legs + Metcon", "kind": "mobility", "position": 1}
    assert planned_line_in_part(conn, params) == (
        False,
        "0 mobility part(s), 0 with a planned line",
    )
    sid = conn.execute(
        "select s.id from planned_session s join training_week w on w.id = s.week_id"
        " where w.number = 3 and s.title = 'Legs + Metcon'"
    ).fetchone()[0]
    part = conn.execute(
        "insert into session_part (session_id, position, kind) values (%s, 9, 'mobility')"
        " returning id",
        (sid,),
    ).fetchone()[0]
    assert planned_line_in_part(conn, params) == (
        False,
        "1 mobility part(s), 0 with a planned line",
    )
    conn.execute(
        "insert into session_exercise (part_id, origin, position, exercise_id, sets, quantity)"
        " select %s, 'planned', 1, id, 1, 60 from exercise where name = 'Hip mobility'",
        (part,),
    )
    # a filled part at position 9 is not at the start
    assert planned_line_in_part(conn, params) == (
        False,
        "1 mobility part(s), 1 with a planned line at position 9",
    )
    assert planned_line_in_part(conn, params | {"position": 9})[0]


def test_the_parts_count_of_the_mobility_check(conn, conversations):
    from lifter.bench.conversation import planned_line_in_part

    run_conversation(conn, conversations["mobility_three_joints"], SilentCoach, 1)
    sid = conn.execute(
        "select s.id from planned_session s join training_week w on w.id = s.week_id"
        " where w.number = 3 and s.title = 'Legs + Metcon'"
    ).fetchone()[0]
    for position in (8, 9):  # two mobility parts, each with a line: one too many
        part = conn.execute(
            "insert into session_part (session_id, position, kind) values (%s, %s, 'mobility')"
            " returning id",
            (sid, position),
        ).fetchone()[0]
        conn.execute(
            "insert into session_exercise (part_id, origin, position, exercise_id, sets, quantity)"
            " select %s, 'planned', 1, id, 1, 60 from exercise where name = 'Hip mobility'",
            (part,),
        )
    params = {"week": 3, "title": "Legs + Metcon", "kind": "mobility"}
    assert planned_line_in_part(conn, params)[0]
    assert not planned_line_in_part(conn, params | {"parts": 1})[0]
