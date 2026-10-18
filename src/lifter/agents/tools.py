"""The coach's tools, generated from the operations catalogue (ADR 0002, Decision 2).

The model has no SQL and no direct write. It reads through a few fixed tools, and changes data
only through `apply_change` (any operation of the catalogue, with a quote of the athlete),
`suggest_change` (a pending suggestion, applied only when the athlete picks it) and
`accept_suggestion`. Every write goes through `operations.run` or `operations.suggest`, which
check the quote against the athlete's stored message, the payload, the row version and the
athlete's rules, and trace the change.

What the model never supplies: the message the quote is checked against (`message_id`, set by
the conversation endpoint), the idempotency key (derived here from the message and the order of
the write calls), the author. A refused call returns the reason to the model, so it can explain
or correct; it never raises into the graph.

Tables and columns the read tools accept are the catalogue's own (`writes` of its operations),
checked against the database catalog and quoted as identifiers: a name from the model never
reaches SQL as text.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from langchain_core.tools import BaseTool, StructuredTool
from psycopg import sql
from pydantic import BaseModel, Field, ValidationError

from lifter import operations
from lifter.agents.week_check import introduced, violations_for_week
from lifter.domain import DomainError
from lifter.quote import QuoteError

AUTHOR = "coach"
MAX_ROWS = 50


def register_rule_check() -> None:
    """Changes to the programme are checked by the guardrail on the stored week."""
    operations.set_programme_check(violations_for_week, introduced)


def readable_tables() -> set[str]:
    """The tables the coach may read row by row: the ones its operations write."""
    return {t for op in operations.CATALOGUE.values() for t in op.writes}


def _json(value: Any) -> str:
    def default(v: Any) -> Any:
        if isinstance(v, date | datetime):
            return v.isoformat()
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, BaseModel):
            return v.model_dump(mode="json")
        return str(v)

    return json.dumps(value, default=default, ensure_ascii=False)


def _refused(reason: str) -> str:
    return _json({"ok": False, "error": reason})


def operation_list() -> str:
    """One line per operation, for the system prompt and the tool descriptions."""
    lines = []
    for name, op in sorted(operations.CATALOGUE.items()):
        first = op.description.split("\n\n")[0].replace("\n", " ")
        lines.append(f"- {name}: {first}")
    return "\n".join(lines)


@dataclass
class ToolContext:
    """What the code knows and the model does not choose: the connection, the athlete's
    message being answered and its conversation, and the order of the write calls (for
    idempotency keys)."""

    conn: psycopg.Connection
    message_id: int
    conversation_id: str
    writes: int = 0
    changes: list[dict] = field(default_factory=list)  # what was applied, for the reply
    suggestions: list[int] = field(default_factory=list)  # suggestions recorded this turn
    # Older suggestions put back in front of the athlete this turn (present_suggestions): with
    # those recorded this turn, the only ones the athlete's next message can accept.
    presented: list[int] = field(default_factory=list)

    def shown(self) -> list[int]:
        return list(dict.fromkeys(self.suggestions + self.presented))

    def next_key(self) -> str:
        self.writes += 1
        return f"message:{self.message_id}:write:{self.writes}"


# Arguments of each tool, as the model sees them


class PresentSuggestionsArgs(BaseModel):
    suggestion_ids: list[int] = Field(
        min_length=1, description="Ids of older suggestions to show the athlete in your reply"
    )


class OperationSchemaArgs(BaseModel):
    operation: str = Field(description="Name of a catalogue operation")


class ReadRowsArgs(BaseModel):
    table: str = Field(
        description="One of: "
        + ", ".join(sorted(readable_tables()))
        + " (a planned session is in planned_session, its parts in session_part, its lines in"
        " session_exercise)"
    )
    column: str | None = Field(
        default=None, description="Filter on this column (equality); none for the latest rows"
    )
    value: str | int | float | bool | None = Field(
        default=None, description="The value the column must equal"
    )


class ApplyChangeArgs(BaseModel):
    operation: str = Field(description="Name of a catalogue operation")
    payload: dict[str, Any] = Field(description="The operation's payload (operation_schema)")
    quote: str = Field(
        description="The athlete's own words asking for this change, copied exactly from their "
        "message (at least two words; one word such as 'ok' or 'annule' only for undo, and only "
        "when it is their whole message)"
    )
    rationale: str = Field(default="", description="Why, in one sentence, for the trace")


class SuggestChangeArgs(BaseModel):
    operation: str = Field(description="Name of a catalogue operation")
    payload: dict[str, Any] = Field(description="The operation's payload (operation_schema)")
    rationale: str = Field(description="Why you suggest it, shown to the athlete")


class AcceptSuggestionArgs(BaseModel):
    suggestion_id: int = Field(description="The id of a pending suggestion")
    quote: str = Field(description="The athlete's words choosing it, copied exactly ('ok pour 2')")


def coach_tools(ctx: ToolContext) -> list[BaseTool]:
    """The tools bound to the coach for one athlete message."""
    conn = ctx.conn

    def operation_schema(operation: str) -> str:
        op = operations.CATALOGUE.get(operation)
        if op is None:
            return _refused(f"unknown operation: {operation}")
        return _json(
            {
                "operation": operation,
                "description": op.description,
                "changes_the_programme": op.programme,
                "payload_schema": op.payload.model_json_schema(),
            }
        )

    def read_rows(
        table: str, column: str | None = None, value: str | int | float | bool | None = None
    ) -> str:
        if table not in readable_tables():
            return _refused(f"{table!r} cannot be read: use a table of the operation list")
        columns = set(operations._columns(conn, table))
        query = sql.SQL("select to_jsonb(t) from {} t").format(sql.Identifier(table))
        params: list[Any] = []
        if column is not None:
            if column not in columns:
                return _refused(f"{table} has no column {column!r}")
            query += sql.SQL(" where {} = %s").format(sql.Identifier(column))
            params.append(value)
        query += sql.SQL(" order by id desc limit {}").format(sql.Literal(MAX_ROWS))
        try:
            with conn.transaction():
                rows = [r[0] for r in conn.execute(query, params).fetchall()]
        except psycopg.Error as exc:  # a value of the wrong type for the column
            return _refused(f"cannot read {table}: {exc.diag.message_primary or exc}")
        return _json({"table": table, "rows": rows, "truncated": len(rows) == MAX_ROWS})

    def pending_suggestions() -> str:
        rows = conn.execute(
            "select id, kind, payload, rationale, created_at from proposal"
            " where status = 'pending' order by id"
        ).fetchall()
        return _json(
            [
                {"id": r[0], "operation": r[1], "payload": r[2], "rationale": r[3], "at": r[4]}
                for r in rows
            ]
        )

    def present_suggestions(suggestion_ids: list[int]) -> str:
        found = {
            r[0]
            for r in conn.execute(
                "select id from proposal where id = any(%s) and status in ('pending', 'expired')",
                (suggestion_ids,),
            ).fetchall()
        }
        missing = [i for i in suggestion_ids if i not in found]
        if missing:
            return _refused(f"no pending or expired suggestion {missing}")
        ctx.presented += [i for i in suggestion_ids if i not in ctx.presented]
        return _json({"ok": True, "presented": ctx.presented})

    def _applied(key: str, change: operations.Change) -> str:
        found = conn.execute(
            "select c.id, p.id from change_log c join proposal p on p.id = c.proposal_id"
            " where p.idempotency_key = %s order by c.id desc limit 1",
            (key,),
        ).fetchone()
        result = {
            "ok": True,
            "proposal_id": found[1] if found else None,
            "operation": change.operation,
            "entity": change.entity,
            "entity_id": change.entity_id,
            "change_id": found[0] if found else None,
            "before": [i.row for i in change.before],
            "after": [i.row for i in change.after],
        }
        ctx.changes.append(result)
        return _json(result)

    def _attempt(call, operation: str | None = None) -> str:
        try:
            return call()
        except operations.RuleViolation as exc:
            return _json(
                {
                    "ok": False,
                    "error": "refused by the athlete's rules",
                    "violations": [getattr(v, "message", str(v)) for v in exc.violations],
                }
            )
        except QuoteError as exc:
            return _refused(f"quote refused: {exc}")
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'payload'}: {e['msg']}"
                for e in exc.errors()
            )
            refusal = {"ok": False, "error": f"invalid payload: {problems}"}
            op = operations.CATALOGUE.get(operation or "")
            if op is not None:
                # The schema with the refusal: the next try is a fix, not another guess
                refusal["payload_schema"] = op.payload.model_json_schema()
            return _json(refusal)
        except DomainError as exc:  # OperationError, StaleRow: refused, nothing written
            return _refused(str(exc))

    def apply_change(
        operation: str, payload: dict[str, Any], quote: str, rationale: str = ""
    ) -> str:
        key = ctx.next_key()
        return _attempt(
            lambda: _applied(
                key,
                operations.run(
                    conn,
                    operation,
                    payload,
                    quote=quote,
                    conversation_id=ctx.conversation_id,
                    message_id=ctx.message_id,
                    idempotency_key=key,
                    author=AUTHOR,
                    rationale=rationale,
                ),
            ),
            operation,
        )

    def suggest_change(operation: str, payload: dict[str, Any], rationale: str) -> str:
        def call() -> str:
            suggestion = operations.suggest(
                conn, operation, payload, rationale=rationale, author=AUTHOR
            )
            ctx.suggestions.append(suggestion)
            return _json({"ok": True, "suggestion_id": suggestion})

        return _attempt(call, operation)

    def accept_suggestion(suggestion_id: int, quote: str) -> str:
        # Only what the coach's last message presented can be accepted: operations.run refuses
        # the rest (one made during this turn, by a model misled by planted text, say).
        key = ctx.next_key()
        return _attempt(
            lambda: _applied(
                key,
                operations.run(
                    conn,
                    "",
                    None,
                    quote=quote,
                    conversation_id=ctx.conversation_id,
                    message_id=ctx.message_id,
                    idempotency_key=key,
                    author=AUTHOR,
                    proposal_id=suggestion_id,
                ),
            )
        )

    ops = operation_list()
    return [
        StructuredTool.from_function(
            operation_schema,
            name="operation_schema",
            description="The payload schema of one operation, before calling apply_change or "
            "suggest_change with it.",
            args_schema=OperationSchemaArgs,
        ),
        StructuredTool.from_function(
            read_rows,
            name="read_rows",
            description="Rows of one table, with their id and version (needed by updates and "
            f"deletes): filtered by one column, or the latest {MAX_ROWS}.",
            args_schema=ReadRowsArgs,
        ),
        StructuredTool.from_function(
            pending_suggestions,
            name="pending_suggestions",
            description="The suggestions waiting for the athlete's choice, with their ids.",
        ),
        StructuredTool.from_function(
            present_suggestions,
            name="present_suggestions",
            description="Put older suggestions back in front of the athlete: name them in your "
            "reply. Only what your reply presents (these and the ones you record now) can be "
            "accepted with their next message; the others expire.",
            args_schema=PresentSuggestionsArgs,
        ),
        StructuredTool.from_function(
            apply_change,
            name="apply_change",
            description="Apply one operation the athlete asked for in their message, quoting "
            "their words. Checked by code (quote, payload, version, rules) and traced; the "
            "result gives the change_id that undo takes. Operations:\n" + ops,
            args_schema=ApplyChangeArgs,
        ),
        StructuredTool.from_function(
            suggest_change,
            name="suggest_change",
            description="Record your own idea as a pending suggestion; it changes nothing until "
            "the athlete picks it (accept_suggestion). Same operations as apply_change.",
            args_schema=SuggestChangeArgs,
        ),
        StructuredTool.from_function(
            accept_suggestion,
            name="accept_suggestion",
            description="Apply a pending suggestion the athlete chose in their message.",
            args_schema=AcceptSuggestionArgs,
        ),
    ]
