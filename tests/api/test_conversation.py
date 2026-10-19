"""The conversation with the coach through the API (lifter.api.conversation): a scripted model
stands in for Mistral, and each side runs as its production role (lifter_chat, lifter_coach)."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from psycopg.conninfo import make_conninfo

from lifter import operations
from lifter.api.app import create_app
from lifter.api.conversation import CONVERSATION, CoachSetup
from lifter.program import load_program, read_program
from test_coach import ScriptedChat, tool_call

EXAMPLE = Path(__file__).parents[2] / "examples" / "program.yaml"


@pytest.fixture(autouse=True)
def no_leftover_rule_check():
    yield
    operations._programme_check = None


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


def as_role(url: str, role: str) -> str:
    return make_conninfo(url, options=f"-c role={role}")


def api_with(database_url: str, model) -> TestClient:
    setup = CoachSetup(
        chat_url=as_role(database_url, "lifter_chat"),
        coach_url=as_role(database_url, "lifter_coach"),
        model=model,
    )
    return TestClient(create_app(database_url, coach=setup), base_url="http://127.0.0.1:8000")


def legs(conn) -> tuple[int, int]:
    return conn.execute(
        "select id, version from planned_session where title = 'Legs + Metcon'"
    ).fetchone()


def test_a_message_is_answered_and_its_change_shown_under_it(conn, database_url, program):
    sid, version = legs(conn)
    model = ScriptedChat(
        tool_call(
            "apply_change",
            operation="move_session",
            payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
            quote="Décale la séance jambes au 2026-03-06",
        ),
        AIMessage("C'est fait : la séance jambes passe au vendredi 6 mars."),
    )
    api = api_with(database_url, lambda: model)

    reply = api.post("/conversation", json={"text": "Décale la séance jambes au 2026-03-06"})

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["athlete"]["text"] == "Décale la séance jambes au 2026-03-06"
    assert body["coach"]["text"].startswith("C'est fait")
    (change,) = body["athlete"]["changes"]
    assert change["operation"] == "move_session" and not change["undone"]
    assert change["subject"].startswith("Legs + Metcon")  # what moved, not just "move session"
    assert body["run_id"] is not None
    thread = api.get("/conversation").json()
    assert [(m["role"], m["id"]) for m in thread] == [
        ("athlete", body["athlete"]["id"]),
        ("coach", body["coach"]["id"]),
    ]
    assert thread[0]["changes"][0]["change_id"] == change["change_id"]


def test_a_suggestion_presented_by_the_reply_comes_back_with_it(conn, database_url, program):
    sid, version = legs(conn)
    model = ScriptedChat(
        tool_call(
            "suggest_change",
            operation="move_session",
            payload={"session_id": sid, "new_day": "2026-03-06", "expected_version": version},
            rationale="Recovery is low on Thursday.",
        ),
        AIMessage("Je propose de décaler la séance jambes à vendredi (suggestion 1)."),
    )
    body = api_with(database_url, lambda: model).post(
        "/conversation", json={"text": "Que proposes-tu pour jeudi ?"}
    )
    (suggestion,) = body.json()["coach"]["suggestions"]
    assert suggestion["operation"] == "move_session" and suggestion["status"] == "pending"


def test_a_newer_message_makes_the_turn_stale(conn, database_url, program):
    # Another message lands between storing this one and answering it: nothing runs.
    def model():
        conn.execute(
            "insert into conversation_message (conversation_id, role, text)"
            " values (%s, 'athlete', 'plus récent')",
            (CONVERSATION,),
        )
        return ScriptedChat()

    reply = api_with(database_url, model).post("/conversation", json={"text": "salut coach"})
    assert reply.status_code == 409


def test_an_unreachable_model_is_a_502_without_detail(conn, database_url, program):
    class Down(ScriptedChat):
        def invoke(self, messages):
            raise httpx.ConnectError("https://api.mistral.ai/v1/chat/completions")

    reply = api_with(database_url, Down).post("/conversation", json={"text": "salut coach"})
    assert reply.status_code == 502
    assert "mistral.ai" not in reply.text


def test_without_the_coach_configured_the_conversation_is_off(database_url):
    api = TestClient(create_app(database_url), base_url="http://127.0.0.1:8000")
    assert api.get("/conversation").status_code == 503
    assert api.post("/conversation", json={"text": "salut"}).status_code == 503


def test_an_empty_or_huge_message_is_refused(conn, database_url, program):
    api = api_with(database_url, ScriptedChat)
    assert api.post("/conversation", json={"text": ""}).status_code == 422
    assert api.post("/conversation", json={"text": "x" * 2001}).status_code == 422
    assert conn.execute("select count(*) from conversation_message").fetchone() == (0,)
