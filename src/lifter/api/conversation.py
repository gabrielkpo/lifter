"""The conversation with the coach (ADR 0002): the app's one write.

`POST /conversation` stores the athlete's message with the conversation endpoint's role
(lifter_chat: it may write the athlete's words and nothing else), then the coach answers it with
its own role (lifter_coach: its changes go through lifter.operations, quoted and traced, the
database refusing any other write). `GET /conversation` reads the thread back with the changes
each message brought and the suggestions each reply presented. Every other endpoint of the API
stays read-only.

One athlete, one conversation for now: its id is fixed here, never chosen by the client
(several athletes are a later milestone).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from lifter.db import connect

CONVERSATION = "main"
MAX_TEXT = 2000
MAX_MESSAGES = 100


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


class Reply(BaseModel):
    athlete: Message
    coach: Message
    stopped: str | None = None
    run_id: int | None = None


def _changes(conn: psycopg.Connection, message_ids: list[int]) -> dict[int, list[Change]]:
    rows = conn.execute(
        "select p.message_id, c.id as change_id, c.operation, c.entity, c.entity_id,"
        " p.undone_by is not null as undone"
        " from change_log c join proposal p on p.id = c.proposal_id"
        " where p.message_id = any(%s) order by c.id",
        (message_ids,),
    ).fetchall()
    out: dict[int, list[Change]] = {}
    for row in rows:
        out.setdefault(row.pop("message_id"), []).append(Change(**row))
    return out


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


def _thread(conn: psycopg.Connection, where: str, params: tuple, limit: int) -> list[Message]:
    rows = conn.execute(
        "select id, role, text, created_at from conversation_message"
        f" where conversation_id = %s and {where} order by id desc limit %s",
        (CONVERSATION, *params, limit),
    ).fetchall()
    ids = [r["id"] for r in rows]
    changes, suggestions = _changes(conn, ids), _suggestions(conn, ids)
    return [
        Message(**r, changes=changes.get(r["id"], []), suggestions=suggestions.get(r["id"], []))
        for r in reversed(rows)
    ]


def register(app: FastAPI, setup: CoachSetup | None) -> None:
    def configured() -> CoachSetup:
        if setup is None:
            raise HTTPException(503, "the coach is not configured on this server")
        return setup

    @app.get("/conversation")
    def thread(limit: int = Query(50, ge=1, le=MAX_MESSAGES)) -> list[Message]:
        """The latest messages of the conversation, oldest first."""
        coach = configured()
        try:
            with connect(coach.coach_url) as conn:
                conn.row_factory = dict_row
                with conn.transaction():
                    conn.execute("set transaction read only")
                    return _thread(conn, "true", (), limit)
        except psycopg.Error:
            raise HTTPException(503, "database unavailable") from None

    @app.post("/conversation")
    def say(said: Said) -> Reply:
        """The athlete's message, then the coach's answer to it (one turn, 1 to 8 model calls)."""
        from lifter.agents.coach import StaleMessage, respond

        coach = configured()
        try:
            with connect(coach.chat_url) as chat:
                message_id = chat.execute(
                    "insert into conversation_message (conversation_id, role, text)"
                    " values (%s, 'athlete', %s) returning id",
                    (CONVERSATION, said.text),
                ).fetchone()[0]
            with connect(coach.coach_url) as conn:
                reply = respond(
                    conn,
                    coach.model(),
                    conversation_id=CONVERSATION,
                    message_id=message_id,
                    model_name=coach.model_name,
                    language=coach.language,
                    trigger="app",
                    token_budget=coach.token_budget,
                )
                conn.row_factory = dict_row
                athlete, answer = _thread(
                    conn, "id = any(%s)", ([message_id, reply.message_id],), 2
                )
        except StaleMessage:
            raise HTTPException(
                409, "a newer message is waiting: reload the conversation"
            ) from None
        except httpx.HTTPError:  # its text names the URL; nothing of the key reaches the client
            raise HTTPException(502, "the coach's model is unreachable, try again") from None
        except psycopg.Error:
            raise HTTPException(503, "database unavailable") from None
        return Reply(athlete=athlete, coach=answer, stopped=reply.stopped, run_id=reply.run_id)
