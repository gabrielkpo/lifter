"""The conversation bench (lifter.bench.conversation): scenarios, checks, and the silent floor."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from lifter import operations
from lifter.bench.conversation import (
    Conversation,
    SilentCoach,
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


def test_eight_scenarios_with_known_checks(conversations):
    assert len(conversations) == 8
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
    assert totals["expectations_met_rate"] == 0.5 and totals["scenarios_fully_met"] == 4
    met = {r.scenario for r in results if r.expectations_met == r.expectations}
    assert met == {"question", "ideas_only", "planted_note", "forbidden_exercise"}


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
