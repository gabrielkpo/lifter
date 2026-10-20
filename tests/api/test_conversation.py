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
from lifter.conversation import start
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
    assert change["detail"].endswith("→ 2026-03-06")  # and where to
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
    start(conn, id=CONVERSATION, title="salut coach", source="app")

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
    assert api.get("/conversations").status_code == 503
    assert api.post("/conversations", json={"text": "salut"}).status_code == 503


def test_an_empty_or_huge_message_is_refused(conn, database_url, program):
    api = api_with(database_url, ScriptedChat)
    assert api.post("/conversation", json={"text": ""}).status_code == 422
    assert api.post("/conversation", json={"text": "x" * 2001}).status_code == 422
    assert conn.execute("select count(*) from conversation_message").fetchone() == (0,)


def test_a_first_message_opens_a_conversation_listed_first(conn, database_url, program):
    model = lambda: ScriptedChat(AIMessage("Bien noté."))  # noqa: E731
    api = api_with(database_url, model)

    first = api.post("/conversations", json={"text": "Comment va   mon squat ?\nDis-moi"})
    second = api.post("/conversations", json={"text": "Je suis fatigué", "id": "mine"})

    assert first.status_code == 200 and second.status_code == 200, second.text
    one, two = first.json()["conversation_id"], second.json()["conversation_id"]
    assert len({one, two, "mine"}) == 3  # drawn by the server, never the client's
    listed = api.get("/conversations").json()
    assert [(c["id"], c["title"], c["source"]) for c in listed] == [
        (two, "Je suis fatigué", "app"),
        (one, "Comment va mon squat ? Dis-moi", "app"),
    ]
    thread = api.get(f"/conversations/{one}").json()
    assert thread["conversation"]["id"] == one
    assert [m["role"] for m in thread["messages"]] == ["athlete", "coach"]


def test_a_conversation_goes_on_where_it_was(conn, database_url, program):
    api = api_with(database_url, lambda: ScriptedChat(AIMessage("Ok.")))
    one = api.post("/conversations", json={"text": "Salut coach"}).json()["conversation_id"]
    two = api.post("/conversations", json={"text": "Autre sujet"}).json()["conversation_id"]

    reply = api.post(f"/conversations/{one}", json={"text": "Et pour jeudi ?"})

    assert reply.status_code == 200, reply.text
    assert reply.json()["conversation_id"] == one
    texts = [m["text"] for m in api.get(f"/conversations/{one}").json()["messages"]]
    assert texts == ["Salut coach", "Ok.", "Et pour jeudi ?", "Ok."]
    assert len(api.get(f"/conversations/{two}").json()["messages"]) == 2
    # The one just written to is the most recently active again.
    assert [c["id"] for c in api.get("/conversations").json()] == [one, two]


def test_the_list_comes_by_pages(conn, database_url, program):
    api = api_with(database_url, lambda: ScriptedChat(AIMessage("Ok.")))
    ids = [
        api.post("/conversations", json={"text": f"message {i}"}).json()["conversation_id"]
        for i in range(3)
    ]
    page = api.get("/conversations", params={"limit": 2}).json()
    assert [c["id"] for c in page] == [ids[2], ids[1]]
    rest = api.get("/conversations", params={"limit": 2, "before": ids[1]}).json()
    assert [c["id"] for c in rest] == [ids[0]]


def test_an_unknown_conversation_is_a_404_and_stores_nothing(conn, database_url, program):
    api = api_with(database_url, ScriptedChat)
    assert api.get("/conversations/nope").status_code == 404
    assert api.post("/conversations/nope", json={"text": "salut"}).status_code == 404
    assert api.get("/conversations/a%20b").status_code == 422  # not an id at all
    assert conn.execute("select count(*) from conversation_message").fetchone() == (0,)
    assert conn.execute("select count(*) from conversation").fetchone() == (0,)


def test_a_newer_message_elsewhere_does_not_stop_a_turn(conn, database_url, program):
    # A turn is stale only when a newer message waits in its own conversation.
    api = api_with(database_url, lambda: ScriptedChat(AIMessage("Ok.")))
    other = api.post("/conversations", json={"text": "Autre"}).json()["conversation_id"]

    def model():
        conn.execute(
            "insert into conversation_message (conversation_id, role, text)"
            " values (%s, 'athlete', 'ailleurs')",
            (other,),
        )
        return ScriptedChat(AIMessage("Toujours là."))

    reply = api_with(database_url, model).post("/conversations", json={"text": "Salut"})
    assert reply.status_code == 200, reply.text


def test_a_failed_first_turn_says_which_conversation_it_opened(conn, database_url, program):
    # The message is stored all the same: the app goes on there instead of opening another.
    class Down(ScriptedChat):
        def invoke(self, messages):
            raise httpx.ConnectError("https://api.mistral.ai/v1/chat/completions")

    api = api_with(database_url, Down)
    reply = api.post("/conversations", json={"text": "salut coach"})

    assert reply.status_code == 502
    opened = reply.json()["detail"]["conversation_id"]
    texts = [m["text"] for m in api.get(f"/conversations/{opened}").json()["messages"]]
    assert texts == ["salut coach"]
    assert "mistral.ai" not in reply.text


def test_a_change_says_what_it_changed_old_to_new():
    from lifter.api.conversation import _detail

    before = {"id": 1, "sets": 3, "quantity": 5, "load_kg": 60.0, "rir": 2, "version": 1}
    after = before | {"load_kg": 45.0, "rir": 5, "version": 2, "notes": "léger"}
    assert _detail(before, after) == "60 kg → 45 kg · RIR 2 → RIR 5 · notes"
    assert _detail(None, after) is None  # created: nothing to compare


def moved(conn, database_url, day: str = "2026-03-06"):
    """A conversation in which the coach moved the legs session to `day`."""
    sid, version = legs(conn)
    model = ScriptedChat(
        tool_call(
            "apply_change",
            operation="move_session",
            payload={"session_id": sid, "new_day": day, "expected_version": version},
            quote=f"Décale la séance jambes au {day}",
        ),
        AIMessage("C'est fait."),
    )
    api = api_with(database_url, lambda: model)
    body = api.post("/conversations", json={"text": f"Décale la séance jambes au {day}"}).json()
    return api, body["conversation_id"], body["athlete"]["changes"][0]["change_id"]


def test_undo_is_applied_without_the_model(conn, database_url, program):
    api, conversation, change = moved(conn, database_url)
    day_before = legs(conn)

    reply = api.post(f"/conversations/{conversation}/undo", json={"change_id": change})

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["athlete"]["text"] == f"annule le changement {change}"
    assert body["coach"]["text"] == "Undone." and body["run_id"] is None
    assert body["athlete"]["changes"][0]["operation"] == "undo"
    thread = api.get(f"/conversations/{conversation}").json()["messages"]
    assert thread[0]["changes"][0]["undone"]  # the move, shown undone under its message
    assert legs(conn) != day_before


def test_an_undo_blocked_by_later_changes_names_them(conn, database_url, program):
    api, conversation, first = moved(conn, database_url, "2026-03-06")
    sid, version = legs(conn)
    model = ScriptedChat(
        tool_call(
            "apply_change",
            operation="move_session",
            payload={"session_id": sid, "new_day": "2026-03-07", "expected_version": version},
            quote="Décale la séance jambes au 2026-03-07",
        ),
        AIMessage("C'est fait."),
    )
    second = (
        api_with(database_url, lambda: model)
        .post(
            f"/conversations/{conversation}", json={"text": "Décale la séance jambes au 2026-03-07"}
        )
        .json()["athlete"]["changes"][0]["change_id"]
    )

    reply = api.post(f"/conversations/{conversation}/undo", json={"change_id": first}).json()

    assert reply["coach"]["text"] == (
        f"To undo it, first undo the later changes on the same rows: {second} (the latest first)."
    )
    assert reply["athlete"]["changes"] == []


def test_undo_in_an_unknown_conversation_is_a_404(conn, database_url, program):
    api = api_with(database_url, ScriptedChat)
    assert api.post("/conversations/nope/undo", json={"change_id": 1}).status_code == 404
    assert api.post("/conversations/nope/undo", json={"change_id": 0}).status_code == 422
