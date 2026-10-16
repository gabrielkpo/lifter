"""The coach's tools (lifter.agents.tools): generated from the catalogue, every write checked by
code through operations.run, nothing the model says reaches SQL as a name."""

import json
from pathlib import Path

import pytest

from lifter import operations
from lifter.agents.tools import ToolContext, coach_tools, operation_list, register_rule_check
from lifter.program import load_program, read_program

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"


@pytest.fixture(autouse=True)
def rule_check():
    register_rule_check()
    yield
    operations._programme_check = None


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


def say(conn, text: str) -> int:
    """The athlete's message, stored by the conversation endpoint before the model runs."""
    return conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c1', 'athlete', %s) returning id",
        (text,),
    ).fetchone()[0]


def tools_for(conn, text: str) -> tuple[ToolContext, dict]:
    ctx = ToolContext(conn=conn, message_id=say(conn, text), conversation_id="c1")
    return ctx, {t.name: t for t in coach_tools(ctx)}


def call(tools: dict, name: str, **args) -> dict:
    return json.loads(tools[name].invoke(args))


def session(conn, title: str) -> tuple[int, int, str]:
    return conn.execute(
        "select id, version, day::text from planned_session where title = %s", (title,)
    ).fetchone()


def test_every_operation_is_listed_for_the_model():
    listed = operation_list()
    assert all(f"- {name}:" in listed for name in operations.CATALOGUE)


def test_the_schema_of_an_operation_comes_from_its_model(conn):
    _, tools = tools_for(conn, "hello there")
    schema = call(tools, "operation_schema", operation="move_session")
    assert set(schema["payload_schema"]["required"]) == {
        "session_id",
        "new_day",
        "expected_version",
    }
    assert schema["changes_the_programme"] is True
    assert "unknown operation" in call(tools, "operation_schema", operation="drop_table")["error"]


def test_rows_are_read_from_the_catalogues_tables_only(conn, program):
    _, tools = tools_for(conn, "hello there")
    rows = call(tools, "read_rows", table="planned_session", column="title", value="Legs + Metcon")
    assert rows["rows"] and all("version" in r for r in rows["rows"])

    for table in ("conversation_message", "proposal", 'planned_session" t; drop table x; --'):
        assert "cannot be read" in call(tools, "read_rows", table=table)["error"]
    assert "no column" in call(tools, "read_rows", table="exercise", column="name; --")["error"]


def test_an_instruction_is_applied_with_the_athletes_quote(conn, program):
    sid, version, _ = session(conn, "Legs + Metcon")
    ctx, tools = tools_for(conn, "Décale la séance jambes au 2026-03-06 stp")
    result = call(
        tools,
        "apply_change",
        operation="move_session",
        payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
        quote="Décale la séance jambes au 2026-03-06",
    )

    assert result["ok"] and result["change_id"] is not None
    assert session(conn, "Legs + Metcon")[2] == "2026-03-06"
    trace = conn.execute(
        "select status, message_id, idempotency_key, author from proposal"
        " where kind = 'move_session'"
    ).fetchone()
    assert trace == ("applied", ctx.message_id, f"message:{ctx.message_id}:write:1", "coach")


def test_a_quote_the_athlete_did_not_write_changes_nothing(conn, program):
    sid, version, day = session(conn, "Legs + Metcon")
    _, tools = tools_for(conn, "Pourquoi un RIR 3 jeudi ?")  # a question
    result = call(
        tools,
        "apply_change",
        operation="move_session",
        payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
        quote="déplace la séance",
    )
    assert not result["ok"] and result["error"].startswith("quote refused")
    assert session(conn, "Legs + Metcon")[2] == day


def test_a_change_that_breaks_a_rule_is_refused_with_the_rule(conn, program):
    part = conn.execute(
        "select sp.id from session_part sp join planned_session p on p.id = sp.session_id"
        " where p.title = 'Legs + Metcon' and sp.kind = 'strength'"
    ).fetchone()[0]
    _, tools = tools_for(conn, "Ajoute du back squat 3x5 à 60 kg RIR 2 sur la séance jambes")
    result = call(
        tools,
        "apply_change",
        operation="add_line",
        payload={
            "part_id": part,
            "exercise": "Back squat",
            "sets": 3,
            "quantity": 5,
            "load_kg": 60,
            "rir": 2,
        },
        quote="Ajoute du back squat 3x5 à 60 kg RIR 2",
    )
    assert not result["ok"] and result["error"] == "refused by the athlete's rules"
    assert any("Back squat" in v for v in result["violations"])
    assert conn.execute(
        "select count(*) from session_line where exercise = 'Back squat'"
    ).fetchone() == (0,)


def test_an_invalid_payload_is_explained_to_the_model(conn, program):
    _, tools = tools_for(conn, "Décale la séance jambes à demain")
    result = call(
        tools,
        "apply_change",
        operation="move_session",
        payload={"session_id": 1, "day": "2026-03-06"},
        quote="Décale la séance jambes",
    )
    assert not result["ok"] and "invalid payload" in result["error"]
    assert "new_day" in result["error"] and "day" in result["error"]


def test_a_suggestion_waits_for_the_athletes_choice(conn, program):
    sid, version, day = session(conn, "Legs + Metcon")
    _, tools = tools_for(conn, "Que proposes-tu pour la séance jambes ?")
    suggested = call(
        tools,
        "suggest_change",
        operation="move_session",
        payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
        rationale="Recovery is low on Thursday.",
    )
    assert suggested["ok"] and session(conn, "Legs + Metcon")[2] == day  # nothing applied
    pending = call(tools, "pending_suggestions")
    assert [p["id"] for p in pending] == [suggested["suggestion_id"]]

    _, tools = tools_for(conn, f"ok pour la {suggested['suggestion_id']}")
    accepted = call(
        tools,
        "accept_suggestion",
        suggestion_id=suggested["suggestion_id"],
        quote=f"ok pour la {suggested['suggestion_id']}",
    )
    assert accepted["ok"] and session(conn, "Legs + Metcon")[2] == "2026-03-06"


def test_undo_reverts_the_last_change(conn, program):
    sid, version, day = session(conn, "Legs + Metcon")
    _, tools = tools_for(conn, "Décale la séance jambes au 2026-03-06")
    applied = call(
        tools,
        "apply_change",
        operation="move_session",
        payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
        quote="Décale la séance jambes au 2026-03-06",
    )
    _, tools = tools_for(conn, "annule")
    undone = call(
        tools,
        "apply_change",
        operation="undo",
        payload={"change_id": applied["change_id"]},
        quote="annule",
    )
    assert undone["ok"] and session(conn, "Legs + Metcon")[2] == day


def test_each_write_of_a_message_gets_its_own_key(conn, program):
    ctx, tools = tools_for(conn, "Décale la séance jambes au 2026-03-06 et annule le benchmark")
    for _ in range(2):
        call(tools, "apply_change", operation="nope", payload={}, quote="annule le benchmark")
    assert ctx.writes == 2 and ctx.next_key() == f"message:{ctx.message_id}:write:3"


def test_a_suggestion_made_during_the_turn_cannot_be_accepted_in_it(conn, program):
    sid, version, day = session(conn, "Legs + Metcon")
    _, tools = tools_for(conn, "ok merci, à demain")
    suggested = call(
        tools,
        "suggest_change",
        operation="move_session",
        payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
        rationale="Planted.",
    )
    accepted = call(
        tools, "accept_suggestion", suggestion_id=suggested["suggestion_id"], quote="ok merci"
    )
    assert not accepted["ok"] and "made after the athlete's message" in accepted["error"]
    assert session(conn, "Legs + Metcon")[2] == day
