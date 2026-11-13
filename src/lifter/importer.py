"""Import an athlete's log written elsewhere (a training journal kept by hand) through the coach's
write path: every item is one operation of `lifter.operations`, authorised by the athlete's own
words for it, traced in the change log and reversible with `undo`, like a change asked in the app.

The file (YAML) holds a conversation title and a list of items:

    title: Journal from 20/10 to 10/11
    items:
      - key: s-2026-10-20           # unique in the file: re-running skips what was applied
        said: "Mardi 20/10, cardio : 3000 m rameur, 3000 m ski erg, 20 min de mobilité"
        op: log_session
        ref: cardio-20              # optional: later payloads name its entity as "$cardio-20"
        payload: {...}

`said` is stored as the athlete's message in the import's conversation and quoted whole by the
operation: the import authorises nothing the log does not say. In a payload:

- "$name" is the entity a previous item (`ref: name`) created or changed;
- {"$id": [table, {column: value, ...}]} is the id of the one row of that table that matches
  (a catalogue table only, values bound as parameters);
- "expected_version": "$current" is the current version of the row the same object names (`id`,
  `part_id` or `session_id`), read just before the operation runs.

Items run in order, each in its own transaction, as the athlete (`author="athlete"`): the
athlete's rules are reported, never refused, and nothing waits for a confirmation, since the log
records what the athlete already did or decided. The conversation's messages are written as
lifter_chat and the operations as lifter_coach, so the database's trace check holds.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml
from pydantic import BaseModel, Field, field_validator

from lifter import operations
from lifter.conversation import start

KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
# A reference names an earlier item's `ref`: "$" then a letter ("$5" stays text).
REF = re.compile(r"^\$[A-Za-z][A-Za-z0-9_.:-]*$")
VERSIONED = {"part_id": "session_part", "session_id": "planned_session"}


class Item(BaseModel):
    key: str
    said: str = Field(min_length=1, max_length=20_000)
    op: str
    ref: str | None = None
    payload: dict[str, Any] = {}

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not KEY.match(value):
            raise ValueError(f"key {value!r}: letters, digits and . _ : - only, 80 at most")
        return value

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str | None) -> str | None:
        if value is not None and not REF.match("$" + value):
            raise ValueError(f"ref {value!r}: a letter, then letters, digits and . _ : -")
        return value

    @field_validator("op")
    @classmethod
    def _op(cls, value: str) -> str:
        if value not in operations.CATALOGUE or value == "undo":
            raise ValueError(f"unknown operation: {value}")
        return value


class ImportFile(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    items: list[Item] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def _unique(cls, items: list[Item]) -> list[Item]:
        keys = [i.key for i in items]
        refs = [i.ref for i in items if i.ref]
        for name, values in (("key", keys), ("ref", refs)):
            twice = sorted({v for v in values if values.count(v) > 1})
            if twice:
                raise ValueError(f"{name} used twice: {', '.join(twice)}")
        return items


def read_import(path: Path) -> ImportFile:
    with path.open(encoding="utf-8") as f:
        return ImportFile.model_validate(yaml.safe_load(f))


def conversation_id(file: ImportFile) -> str:
    """The import's conversation, the same on every run of the same title."""
    return "import-" + hashlib.sha256(file.title.encode()).hexdigest()[:16]


@dataclass
class Outcome:
    key: str
    op: str
    entity_id: int | None
    skipped: bool
    violations: list[dict[str, Any]]


class Resolver:
    """Turns a payload's references into ids and versions, on the coach's connection."""

    def __init__(self, conn: psycopg.Connection, refs: dict[str, int | None]):
        self.conn = conn
        self.refs = refs
        self.tables = operations._writable()

    def resolve(self, value: Any, table: str | None = None) -> Any:
        if isinstance(value, str) and REF.match(value) and value != "$current":
            name = value[1:]
            if name not in self.refs:
                raise operations.OperationError(f"{value}: no earlier item has this ref")
            return self.refs[name]
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {"$id"}:
            return self._id(*value["$id"])
        out = {k: self.resolve(v) for k, v in value.items() if k != "expected_version"}
        if "expected_version" in value:
            out["expected_version"] = self._version(value["expected_version"], out, table)
        return out

    def _id(self, table: str, where: dict[str, Any]) -> int:
        if table not in self.tables:
            raise operations.OperationError(f"$id: {table} is not a catalogue table")
        columns = set(operations._columns(self.conn, table))
        unknown = set(where) - columns
        if unknown or not where:
            raise operations.OperationError(f"$id on {table}: unknown columns {sorted(unknown)}")
        resolved = {k: self.resolve(v) for k, v in where.items()}
        sql = " and ".join(f'"{k}" = %s' for k in resolved)
        rows = self.conn.execute(
            f"select id from {table} where {sql}", tuple(resolved.values())
        ).fetchall()
        if len(rows) != 1:
            raise operations.OperationError(f"$id on {table} {where}: {len(rows)} rows match")
        return rows[0][0]

    def _version(self, value: Any, obj: dict[str, Any], table: str | None) -> Any:
        if value != "$current":
            return value
        # The row the object names as its own (`id`, in the operation's table) comes first; a
        # nested part or a session to move is named by part_id or session_id.
        if "id" in obj and table is not None:
            row_table, row_id = table, obj["id"]
        else:
            named = [(t, obj[c]) for c, t in VERSIONED.items() if c in obj]
            if not named:
                raise operations.OperationError("expected_version $current: which row?")
            row_table, row_id = named[0]
        row = self.conn.execute(
            f"select version from {row_table} where id = %s", (row_id,)
        ).fetchone()
        if row is None:
            raise operations.OperationError(f"{row_table} {row_id} does not exist")
        return row[0]


def run_import(
    file: ImportFile,
    chat: psycopg.Connection,
    coach: psycopg.Connection,
    *,
    on_item: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    """Apply the file's items in order; an item already applied (same key) is skipped, its entity
    kept for later references. Stops at the first item that fails, after reporting it."""
    cid = conversation_id(file)
    with chat.transaction():
        start(chat, id=cid, title=file.title, source="cli")
    refs: dict[str, int | None] = {}
    outcomes = []
    for item in file.items:
        key = f"import:{cid}:{item.key}"
        done = coach.execute(
            "select p.status, p.result, p.kind, m.text from proposal p"
            " left join conversation_message m on m.id = p.message_id"
            " where p.idempotency_key = %s",
            (key,),
        ).fetchone()
        if done is not None:
            if done[0] != "applied" or done[2] != item.op:
                raise operations.OperationError(
                    f"{item.key}: already recorded as {done[2]} {done[0]}"
                )
            if done[3] != item.said:
                # Same title and key, other words: another item, never skipped silently.
                raise operations.OperationError(
                    f"{item.key}: this key was applied with other words; give this item a new key"
                )
            change = operations.Change.model_validate(done[1])
            skipped = True
        else:
            table = operations.CATALOGUE[item.op].writes[0]
            payload = Resolver(coach, refs).resolve(item.payload, table)
            with chat.transaction():
                row = chat.execute(
                    "insert into conversation_message (conversation_id, role, text)"
                    " values (%s, 'athlete', %s) returning id",
                    (cid, item.said),
                ).fetchone()
                assert row is not None  # an insert ... returning gives its row
                message_id = row[0]
            change = operations.run(
                coach,
                item.op,
                payload,
                conversation_id=cid,
                quote=item.said,
                message_id=message_id,
                idempotency_key=key,
                author="athlete",
                rationale=f"{file.title}: {item.key}",
            )
            skipped = False
        if item.ref:
            refs[item.ref] = change.entity_id
        outcome = Outcome(item.key, item.op, change.entity_id, skipped, change.violations)
        outcomes.append(outcome)
        if on_item:
            on_item(outcome)
    return outcomes
