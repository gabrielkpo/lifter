"""The conversations with the coach (ADR 0002): the app's one write.

`POST /conversations` opens a conversation and stores the athlete's first message with the
conversation endpoint's role (lifter_chat: it may open conversations and write the athlete's
words, nothing else); `POST /conversations/{id}` adds a message to one. The coach then answers
with its own role (lifter_coach: its changes go through lifter.operations, quoted and traced, the
database refusing any other write). `GET /conversations` lists them, the most recently active
first; `GET /conversations/{id}` reads one back with the changes each message brought and the
suggestions each reply presented. Every other endpoint of the API stays read-only.

A conversation's id is drawn by the server when it opens (lifter.conversation.start), never
chosen by the client, which only names one that exists. One athlete for now: several athletes
are a later milestone. The routes on `/conversation` (the first conversation, "main") stay one
release for an app left open across the deployment, then go.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Path, Query
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from lifter.conversation import ID, start
from lifter.db import connect

CONVERSATION = "main"  # the first conversation, from before there were several
ID_PATTERN = ID.pattern
MAX_TEXT = 2000
MAX_MESSAGES = 100
MAX_CONVERSATIONS = 100


@dataclass(frozen=True)
class CoachSetup:
    """What the coach needs to answer; built from the environment (lifter.api.hosted)."""

    chat_url: str = field(repr=False)  # lifter_chat
    coach_url: str = field(repr=False)  # lifter_coach
    model: Callable[[], Any] = field(repr=False)  # the chat model, built per request
    model_name: str = "mistral-small-latest"
    language: str = "English"
    token_budget: int = 60_000


class Said(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class Change(BaseModel):
    change_id: int
    operation: str
    entity: str
    entity_id: int | None
    # What it is about, in a few words: the exercise of a line, the kind or title of a part,
    # the title and day of a session...
    subject: str | None = None
    # What it changed on that row, old to new: "RIR 2 → 5 · 60 → 45 kg".
    detail: str | None = None
    undone: bool = False


class Suggestion(BaseModel):
    id: int
    operation: str
    rationale: str
    status: str


class Message(BaseModel):
    id: int
    role: str
    text: str
    created_at: datetime
    # On an athlete's message: the changes it authorised. On a coach's reply: the suggestions it
    # presented, which the athlete's next message may accept.
    changes: list[Change] = []
    suggestions: list[Suggestion] = []


class Conversation(BaseModel):
    id: str
    title: str
    source: str
    created_at: datetime
    last_message_at: datetime


class Thread(BaseModel):
    conversation: Conversation
    messages: list[Message]


class Reply(BaseModel):
    conversation_id: str
    athlete: Message
    coach: Message
    stopped: str | None = None
    run_id: int | None = None


def _changes(conn: psycopg.Connection, message_ids: list[int]) -> dict[int, list[Change]]:
    rows = conn.execute(
        "select p.message_id, c.id as change_id, c.operation, c.entity, c.entity_id,"
        " p.undone_by is not null as undone, c.before, c.after"
        " from change_log c join proposal p on p.id = c.proposal_id"
        " where p.message_id = any(%s) order by c.id",
        (message_ids,),
    ).fetchall()
    out: dict[int, list[Change]] = {}
    for row in rows:
        after, before = _image(row.pop("after"), row), _image(row.pop("before"), row)
        out.setdefault(row.pop("message_id"), []).append(
            Change(
                **row,
                subject=_subject(conn, after or before),  # as it became, else as it was
                detail=_detail(before, after),
            )
        )
    return out


def _image(images: list[dict[str, Any]], change: dict[str, Any]) -> dict[str, Any] | None:
    """The changed row itself among the rows a change recorded."""
    return next(
        (
            i["row"]
            for i in images
            if i["table"] == change["entity"] and i["id"] == change["entity_id"] and i["row"]
        ),
        None,
    )


# The fields an athlete reads in a change, in that order, and how each is written.
DETAIL = (
    ("day", "{}"),
    ("sets", "{} sets"),
    ("quantity", "{} reps"),
    ("load_kg", "{} kg"),
    ("rir", "RIR {}"),
    ("rest_seconds", "{} s rest"),
    ("title", "{}"),
    ("kind", "{}"),
    ("status", "{}"),
)


def _detail(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str | None:
    """What an update changed on a row, old to new, in a few words."""
    if not before or not after:
        return None

    def shown(value: Any, form: str) -> str:
        if value is None:
            return "–"
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return form.format(str(value).replace("_", " "))

    parts = [
        f"{shown(before.get(key), form)} → {shown(after.get(key), form)}"
        for key, form in DETAIL
        if before.get(key) != after.get(key)
    ]
    others = [
        key
        for key in after
        if key not in dict(DETAIL)
        and key not in ("version", "updated_at", "position")
        and before.get(key) != after.get(key)
    ]
    if others:
        parts.append(", ".join(k.replace("_", " ") for k in others[:2]))
    return " · ".join(parts)[:120] or None


def _subject(conn: psycopg.Connection, row: dict[str, Any] | None) -> str | None:
    """A few words naming a changed row, for the athlete: never more than the row says."""
    if not row:
        return None
    words = []
    if row.get("exercise_id"):
        found = conn.execute("select name from exercise where id = %s", (row["exercise_id"],))
        name = found.fetchone()
        words.append(name["name"] if name else None)
    for key in ("title", "name", "kind", "body_part", "day", "text"):
        value = row.get(key)
        if value and str(value) not in words:
            words.append(str(value).replace("_", " "))
    text = " · ".join(w for w in words[:2] if w)
    return text[:80] or None


def _suggestions(conn: psycopg.Connection, message_ids: list[int]) -> dict[int, list[Suggestion]]:
    rows = conn.execute(
        "select presented_in, id, kind as operation, rationale, status from proposal"
        " where presented_in = any(%s) order by id",
        (message_ids,),
    ).fetchall()
    out: dict[int, list[Suggestion]] = {}
    for row in rows:
        out.setdefault(row.pop("presented_in"), []).append(Suggestion(**row))
    return out


def _thread(
    conn: psycopg.Connection, conversation_id: str, where: str, params: tuple, limit: int
) -> list[Message]:
    rows = conn.execute(
        "select id, role, text, created_at from conversation_message"
        f" where conversation_id = %s and {where} order by id desc limit %s",
        (conversation_id, *params, limit),
    ).fetchall()
    ids = [r["id"] for r in rows]
    changes, suggestions = _changes(conn, ids), _suggestions(conn, ids)
    return [
        Message(**r, changes=changes.get(r["id"], []), suggestions=suggestions.get(r["id"], []))
        for r in reversed(rows)
    ]


def _conversation(conn: psycopg.Connection, conversation_id: str) -> Conversation:
    row = conn.execute(
        "select id, title, source, created_at, last_message_at from conversation where id = %s",
        (conversation_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "no such conversation")
    return Conversation(**row)


def register(app: FastAPI, setup: CoachSetup | None) -> None:
    def configured() -> CoachSetup:
        if setup is None:
            raise HTTPException(503, "the coach is not configured on this server")
        return setup

    @contextmanager
    def reading() -> Iterator[psycopg.Connection]:
        """A read-only transaction with the coach's role, which reads the conversations."""
        coach = configured()
        try:
            with connect(coach.coach_url) as conn:
                conn.row_factory = dict_row
                with conn.transaction():
                    conn.execute("set transaction read only")
                    yield conn
        except psycopg.Error:
            raise HTTPException(503, "database unavailable") from None

    def turn(text: str, conversation_id: str | None, *, opened_as: str | None = None) -> Reply:
        """The athlete's message, then the coach's answer to it (one turn, 1 to 8 model calls).

        `conversation_id` None opens a new conversation with this message; `opened_as` opens
        the one of that id if it does not exist yet (the first conversation, "main")."""
        from lifter.agents.coach import StaleMessage, respond

        coach = configured()
        opening = conversation_id is None
        opened: str | None = None  # a conversation this turn opened, kept if the turn fails

        def failed(status: int, message: str) -> HTTPException:
            # The app goes on in the conversation it opened instead of opening another one.
            detail: Any = {"message": message, "conversation_id": opened} if opened else message
            return HTTPException(status, detail)

        try:
            # The conversation and the message in one transaction: never one without the other.
            with connect(coach.chat_url) as chat:
                if conversation_id is None or opened_as:
                    conversation_id = start(chat, title=text, source="app", id=opened_as)
                elif not chat.execute(
                    "select 1 from conversation where id = %s", (conversation_id,)
                ).fetchone():
                    raise HTTPException(404, "no such conversation")
                message_id = chat.execute(
                    "insert into conversation_message (conversation_id, role, text)"
                    " values (%s, 'athlete', %s) returning id",
                    (conversation_id, text),
                ).fetchone()[0]
            if opening:
                opened = conversation_id
            with connect(coach.coach_url) as conn:
                reply = respond(
                    conn,
                    coach.model(),
                    conversation_id=conversation_id,
                    message_id=message_id,
                    model_name=coach.model_name,
                    language=coach.language,
                    trigger="app",
                    token_budget=coach.token_budget,
                )
                conn.row_factory = dict_row
                athlete, answer = _thread(
                    conn, conversation_id, "id = any(%s)", ([message_id, reply.message_id],), 2
                )
        except StaleMessage:
            raise failed(409, "a newer message is waiting: reload the conversation") from None
        except httpx.HTTPError:  # its text names the URL; nothing of the key reaches the client
            raise failed(502, "the coach's model is unreachable, try again") from None
        except psycopg.Error:
            raise failed(503, "database unavailable") from None
        return Reply(
            conversation_id=conversation_id,
            athlete=athlete,
            coach=answer,
            stopped=reply.stopped,
            run_id=reply.run_id,
        )

    @app.get("/conversations")
    def conversations(
        limit: int = Query(50, ge=1, le=MAX_CONVERSATIONS),
        before: str | None = Query(None, pattern=ID_PATTERN),
    ) -> list[Conversation]:
        """The conversations, the most recently active first; `before` (the last id of the
        previous page) gives the next page."""
        with reading() as conn:
            after = "true"
            params: tuple = ()
            if before is not None:
                after = (
                    "(c.last_message_at, c.id)"
                    " < (select last_message_at, id from conversation where id = %s)"
                )
                params = (before,)
            rows = conn.execute(
                "select c.id, c.title, c.source, c.created_at, c.last_message_at"
                f" from conversation c where {after}"
                " order by c.last_message_at desc, c.id desc limit %s",
                (*params, limit),
            ).fetchall()
            return [Conversation(**r) for r in rows]

    @app.get("/conversations/{conversation_id}")
    def conversation(
        conversation_id: str = Path(pattern=ID_PATTERN),
        limit: int = Query(50, ge=1, le=MAX_MESSAGES),
    ) -> Thread:
        """A conversation and its latest messages, oldest first."""
        with reading() as conn:
            return Thread(
                conversation=_conversation(conn, conversation_id),
                messages=_thread(conn, conversation_id, "true", (), limit),
            )

    @app.post("/conversations")
    def open_conversation(said: Said) -> Reply:
        """A new conversation, opened by the athlete's first message and the coach's answer."""
        return turn(said.text, None)

    @app.post("/conversations/{conversation_id}")
    def continue_conversation(said: Said, conversation_id: str = Path(pattern=ID_PATTERN)) -> Reply:
        """The athlete's next message in a conversation, and the coach's answer."""
        return turn(said.text, conversation_id)

    # The first conversation's routes, for one release (an app left open across the deployment).
    @app.get("/conversation")
    def thread(limit: int = Query(50, ge=1, le=MAX_MESSAGES)) -> list[Message]:
        """The latest messages of the first conversation, oldest first."""
        with reading() as conn:
            return _thread(conn, CONVERSATION, "true", (), limit)

    @app.post("/conversation")
    def say(said: Said) -> Reply:
        """The athlete's message in the first conversation, then the coach's answer."""
        return turn(said.text, CONVERSATION, opened_as=CONVERSATION)
