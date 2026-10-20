"""The coach's tools (lifter.agents.tools): generated from the catalogue, every write checked by
code through operations.run, nothing the model says reaches SQL as a name."""

import json
from pathlib import Path

import pytest

from lifter import operations
from lifter.agents.tools import ToolContext, coach_tools, operation_list, register_rule_check
from lifter.conversation import start
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
    start(conn, id="c1", title=text, source="cli")
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
    # the schema comes with the refusal, so the next try can be right
    assert "new_day" in result["payload_schema"]["properties"]


def test_an_invalid_suggestion_comes_back_with_its_schema(conn, program):
    _, tools = tools_for(conn, "Tu changerais quoi ?")
    result = call(
        tools, "suggest_change", operation="update_session", payload={"day": "x"}, rationale="r"
    )
    assert not result["ok"] and "invalid payload" in result["error"]
    assert "expected_version" in result["payload_schema"]["properties"]


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
    coach_replies(conn, "Je propose de la décaler à vendredi.", [suggested["suggestion_id"]])

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


def test_a_bare_undo_never_reaches_a_change_made_in_another_conversation(conn, program):
    sid, version, day = session(conn, "Legs + Metcon")
    _, tools = tools_for(conn, "Décale la séance jambes au 2026-03-06")
    applied = call(
        tools,
        "apply_change",
        operation="move_session",
        payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
        quote="Décale la séance jambes au 2026-03-06",
    )

    def elsewhere(text: str) -> dict:
        start(conn, id="c2", title=text, source="cli")
        message = conn.execute(
            "insert into conversation_message (conversation_id, role, text)"
            " values ('c2', 'athlete', %s) returning id",
            (text,),
        ).fetchone()[0]
        ctx = ToolContext(conn=conn, message_id=message, conversation_id="c2")
        return {t.name: t for t in coach_tools(ctx)}

    undo = {"operation": "undo", "payload": {"change_id": applied["change_id"]}}
    refused = call(elsewhere("annule"), "apply_change", quote="annule", **undo)
    assert not refused["ok"] and "another conversation" in refused["error"]
    assert session(conn, "Legs + Metcon")[2] == "2026-03-06"

    named = "annule le déplacement de la séance jambes"
    undone = call(elsewhere(named), "apply_change", quote=named, **undo)
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
    assert not accepted["ok"] and "not presented" in accepted["error"]
    assert session(conn, "Legs + Metcon")[2] == day


def coach_replies(conn, text: str, shown: list[int]) -> int:
    """The coach's reply as respond() stores it, presenting `shown` (audit N7)."""
    start(conn, id="c1", title=text, source="cli")
    message = conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c1', 'coach', %s) returning id",
        (text,),
    ).fetchone()[0]
    operations.present(conn, conversation_id="c1", coach_message_id=message, proposal_ids=shown)
    return message


def test_an_older_suggestion_is_accepted_only_once_presented_again(conn, program):
    # Listing is not presenting: the planner's suggestion becomes acceptable only when the coach
    # puts it back in front of the athlete (present_suggestions), and expires when it does not.
    sid, version, _ = session(conn, "Legs + Metcon")
    planner = operations.suggest(
        conn,
        "move_session",
        {"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
        rationale="Planned by the planner.",
        author="planner",
    )
    ctx, tools = tools_for(conn, "Quelles suggestions sont en attente ?")
    call(tools, "pending_suggestions")
    assert ctx.shown() == []
    coach_replies(conn, "Une suggestion du planificateur attend.", ctx.shown())
    _, tools = tools_for(conn, f"ok pour la {planner}")
    refused = call(tools, "accept_suggestion", suggestion_id=planner, quote=f"ok pour la {planner}")
    assert not refused["ok"] and "not presented" in refused["error"]

    ctx, tools = tools_for(conn, "montre-la moi")
    assert call(tools, "present_suggestions", suggestion_ids=[planner])["ok"]
    coach_replies(conn, f"La {planner} : décaler la séance jambes à vendredi.", ctx.shown())
    _, tools = tools_for(conn, f"ok pour la {planner}")
    accepted = call(
        tools, "accept_suggestion", suggestion_id=planner, quote=f"ok pour la {planner}"
    )
    assert accepted["ok"] and session(conn, "Legs + Metcon")[2] == "2026-03-06"


def test_exercise_records_reads_what_the_pr_tab_shows(conn, program):
    _, tools = tools_for(conn, "Quel est mon PR au leg press ?")
    result = call(tools, "exercise_records", exercise="leg press")  # any case
    assert result["exercise"] == "Leg press"
    assert result["best_load_per_reps"] and result["recent"]

    conn.execute(
        "insert into record_definition (name, kind, record_type, unit, exercise_id)"
        " select 'Leg press 1RM', 'lift', 'rep_max', 'kg', id from exercise where name = 'Leg press'"
    )
    conn.execute(
        "insert into record_entry (definition_id, day, reps, value)"
        " select id, '2026-03-01', 1, 150 from record_definition where name = 'Leg press 1RM'"
    )
    (record,) = call(tools, "exercise_records", exercise="Leg press")["records"]
    assert (record["record"], record["reps"], float(record["value"])) == ("Leg press 1RM", 1, 150.0)

    unknown = call(tools, "exercise_records", exercise="leg")
    assert not unknown["ok"] and "Leg press" in unknown["error"]
