"""The coach in conversation (lifter.agents.coach): a scripted model stands in for Mistral, so
these tests check everything around it: what it sees, what its tool calls change, the limits,
the stored reply and the audit."""

from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from lifter import operations
from lifter.agents.coach import respond
from lifter.program import load_program, read_program

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"
TODAY = date(2026, 3, 4)  # inside week 1


@pytest.fixture(autouse=True)
def no_leftover_rule_check():
    yield
    operations._programme_check = None


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


class ScriptedChat:
    """A chat model that answers from a script, one message per call, and keeps what it saw."""

    def __init__(self, *answers: AIMessage):
        self.answers = list(answers)
        self.seen: list[list] = []

    def bind_tools(self, tools):
        self.tools = {t.name for t in tools}
        return self

    def invoke(self, messages):
        self.seen.append(list(messages))
        answer = self.answers.pop(0) if self.answers else AIMessage("Done.")
        answer.usage_metadata = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
        return answer


def tool_call(name: str, n: int = 1, **args) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"call_{n}"}])


def say(conn, text: str, conversation: str = "c1") -> int:
    return conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values (%s, 'athlete', %s) returning id",
        (conversation, text),
    ).fetchone()[0]


def session(conn, title: str):
    return conn.execute(
        "select id, version, day::text from planned_session where title = %s", (title,)
    ).fetchone()


def answer(conn, model, message_id, **kw):
    return respond(conn, model, conversation_id="c1", message_id=message_id, today=TODAY, **kw)


def test_an_instruction_is_applied_reported_stored_and_audited(conn, program):
    sid, version, _ = session(conn, "Legs + Metcon")
    message = say(conn, "Décale la séance jambes au 2026-03-06 stp")
    model = ScriptedChat(
        tool_call(
            "apply_change",
            operation="move_session",
            payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
            quote="Décale la séance jambes au 2026-03-06",
        ),
        AIMessage("Séance jambes déplacée au vendredi 6 mars, cette semaine seulement."),
    )
    reply = answer(conn, model, message, model_name="fake", trigger="cli")

    assert session(conn, "Legs + Metcon")[2] == "2026-03-06"
    assert reply.text.startswith("Séance jambes déplacée") and reply.stopped is None
    assert [c["operation"] for c in reply.changes] == ["move_session"]
    stored = conn.execute(
        "select role, text from conversation_message where id = %s", (reply.message_id,)
    ).fetchone()
    assert stored == ("coach", reply.text)
    run = conn.execute(
        "select agent, trigger, status, attempts, input_tokens, proposal_ids,"
        " jsonb_array_length(context -> 'calls') from agent_run where id = %s",
        (reply.run_id,),
    ).fetchone()
    assert run[:5] == ("coach", "cli", "accepted", 2, 2000)
    assert run[5] == [reply.changes[0]["proposal_id"]] and run[6] == 2  # the call, its result


def test_the_coach_sees_the_snapshot_and_the_conversation(conn, program):
    say(conn, "Salut coach")
    conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c1', 'coach', 'Salut !')"
    )
    message = say(conn, "Pourquoi un RIR 3 sur la presse ?")
    model = ScriptedChat(AIMessage("Parce que la semaine 1 accumule du volume."))
    answer(conn, model, message)

    system, *conversation = model.seen[0]
    assert isinstance(system, SystemMessage)
    assert "Legs + Metcon" in system.content and '"today": "2026-03-04"' in system.content
    assert [m.content for m in conversation] == [
        "Salut coach",
        "Salut !",
        "Pourquoi un RIR 3 sur la presse ?",
    ]
    assert model.tools >= {"apply_change", "suggest_change", "read_rows", "operation_schema"}


def test_a_question_changes_nothing(conn, program):
    _, _, day = session(conn, "Legs + Metcon")
    message = say(conn, "Pourquoi un RIR 3 jeudi ?")
    reply = answer(conn, ScriptedChat(AIMessage("Le RIR 3 garde de la marge.")), message)
    assert reply.changes == [] and session(conn, "Legs + Metcon")[2] == day
    assert conn.execute("select count(*) from proposal").fetchone() == (0,)


def test_an_invented_quote_is_refused_and_nothing_changes(conn, program):
    sid, version, day = session(conn, "Legs + Metcon")
    message = say(conn, "Pourquoi un RIR 3 jeudi ?")
    model = ScriptedChat(
        tool_call(
            "apply_change",
            operation="move_session",
            payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
            quote="déplace la séance jambes",  # not what the athlete wrote
        ),
        AIMessage("Je ne peux pas : tu ne me l'as pas demandé."),
    )
    reply = answer(conn, model, message)

    assert reply.changes == [] and session(conn, "Legs + Metcon")[2] == day
    refused = model.seen[1][-1]  # the tool's answer the model read next
    assert "quote refused" in refused.content


def test_the_run_stops_at_its_step_limit(conn, program):
    message = say(conn, "Montre-moi mes exercices")
    looping = [tool_call("read_rows", n, table="exercise") for n in range(10)]
    reply = answer(conn, ScriptedChat(*looping), message, max_steps=3, trigger="cli")

    assert reply.usage.calls == 3 and "step limit reached" in reply.stopped
    assert "I stopped before finishing" in reply.text
    status = conn.execute("select status from agent_run where id = %s", (reply.run_id,))
    assert status.fetchone() == ("refused",)


def test_the_run_stops_at_its_token_budget(conn, program):
    message = say(conn, "Montre-moi mes exercices")
    looping = [tool_call("read_rows", n, table="exercise") for n in range(10)]
    reply = answer(conn, ScriptedChat(*looping), message, token_budget=2000)
    assert reply.usage.calls == 2 and "token budget reached: 2200 of 2000" in reply.stopped


def test_a_crash_is_audited_with_its_error(conn, program):
    class Down(ScriptedChat):
        def invoke(self, messages):
            raise ConnectionError("Mistral unreachable")

    message = say(conn, "Salut coach")
    with pytest.raises(ConnectionError):
        answer(conn, Down(), message, trigger="cli")
    row = conn.execute("select agent, status, error from agent_run").fetchone()
    assert row == ("coach", "error", "ConnectionError: Mistral unreachable")


def test_chat_stores_the_message_and_prints_the_reply(
    monkeypatch, capsys, conn, program, database_url
):
    from lifter.cli import main

    model = ScriptedChat(AIMessage("Bonjour ! Rien à changer pour l'instant."))
    monkeypatch.setattr("lifter.agents.coach.mistral_model", lambda *a, **k: model)
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    assert main(["chat", "Salut coach", "--today", "2026-03-04"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("Bonjour !") and "audit: lifter run" in out
    rows = conn.execute(
        "select role, text from conversation_message where conversation_id = 'cli' order by id"
    ).fetchall()
    assert rows == [
        ("athlete", "Salut coach"),
        ("coach", "Bonjour ! Rien à changer pour l'instant."),
    ]


def test_chat_needs_the_mistral_key(monkeypatch, capsys):
    from lifter.cli import main

    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert main(["chat", "Salut"]) == 2
    assert "MISTRAL_API_KEY is not set" in capsys.readouterr().out


def test_a_crash_after_a_change_tells_the_athlete_and_keeps_the_calls(conn, program):
    sid, version, _ = session(conn, "Legs + Metcon")
    message = say(conn, "Décale la séance jambes au 2026-03-06 stp")

    class FailsSecond(ScriptedChat):
        def invoke(self, messages):
            if self.seen:
                raise TimeoutError("Mistral timed out")
            return super().invoke(messages)

    model = FailsSecond(
        tool_call(
            "apply_change",
            operation="move_session",
            payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
            quote="Décale la séance jambes au 2026-03-06",
        )
    )
    with pytest.raises(TimeoutError):
        answer(conn, model, message, trigger="cli")

    told = conn.execute(
        "select text from conversation_message where role = 'coach' order by id desc limit 1"
    ).fetchone()[0]
    assert "error after applying: move_session" in told
    calls = conn.execute("select context -> 'calls' from agent_run").fetchone()[0]
    assert calls[0]["tool"] == "apply_change" and '"ok": true' in calls[1]["result"]


def test_the_coach_runs_with_the_lifter_coach_role_only(conn, program, database_url):
    """End to end under the coach's own grants: reads, an applied change with its trace, the
    reply and the audit. A missing grant fails here, not in production."""
    from test_roles import as_role

    sid, version, _ = session(conn, "Legs + Metcon")
    message = say(conn, "Décale la séance jambes au 2026-03-06 stp")  # the endpoint's role
    model = ScriptedChat(
        tool_call("read_rows", 1, table="planned_session", column="id", value=sid),
        tool_call(
            "apply_change",
            2,
            operation="move_session",
            payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
            quote="Décale la séance jambes au 2026-03-06",
        ),
        AIMessage("C'est fait : jeudi 6 mars."),
    )
    with as_role(database_url, "lifter_coach") as coach_conn:
        reply = respond(
            coach_conn,
            model,
            conversation_id="c1",
            message_id=message,
            today=TODAY,
            trigger="app",
        )

    assert [c["operation"] for c in reply.changes] == ["move_session"]
    assert '"rows": [{"id": ' in model.seen[1][-1].content  # read_rows worked under the role
    assert session(conn, "Legs + Metcon")[2] == "2026-03-06"
    assert conn.execute("select count(*) from change_log").fetchone() == (1,)
    assert conn.execute(
        "select agent, trigger, status from agent_run where id = %s", (reply.run_id,)
    ).fetchone() == ("coach", "app", "accepted")


def test_only_the_athletes_latest_message_can_be_answered(conn, program):
    from lifter.agents.coach import StaleMessage

    first = say(conn, "Décale la séance jambes au 2026-03-06")
    say(conn, "En fait non, ne change rien")
    other = say(conn, "Salut", conversation="c2")
    model = ScriptedChat(AIMessage("..."))
    for message, conversation in ((first, "c1"), (other, "c1"), (99999, "c1")):
        with pytest.raises(StaleMessage):
            respond(conn, model, conversation_id=conversation, message_id=message, today=TODAY)
    assert model.seen == []  # the model never ran
    assert conn.execute("select count(*) from agent_run").fetchone() == (0,)
