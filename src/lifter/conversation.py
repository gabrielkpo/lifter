"""The conversations with the coach (migration 015): every message belongs to one that exists.

`start` is the one way to open a conversation, for the app (an id drawn by the database), the
terminal and the bench (an id of their own, opened once). Nothing here deletes or renames one.
"""

import re
from typing import Literal

import psycopg
from psycopg.rows import tuple_row

Source = Literal["app", "cli", "bench"]
# A conversation's name in the list: the start of the athlete's first message.
TITLE_MAX = 60
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def title_of(text: str) -> str:
    """The first words of a message, on one line, cut between two words."""
    line = " ".join(text.split())
    if len(line) <= TITLE_MAX:
        return line or "Conversation"
    cut = line[: TITLE_MAX - 1].rsplit(" ", 1)[0] or line[: TITLE_MAX - 1]
    return cut.rstrip(" ,;:.") + "…"


def start(conn: psycopg.Connection, *, title: str, source: Source, id: str | None = None) -> str:
    """Open a conversation named after `title` and return its id: a new one drawn by the
    database, or `id`, left as it is when it already exists."""
    cur = conn.cursor(row_factory=tuple_row)
    if id is None:
        return cur.execute(
            "insert into conversation (title, source) values (%s, %s) returning id",
            (title_of(title), source),
        ).fetchone()[0]
    cur.execute(
        "insert into conversation (id, title, source) values (%s, %s, %s)"
        " on conflict (id) do nothing",
        (id, title_of(title), source),
    )
    return id
