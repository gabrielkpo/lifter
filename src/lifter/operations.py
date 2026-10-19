"""The catalogue of operations: the only way the coach changes data (ADR 0002, Decision 3).

Each operation has a stable name (the coach's tool of the same name), a strict payload model
whose docstring is the tool's description, the tables it writes (read by the coverage test),
and `apply`, which returns a `Change`: the rows before and after, from which `undo` rebuilds the
previous state exactly (ids included).

`run` is the single entry point and does everything in one transaction, in this order:
1. a retry with the same idempotency key returns the change already made, writing nothing;
2. the message must be the athlete's latest in the conversation (the one being answered), and
   the quote is checked against it as stored (lifter.quote);
3. the payload is validated (unknown fields refused);
4. the operation is applied; a row whose version changed since the coach read it is refused;
5. for an operation on the programme, the guardrail's violations on the weeks it touches are
   computed before and after, and the change is refused if it introduces one;
6. the trace: one `proposal` row (applied, with the quote and the message) and one `change_log`
   row. The database refuses the coach's commit without them (009_write_path.sql), and an
   applied proposal's trace cannot be rewritten afterwards (011_trace_integrity.sql).

Updates are partial: only the fields given change, and an explicit null sets the column to
null. The rule check is registered by the coach before it runs
(`lifter.agents.tools.register_rule_check`, through `set_programme_check`), so the domain does
not import the agents; without it, an operation on the programme is refused.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, create_model, model_validator
from pydantic.fields import FieldInfo

from lifter import domain
from lifter.domain import (
    DomainError,
    ExerciseIn,
    FeedbackIn,
    GoalIn,
    LineIn,
    MetconFormat,
    MilestoneIn,
    PartKind,
    RuleIn,
    SessionIn,
    StrictModel,
)
from lifter.quote import verify_quote

# The change


class RowImage(BaseModel):
    """One row as it was (before) or became (after); `row` is null when it did not exist."""

    table: str
    id: int
    row: dict[str, Any] | None


class Change(BaseModel):
    operation: str
    entity: str
    entity_id: int | None
    before: list[RowImage]
    after: list[RowImage]
    # Set by `undo`: the proposal whose change was reverted.
    undoes: int | None = None
    # A change of the athlete's rules is not refused for the sessions already planned that the
    # new rules flag: they are reported here, for the coach to adapt them.
    violations: list[dict[str, Any]] = []


class OperationError(DomainError):
    """The operation was refused; nothing was written."""


class StaleRow(OperationError):
    """A row changed since the coach read it: read it again and propose again."""


class RuleViolation(OperationError):
    def __init__(self, violations: list[Any]):
        self.violations = violations
        messages = "; ".join(getattr(v, "message", str(v)) for v in violations)
        super().__init__(f"the change breaks the athlete's rules: {messages}")


@dataclass(frozen=True)
class Context:
    """Who applies the change, for the columns that record it (`source`, `reported_quote`)."""

    source: Literal["athlete", "agent"]
    quote: str


@dataclass(frozen=True)
class Operation:
    name: str
    payload: type[StrictModel]
    writes: tuple[str, ...]
    apply: Callable[[psycopg.Connection, Any, Context], Change]
    # Changes what is prescribed: checked by the guardrail on `weeks(conn, payload)`.
    programme: bool = False
    weeks: Callable[[psycopg.Connection, Any], set[int]] | None = None
    # The athlete's rules themselves: what the guardrail then flags is reported, not refused.
    report: bool = False
    # "ok", "annule": one word is enough (the athlete's whole message).
    short_quote: bool = False

    @property
    def description(self) -> str:
        return (self.payload.__doc__ or "").strip()


CATALOGUE: dict[str, Operation] = {}

_programme_check: tuple[Callable, Callable] | None = None


def set_programme_check(
    violations_for_week: Callable[[psycopg.Connection, int], list],
    introduced: Callable[[list, list], list],
) -> None:
    """Register the guardrail on a stored week (lifter.agents.week_check)."""
    global _programme_check
    _programme_check = (violations_for_week, introduced)


def _register(
    name: str,
    payload: type[StrictModel],
    writes: tuple[str, ...],
    *,
    programme: bool = False,
    weeks: Callable | None = None,
    short_quote: bool = False,
    report: bool = False,
):
    def wrap(fn):
        CATALOGUE[name] = Operation(
            name,
            payload,
            writes,
            fn,
            programme=programme,
            weeks=weeks,
            short_quote=short_quote,
            report=report,
        )
        return fn

    return wrap


# Rows: images, versions, generic writes. Table and column names come from this module, never
# from a payload.


def _row(conn: psycopg.Connection, table: str, row_id: int) -> dict[str, Any] | None:
    found = conn.execute(f"select to_jsonb(t) from {table} t where id = %s", (row_id,)).fetchone()
    return found[0] if found else None


def _image(conn: psycopg.Connection, table: str, row_id: int) -> RowImage:
    return RowImage(table=table, id=row_id, row=_row(conn, table, row_id))


def _existing(conn, table: str, row_id: int, expected_version: int | None = None) -> dict:
    row = _row(conn, table, row_id)
    if row is None:
        raise OperationError(f"{table} {row_id} does not exist")
    if expected_version is not None and row["version"] != expected_version:
        raise StaleRow(
            f"{table} {row_id} changed since it was read (version {row['version']}, "
            f"not {expected_version})"
        )
    return row


def _value(value: Any) -> Any:
    return Jsonb(value) if isinstance(value, dict) else value


def _insert(conn, table: str, values: dict[str, Any]) -> RowImage:
    row_id = domain.insert_row(conn, table, values)
    return _image(conn, table, row_id)


def _update(conn, table: str, row_id: int, expected_version: int | None, values: dict) -> Change:
    before = RowImage(table=table, id=row_id, row=_existing(conn, table, row_id, expected_version))
    sets = ", ".join(f"{column} = %s" for column in values)
    conn.execute(
        f"update {table} set {sets} where id = %s",
        [*(_value(v) for v in values.values()), row_id],
    )
    return Change(
        operation="",
        entity=table,
        entity_id=row_id,
        before=[before],
        after=[_image(conn, table, row_id)],
    )


def _references(conn, table: str) -> list[tuple[str, str, str]]:
    """Single-column foreign keys pointing at `table`: (child table, column, on delete)."""
    return conn.execute(
        """
        select c.conrelid::regclass::text, a.attname, c.confdeltype::text
        from pg_constraint c
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
        where c.contype = 'f' and c.confrelid = %s::regclass and array_length(c.conkey, 1) = 1
        order by 1, 2
        """,
        (table,),
    ).fetchall()


def _dependents(conn, table: str, ids: list[int], out: list[RowImage], nulled: list[RowImage]):
    """Every row a delete of `ids` removes by cascade (parents first) or sets to null, each
    once: a week is reached both from its cycle and from its block.

    Only the catalogue's tables are imaged: `undo` restores those alone. A row elsewhere that
    points here with `on delete set null` (an agent run's target week) keeps its own history and
    just loses the link; one that would go by cascade makes the delete refused, since no undo
    could bring it back."""
    seen = {(i.table, i.id) for i in out + nulled}
    writable = _writable()
    for child, column, action in _references(conn, table):
        if child not in writable:
            if (
                action == "c"
                and conn.execute(
                    f"select exists (select from {child} where {column} = any(%s))", (ids,)
                ).fetchone()[0]
            ):
                raise OperationError(f"{child} rows depend on this {table}: it cannot be deleted")
            continue
        child_ids = [
            r[0]
            for r in conn.execute(
                f"select id from {child} where {column} = any(%s) order by id", (ids,)
            ).fetchall()
            if (child, r[0]) not in seen
        ]
        if not child_ids:
            continue
        if action == "c":
            out.extend(_image(conn, child, i) for i in child_ids)
            seen.update((child, i) for i in child_ids)
            _dependents(conn, child, child_ids, out, nulled)
            seen = {(i.table, i.id) for i in out + nulled}
        elif action == "n":
            nulled.extend(_image(conn, child, i) for i in child_ids)
            seen.update((child, i) for i in child_ids)


def _delete(conn, table: str, row_id: int, expected_version: int) -> Change:
    """Delete a row with its cascade: `before` holds every row removed or set to null, so
    `undo` recreates them exactly."""
    removed = [
        RowImage(table=table, id=row_id, row=_existing(conn, table, row_id, expected_version))
    ]
    nulled: list[RowImage] = []
    _dependents(conn, table, [row_id], removed, nulled)
    try:
        with conn.transaction():
            conn.execute(f"delete from {table} where id = %s", (row_id,))
    except psycopg.errors.ForeignKeyViolation as exc:
        detail = exc.diag.message_detail or str(exc)
        raise OperationError(f"{table} {row_id} is still used: {detail}") from None
    return Change(
        operation="",
        entity=table,
        entity_id=row_id,
        before=removed + nulled,
        after=[_image(conn, img.table, img.id) for img in nulled],
    )


def _columns(conn, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "select attname from pg_attribute where attrelid = %s::regclass and attnum > 0"
            " and not attisdropped order by attnum",
            (table,),
        ).fetchall()
    ]


def _writable() -> set[str]:
    return {t for op in CATALOGUE.values() for t in op.writes}


def _content(row: dict[str, Any]) -> dict[str, Any]:
    """A row without its bookkeeping: an undo bumps the version of the rows it puts back, so
    undoing the changes one after the other (the last first) compares what they hold."""
    return {k: v for k, v in row.items() if k not in ("version", "updated_at")}


def revert(conn: psycopg.Connection, change: Change) -> Change:
    """The inverse of `change`: delete what it created, recreate what it deleted (same ids),
    restore what it updated. Refused when any of those rows changed since."""
    # Table names are put in SQL: only the catalogue's own tables, whatever a stored change says.
    unknown = {i.table for i in change.before + change.after} - _writable()
    if unknown:
        raise OperationError(
            f"a change can only touch the catalogue's tables, not {sorted(unknown)}"
        )
    before = {(i.table, i.id): i.row for i in change.before}
    after = {(i.table, i.id): i.row for i in change.after}
    for (table, row_id), row in after.items():
        current = _row(conn, table, row_id)
        if row is None:
            if current is not None:
                raise StaleRow(f"{table} {row_id} exists again since this change")
        elif current is None or _content(current) != _content(row):
            raise StaleRow(f"{table} {row_id} changed since this change: undo is refused")
    for key in before.keys() - after.keys():
        if _row(conn, *key) is not None:
            raise StaleRow(f"{key[0]} {key[1]} exists again since this change")
    created = [i for i in change.after if before.get((i.table, i.id)) is None and i.row]
    # Rows added since under a row this undo deletes would go with it silently, or lose their
    # link to it (on delete set null): refuse.
    for img in created:
        extra: list[RowImage] = []
        nulled: list[RowImage] = []
        _dependents(conn, img.table, [img.id], extra, nulled)
        unknown = [e for e in extra + nulled if (e.table, e.id) not in after]
        if unknown:
            raise StaleRow(f"{unknown[0].table} {unknown[0].id} was added since this change")

    undo_before = [_image(conn, t, i) for t, i in sorted(before.keys() | after.keys())]
    for img in reversed(created):
        conn.execute(f"delete from {img.table} where id = %s", (img.id,))
    for img in change.before:
        if img.row is None:
            continue
        if after.get((img.table, img.id)) is None:
            conn.execute(
                f"insert into {img.table}"
                f" select * from jsonb_populate_record(null::{img.table}, %s)",
                (Jsonb(img.row),),
            )
        else:
            columns = [c for c in _columns(conn, img.table) if c != "id"]
            names = ", ".join(columns)
            conn.execute(
                f"update {img.table} set ({names}) = (select {names} from"
                f" jsonb_populate_record(null::{img.table}, %s)) where id = %s",
                (Jsonb(img.row), img.id),
            )
    return Change(
        operation="undo",
        entity=change.entity,
        entity_id=change.entity_id,
        before=undo_before,
        after=[_image(conn, i.table, i.id) for i in undo_before],
    )


# Payload helpers


class _Update(StrictModel):
    id: int
    expected_version: int

    @model_validator(mode="after")
    def _changes_something(self):
        if not self.model_fields_set - {"id", "expected_version"}:
            raise ValueError("nothing to change: give at least one field")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True, exclude={"id", "expected_version"})


class _Delete(StrictModel):
    id: int
    expected_version: int


def _partial(name: str, fields: type[BaseModel], doc: str) -> type[_Update]:
    """An update model: every field of `fields` optional; given ones change, null sets null."""
    optional = {
        n: (f.annotation | None, FieldInfo.merge_field_infos(f, default=None))
        for n, f in fields.model_fields.items()
    }
    model = create_model(name, __base__=_Update, **optional)
    model.__doc__ = doc + (
        " Partial: only the fields given change; an explicit null sets the field to null."
        " `expected_version` is the version read with the row."
    )
    return model


def _delete_model(name: str, doc: str) -> type[_Delete]:
    model = create_model(name, __base__=_Delete)
    model.__doc__ = doc + " Rows that depend on it go too, and `undo` brings them all back."
    return model


def _named(change: Change, name: str) -> Change:
    return change.model_copy(update={"operation": name})


def _exercise_id(conn, name: str | None) -> int | None:
    return None if name is None else domain.exercise_ids(conn, {name})[name]


def _week_of_day(conn, day: date) -> set[int]:
    rows = conn.execute(
        "select id from training_week where start_date <= %s and %s < start_date + 7", (day, day)
    ).fetchall()
    return {r[0] for r in rows}


def _week_of_session(conn, session_id: int) -> set[int]:
    row = conn.execute(
        "select week_id, day from planned_session where id = %s", (session_id,)
    ).fetchone()
    if row is None:
        return set()
    return {row[0]} if row[0] is not None else _week_of_day(conn, row[1])


def _session_of_part(conn, part_id: int) -> int | None:
    row = conn.execute("select session_id from session_part where id = %s", (part_id,)).fetchone()
    return row[0] if row else None


def _week_of_part(conn, part_id: int) -> set[int]:
    session_id = _session_of_part(conn, part_id)
    return _week_of_session(conn, session_id) if session_id else set()


def _line(conn, line_id: int) -> tuple[int, str] | None:
    row = conn.execute(
        "select part_id, origin from session_exercise where id = %s", (line_id,)
    ).fetchone()
    return (row[0], row[1]) if row else None


def _week_of_planned_line(conn, line_id: int) -> set[int]:
    found = _line(conn, line_id)
    return _week_of_part(conn, found[0]) if found and found[1] == "planned" else set()


def _ids(conn, sql: str, params: tuple = ()) -> set[int]:
    return {r[0] for r in conn.execute(sql, params).fetchall()}


def _live_weeks(conn) -> set[int]:
    """The weeks not over yet: what a change of the rules or of the bank can still affect."""
    return _ids(conn, "select id from training_week where start_date + 6 >= current_date")


def _weeks_of(conn, column: str, row_id: int) -> set[int]:
    """The weeks of a cycle or a block (`column` is cycle_id or block_id, never a payload)."""
    return _ids(conn, f"select id from training_week where {column} = %s", (row_id,))


def _week_after(conn, cycle_id: int, number: int) -> set[int]:
    """The week that follows `number` in its cycle: the guardrail reads the week before it."""
    return _ids(
        conn,
        "select id from training_week where cycle_id = %s and number = %s",
        (cycle_id, number + 1),
    )


def _weeks_around_week(conn, week_id: int) -> set[int]:
    row = conn.execute(
        "select cycle_id, number from training_week where id = %s", (week_id,)
    ).fetchone()
    return _week_after(conn, *row) if row else set()


def _weeks_after_range(conn, column: str, row_id: int) -> set[int]:
    """The weeks of a block or a cycle, and the one right after them (deleting them changes
    the week before it)."""
    row = conn.execute(
        f"select cycle_id, max(number) from training_week where {column} = %s group by cycle_id",
        (row_id,),
    ).fetchone()
    return _weeks_of(conn, column, row_id) | (_week_after(conn, *row) if row else set())


def _weeks_using_exercise(conn, exercise_id: int) -> set[int]:
    sessions = _ids(
        conn,
        "select distinct p.session_id from session_exercise l"
        " join session_part p on p.id = l.part_id"
        " where l.exercise_id = %s and l.origin = 'planned'",
        (exercise_id,),
    )
    return set().union(*(_week_of_session(conn, s) for s in sessions)) if sessions else set()


RULE_OPERATIONS = frozenset({"add_rule", "update_rule", "deactivate_rule"})


def _weeks_of_change(conn, p) -> set[int]:
    """The weeks an undo touches: those of the rows it restores or removes."""
    row = conn.execute(
        "select before, after from change_log where id = %s", (p.change_id,)
    ).fetchone()
    if row is None:
        return set()
    weeks: set[int] = set()
    for image in [RowImage.model_validate(i) for i in row[0] + row[1]]:
        data = image.row or {}
        if image.table == "training_week":
            weeks |= {image.id} | _weeks_around_week(conn, image.id)
        elif image.table == "planned_session":
            weeks |= {data["week_id"]} if data.get("week_id") else _week_of_session(conn, image.id)
        elif image.table == "session_part":
            weeks |= _week_of_session(conn, data["session_id"]) if data else set()
        elif image.table == "session_exercise":
            weeks |= _week_of_part(conn, data["part_id"]) if data else set()
        elif image.table == "block":
            weeks |= _weeks_of(conn, "block_id", image.id)
        elif image.table == "cycle":
            weeks |= _weeks_of(conn, "cycle_id", image.id)
        elif image.table in ("athlete_rule", "exercise"):
            weeks |= _live_weeks(conn)
    return weeks


def _undoes_a_rule(conn, change_id: int) -> bool:
    row = conn.execute("select operation from change_log where id = %s", (change_id,)).fetchone()
    return row is not None and row[0] in RULE_OPERATIONS


# Programme: cycles, blocks, weeks


class CycleFields(StrictModel):
    name: str = Field(min_length=1)
    start_date: date
    end_date: date
    notes: str | None = None
    status: Literal["active", "done", "cancelled"] = "active"


class CreateCycle(CycleFields):
    """Create a training cycle (about three months, made of blocks and weeks)."""


UpdateCycle = _partial("UpdateCycle", CycleFields, "Change a cycle: name, dates, notes, status.")
DeleteCycle = _delete_model("DeleteCycle", "Delete a cycle with its blocks and weeks.")


@_register("create_cycle", CreateCycle, ("cycle",))
def create_cycle(conn, p: CreateCycle, ctx: Context) -> Change:
    img = _insert(conn, "cycle", p.model_dump())
    return Change(
        operation="create_cycle", entity="cycle", entity_id=img.id, before=[], after=[img]
    )


@_register(
    "update_cycle",
    UpdateCycle,
    ("cycle",),
    programme=True,
    weeks=lambda c, p: _weeks_of(c, "cycle_id", p.id),
)
def update_cycle(conn, p, ctx: Context) -> Change:
    return _named(_update(conn, "cycle", p.id, p.expected_version, p.changes()), "update_cycle")


@_register(
    "delete_cycle",
    DeleteCycle,
    ("cycle", "block", "training_week", "planned_session"),
    programme=True,
    weeks=lambda c, p: _weeks_of(c, "cycle_id", p.id),
)
def delete_cycle(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "cycle", p.id, p.expected_version), "delete_cycle")


class BlockFields(StrictModel):
    cycle_id: int
    position: int = Field(ge=1)
    kind: Literal["accumulation", "transmutation", "realisation"]
    start_date: date
    end_date: date
    intent: str | None = None
    target_strength_sessions: int | None = Field(default=None, gt=0)


class CreateBlock(BlockFields):
    """Create a block of a cycle; it ends when its target of strength sessions is reached."""


UpdateBlock = _partial("UpdateBlock", BlockFields, "Change a block: dates, intent, target.")
DeleteBlock = _delete_model("DeleteBlock", "Delete a block with its weeks.")


@_register("create_block", CreateBlock, ("block",))
def create_block(conn, p: CreateBlock, ctx: Context) -> Change:
    img = _insert(conn, "block", p.model_dump())
    return Change(
        operation="create_block", entity="block", entity_id=img.id, before=[], after=[img]
    )


@_register(
    "update_block",
    UpdateBlock,
    ("block",),
    programme=True,
    weeks=lambda c, p: _weeks_of(c, "block_id", p.id),
)
def update_block(conn, p, ctx: Context) -> Change:
    return _named(_update(conn, "block", p.id, p.expected_version, p.changes()), "update_block")


@_register(
    "delete_block",
    DeleteBlock,
    ("block", "training_week", "planned_session"),
    programme=True,
    weeks=lambda c, p: _weeks_after_range(c, "block_id", p.id),
)
def delete_block(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "block", p.id, p.expected_version), "delete_block")


Phase = Literal[
    "reset",
    "reference",
    "volume",
    "volume_peak",
    "deload",
    "strength",
    "intensification",
    "strength_peak",
    "power",
    "density",
    "peak",
    "test",
]


class WeekFields(StrictModel):
    cycle_id: int
    block_id: int | None = None
    number: int = Field(ge=0)
    start_date: date
    phase: Phase
    title: str | None = None
    intent: dict[str, Any] = {}
    review: str | None = None


class CreateWeek(WeekFields):
    """Create a week of a cycle: its phase and the intent for each part of its sessions."""


UpdateWeek = _partial(
    "UpdateWeek", WeekFields, "Change a week: phase, title, intent, or the athlete's review."
)
DeleteWeek = _delete_model("DeleteWeek", "Delete a week; its sessions stay, without a week.")


@_register(
    "create_week",
    CreateWeek,
    ("training_week",),
    programme=True,
    weeks=lambda c, p: _week_after(c, p.cycle_id, p.number),
)
def create_week(conn, p: CreateWeek, ctx: Context) -> Change:
    img = _insert(conn, "training_week", p.model_dump())
    return Change(
        operation="create_week", entity="training_week", entity_id=img.id, before=[], after=[img]
    )


@_register("update_week", UpdateWeek, ("training_week",), programme=True, weeks=lambda c, p: {p.id})
def update_week(conn, p, ctx: Context) -> Change:
    return _named(
        _update(conn, "training_week", p.id, p.expected_version, p.changes()), "update_week"
    )


@_register(
    "delete_week",
    DeleteWeek,
    ("training_week", "planned_session"),
    programme=True,
    weeks=lambda c, p: _weeks_around_week(c, p.id),
)
def delete_week(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "training_week", p.id, p.expected_version), "delete_week")


# Programme: sessions, parts, lines


class CreateSession(SessionIn):
    """Create a session on a day, with its parts and their planned (or done) lines."""


@_register(
    "create_session",
    CreateSession,
    ("planned_session", "session_part", "session_exercise"),
    programme=True,
    weeks=lambda c, p: {p.week_id} if p.week_id else _week_of_day(c, p.day),
)
def create_session(conn, p: CreateSession, ctx: Context) -> Change:
    kinds = [part.kind for part in p.parts]
    twice = sorted({k for k in kinds if kinds.count(k) > 1})
    if twice:
        raise OperationError(
            f"a session holds one part per kind, not two {twice[0]} parts: put their"
            " exercises in one"
        )
    session_id = domain.create_session(conn, p, ctx.source)
    images = [_image(conn, "planned_session", session_id)]
    for (part_id,) in conn.execute(
        "select id from session_part where session_id = %s order by position", (session_id,)
    ).fetchall():
        images.append(_image(conn, "session_part", part_id))
        lines = conn.execute(
            "select id from session_exercise where part_id = %s order by origin, position",
            (part_id,),
        ).fetchall()
        images += [_image(conn, "session_exercise", line_id) for (line_id,) in lines]
    return Change(
        operation="create_session",
        entity="planned_session",
        entity_id=session_id,
        before=[],
        after=images,
    )


class SessionFields(StrictModel):
    title: str = Field(min_length=1)
    kind: Literal["training", "cardio", "mobility", "rest"]
    week_id: int | None
    notes: str | None
    deviation: str | None


UpdateSession = _partial(
    "UpdateSession", SessionFields, "Change a session's title, kind, week, notes or deviation."
)


@_register(
    "update_session",
    UpdateSession,
    ("planned_session",),
    programme=True,
    weeks=lambda c, p: _week_of_session(c, p.id) | ({p.week_id} if p.week_id else set()),
)
def update_session(conn, p, ctx: Context) -> Change:
    return _named(
        _update(conn, "planned_session", p.id, p.expected_version, p.changes()),
        "update_session",
    )


class MoveSession(StrictModel):
    """Move a planned session to another day; its parts and lines move with it."""

    session_id: int
    new_day: date
    expected_version: int


@_register(
    "move_session",
    MoveSession,
    ("planned_session",),
    programme=True,
    weeks=lambda c, p: _week_of_session(c, p.session_id) | _week_of_day(c, p.new_day),
)
def move_session(conn, p: MoveSession, ctx: Context) -> Change:
    row = _existing(conn, "planned_session", p.session_id, p.expected_version)
    if row["status"] != "planned":
        raise OperationError(f"session {p.session_id} is cancelled: restore it first")
    weeks = _week_of_day(conn, p.new_day)
    change = _update(
        conn,
        "planned_session",
        p.session_id,
        p.expected_version,
        {
            "day": p.new_day,
            "moved_from": row["moved_from"] or row["day"],
            # A session follows its day into the week that contains it.
            "week_id": min(weeks) if weeks else row["week_id"],
        },
    )
    return _named(change, "move_session")


class SessionStatus(StrictModel):
    session_id: int
    expected_version: int


class CancelSession(SessionStatus):
    """Cancel a planned session (it stays in the calendar, marked cancelled)."""


class RestoreSession(SessionStatus):
    """Plan again a cancelled session."""


def _set_status(conn, p: SessionStatus, status: str, name: str) -> Change:
    row = _existing(conn, "planned_session", p.session_id, p.expected_version)
    if row["status"] == status:
        raise OperationError(f"session {p.session_id} is already {status}")
    return _named(
        _update(conn, "planned_session", p.session_id, p.expected_version, {"status": status}),
        name,
    )


@_register(
    "cancel_session",
    CancelSession,
    ("planned_session",),
    programme=True,
    weeks=lambda c, p: _week_of_session(c, p.session_id),
)
def cancel_session(conn, p: CancelSession, ctx: Context) -> Change:
    return _set_status(conn, p, "cancelled", "cancel_session")


@_register(
    "restore_session",
    RestoreSession,
    ("planned_session",),
    programme=True,
    weeks=lambda c, p: _week_of_session(c, p.session_id),
)
def restore_session(conn, p: RestoreSession, ctx: Context) -> Change:
    return _set_status(conn, p, "planned", "restore_session")


DeleteSession = _delete_model("DeleteSession", "Delete a session with its parts and lines.")


@_register(
    "delete_session",
    DeleteSession,
    ("planned_session", "session_part", "session_exercise", "feedback"),
    programme=True,
    weeks=lambda c, p: _week_of_session(c, p.id),
)
def delete_session(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "planned_session", p.id, p.expected_version), "delete_session")


class PartFields(StrictModel):
    kind: PartKind
    title: str | None = None
    notes: str | None = None
    format: MetconFormat | None = None
    duration_minutes: float | None = Field(default=None, gt=0)
    rounds: int | None = Field(default=None, gt=0)
    interval_seconds: int | None = Field(default=None, gt=0)
    target_seconds: int | None = Field(default=None, gt=0)
    target_rounds: float | None = Field(default=None, gt=0)
    result_seconds: int | None = Field(default=None, gt=0)
    result_rounds: float | None = Field(default=None, ge=0)
    result_notes: str | None = None


class AddPart(PartFields):
    """Add a part to a session (warm-up, weightlifting, gymnastics, strength, metcon, cardio,
    mobility): one part per kind, its exercises go inside it (add_line), so a session that
    already has a part of this kind refuses it. It takes its place in the usual order (warm-up,
    mobility, weightlifting, gymnastics, strength, metcon, cardio), the parts after it move
    down; `position` is accepted and ignored, the order decides."""

    session_id: int
    position: int | None = Field(default=None, ge=1)


def _shift_parts(conn, session_id: int, from_position: int, images: list[RowImage]) -> None:
    rows = conn.execute(
        "select id from session_part where session_id = %s and position >= %s"
        " order by position desc",
        (session_id, from_position),
    ).fetchall()
    for (part_id,) in rows:
        images.append(_image(conn, "session_part", part_id))
        conn.execute("update session_part set position = position + 1 where id = %s", (part_id,))


PART_ORDER = ("warmup", "mobility", "weightlifting", "gymnastics", "strength", "metcon", "cardio")


def _one_part_per_kind(conn, session_id: int, kind: str, but: int | None = None) -> None:
    """A session holds one part per kind: its exercises go inside it (add_line)."""
    same = conn.execute(
        "select id from session_part where session_id = %s and kind = %s and id <> %s limit 1",
        (session_id, kind, but or 0),
    ).fetchone()
    if same:
        raise OperationError(
            f"session {session_id} already has a {kind} part (part {same[0]}): add the"
            " exercises to it (add_line), one part per kind"
        )


@_register(
    "add_part",
    AddPart,
    ("session_part",),
    programme=True,
    weeks=lambda c, p: _week_of_session(c, p.session_id),
)
def add_part(conn, p: AddPart, ctx: Context) -> Change:
    _existing(conn, "planned_session", p.session_id)
    parts = conn.execute(
        "select id, kind, position from session_part where session_id = %s order by position",
        (p.session_id,),
    ).fetchall()
    _one_part_per_kind(conn, p.session_id, p.kind)
    # Its place in the usual order: before the first part ranked after it, else last. The order
    # decides, not `position`: a mobility part never lands before the warm-up.
    rank = PART_ORDER.index(p.kind)
    after = [pos for _, kind, pos in parts if PART_ORDER.index(kind) > rank]
    position = min(after) if after else (parts[-1][2] if parts else 0) + 1
    shifted: list[RowImage] = []
    _shift_parts(conn, p.session_id, position, shifted)
    img = _insert(
        conn,
        "session_part",
        p.model_dump(exclude={"position"}) | {"position": position},
    )
    return Change(
        operation="add_part",
        entity="session_part",
        entity_id=img.id,
        before=shifted,
        after=[_image(conn, "session_part", s.id) for s in shifted] + [img],
    )


UpdatePart = _partial(
    "UpdatePart",
    PartFields,
    "Change a part: its kind, title, notes, metcon format and target, or its logged result.",
)


@_register(
    "update_part",
    UpdatePart,
    ("session_part",),
    programme=True,
    weeks=lambda c, p: _week_of_part(c, p.id),
)
def update_part(conn, p, ctx: Context) -> Change:
    changes = p.changes()
    if "kind" in changes:
        part = _existing(conn, "session_part", p.id)
        _one_part_per_kind(conn, part["session_id"], changes["kind"], but=p.id)
    return _named(_update(conn, "session_part", p.id, p.expected_version, changes), "update_part")


DeletePart = _delete_model("DeletePart", "Delete a part of a session with its lines.")


@_register(
    "delete_part",
    DeletePart,
    ("session_part", "session_exercise"),
    programme=True,
    weeks=lambda c, p: _week_of_part(c, p.id),
)
def delete_part(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "session_part", p.id, p.expected_version), "delete_part")


class ReorderParts(StrictModel):
    """Put the parts of a session in a new order: every part id of the session, once.
    `expected_order` is their order as read: refused if it changed since."""

    session_id: int
    part_ids: list[int] = Field(min_length=1)
    expected_order: list[int] = Field(min_length=1)


@_register(
    "reorder_parts",
    ReorderParts,
    ("session_part",),
    programme=True,
    weeks=lambda c, p: _week_of_session(c, p.session_id),
)
def reorder_parts(conn, p: ReorderParts, ctx: Context) -> Change:
    current = [
        r[0]
        for r in conn.execute(
            "select id from session_part where session_id = %s order by position", (p.session_id,)
        ).fetchall()
    ]
    if current != p.expected_order:
        raise StaleRow(f"the parts of session {p.session_id} changed since: now {current}")
    if sorted(current) != sorted(p.part_ids) or len(set(p.part_ids)) != len(p.part_ids):
        raise OperationError(f"give every part of session {p.session_id} once: {current}")
    before = [_image(conn, "session_part", i) for i in current]
    # Two steps: positions are unique within a session.
    for offset, part_id in enumerate(p.part_ids, start=1):
        conn.execute(
            "update session_part set position = %s where id = %s", (1000 + offset, part_id)
        )
    for offset, part_id in enumerate(p.part_ids, start=1):
        conn.execute("update session_part set position = %s where id = %s", (offset, part_id))
    return Change(
        operation="reorder_parts",
        entity="planned_session",
        entity_id=p.session_id,
        before=before,
        after=[_image(conn, "session_part", i) for i in current],
    )


class AddLine(LineIn):
    """Add an exercise line to a part, as prescribed (`planned`) or as done (`done`)."""

    part_id: int
    origin: Literal["planned", "done"] = "planned"


@_register(
    "add_line",
    AddLine,
    ("session_exercise",),
    programme=True,
    weeks=lambda c, p: _week_of_part(c, p.part_id) if p.origin == "planned" else set(),
)
def add_line(conn, p: AddLine, ctx: Context) -> Change:
    _existing(conn, "session_part", p.part_id)
    position = conn.execute(
        "select coalesce(max(position), 0) + 1 from session_exercise"
        " where part_id = %s and origin = %s",
        (p.part_id, p.origin),
    ).fetchone()[0]
    values = p.model_dump(exclude={"exercise"}) | {
        "exercise_id": _exercise_id(conn, p.exercise),
        "position": position,
    }
    img = _insert(conn, "session_exercise", values)
    return Change(
        operation="add_line", entity="session_exercise", entity_id=img.id, before=[], after=[img]
    )


class LineFields(StrictModel):
    exercise: str = Field(min_length=1)
    sets: int | None = Field(default=None, gt=0)
    quantity: float | None = Field(default=None, gt=0)
    unit: Literal["reps", "cal", "m", "s", "min"] = "reps"
    load_kg: float | None = Field(default=None, ge=0)
    load_kg_max: float | None = Field(default=None, ge=0)
    rir: int | None = Field(default=None, ge=0, le=10)
    rest_seconds: int | None = Field(default=None, ge=0)
    notes: str | None = None


UpdateLine = _partial(
    "UpdateLine", LineFields, "Change an exercise line: exercise, sets, quantity, load, RIR, rest."
)


@_register(
    "update_line",
    UpdateLine,
    ("session_exercise",),
    programme=True,
    weeks=lambda c, p: _week_of_planned_line(c, p.id),
)
def update_line(conn, p, ctx: Context) -> Change:
    values = p.changes()
    if "exercise" in values:
        values["exercise_id"] = _exercise_id(conn, values.pop("exercise"))
    return _named(
        _update(conn, "session_exercise", p.id, p.expected_version, values), "update_line"
    )


DeleteLine = _delete_model("DeleteLine", "Delete an exercise line.")


@_register(
    "delete_line",
    DeleteLine,
    ("session_exercise",),
    programme=True,
    weeks=lambda c, p: _week_of_planned_line(c, p.id),
)
def delete_line(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "session_exercise", p.id, p.expected_version), "delete_line")


# What was done


class LoggedPart(StrictModel):
    part_id: int
    # The part's version as read: a log on a part changed since (another log) is refused.
    expected_version: int
    done: list[LineIn] = []
    result_seconds: int | None = Field(default=None, gt=0)
    result_rounds: float | None = Field(default=None, ge=0)
    result_notes: str | None = None


class SessionFeedback(StrictModel):
    rpe: int | None = Field(default=None, ge=1, le=10)
    fatigue: int | None = Field(default=None, ge=1, le=5)
    pain: int | None = Field(default=None, ge=0, le=10)
    pain_location: str | None = None
    notes: str | None = None


class LogSession(StrictModel):
    """Log a session as the athlete did it: the lines done in each part (they replace any
    logged before), the metcon results, and how it felt. One `undo` reverts it all."""

    session_id: int
    parts: list[LoggedPart] = []
    feedback: SessionFeedback | None = None


@_register("log_session", LogSession, ("session_exercise", "session_part", "feedback"))
def log_session(conn, p: LogSession, ctx: Context) -> Change:
    session = _existing(conn, "planned_session", p.session_id)
    before: list[RowImage] = []
    after: list[RowImage] = []
    names = {line.exercise for part in p.parts for line in part.done}
    ids = domain.exercise_ids(conn, names) if names else {}
    for part in p.parts:
        if _session_of_part(conn, part.part_id) != p.session_id:
            raise OperationError(f"part {part.part_id} is not in session {p.session_id}")
        row = _existing(conn, "session_part", part.part_id, part.expected_version)
        if part.done:
            old = conn.execute(
                "select id from session_exercise where part_id = %s and origin = 'done'"
                " order by position",
                (part.part_id,),
            ).fetchall()
            for (line_id,) in old:
                before.append(_image(conn, "session_exercise", line_id))
                conn.execute("delete from session_exercise where id = %s", (line_id,))
            for position, line in enumerate(part.done, start=1):
                after.append(
                    _insert(
                        conn,
                        "session_exercise",
                        line.model_dump(exclude={"exercise"})
                        | {
                            "part_id": part.part_id,
                            "origin": "done",
                            "position": position,
                            "exercise_id": ids[line.exercise],
                        },
                    )
                )
        results = part.model_dump(
            include={"result_seconds", "result_rounds", "result_notes"}, exclude_none=True
        )
        # The part is always updated, so its version moves with every log, done lines alone
        # included: a second log made from the same reading is refused.
        change = _update(
            conn, "session_part", part.part_id, None, results or {"position": row["position"]}
        )
        before += change.before
        after += change.after
    if p.feedback is not None:
        after.append(
            _insert(
                conn,
                "feedback",
                p.feedback.model_dump()
                | {"day": session["day"], "kind": "session", "planned_session_id": p.session_id},
            )
        )
    if not before and not after:
        raise OperationError("nothing to log: give done lines, a result or feedback")
    return Change(
        operation="log_session",
        entity="planned_session",
        entity_id=p.session_id,
        before=before,
        after=after,
    )


class AddFeedback(FeedbackIn):
    """Record how a session felt (RPE, fatigue, pain) or the morning check-in."""


UpdateFeedback = _partial("UpdateFeedback", FeedbackIn, "Change a feedback entry.")
DeleteFeedback = _delete_model("DeleteFeedback", "Delete a feedback entry.")


@_register("add_feedback", AddFeedback, ("feedback",))
def add_feedback(conn, p: AddFeedback, ctx: Context) -> Change:
    img = _insert(conn, "feedback", p.model_dump())
    return Change(
        operation="add_feedback", entity="feedback", entity_id=img.id, before=[], after=[img]
    )


@_register("update_feedback", UpdateFeedback, ("feedback",))
def update_feedback(conn, p, ctx: Context) -> Change:
    return _named(
        _update(conn, "feedback", p.id, p.expected_version, p.changes()), "update_feedback"
    )


@_register("delete_feedback", DeleteFeedback, ("feedback",))
def delete_feedback(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "feedback", p.id, p.expected_version), "delete_feedback")


# Goals


class CreateGoal(GoalIn):
    """Create a goal (a load, a skill, a benchmark) with its dated milestones."""


@_register("create_goal", CreateGoal, ("goal", "goal_milestone"))
def create_goal(conn, p: CreateGoal, ctx: Context) -> Change:
    goal_id = domain.create_goal(conn, p, ctx.source)
    images = [_image(conn, "goal", goal_id)] + [
        _image(conn, "goal_milestone", i)
        for (i,) in conn.execute(
            "select id from goal_milestone where goal_id = %s order by day, id", (goal_id,)
        ).fetchall()
    ]
    return Change(
        operation="create_goal", entity="goal", entity_id=goal_id, before=[], after=images
    )


class GoalFields(StrictModel):
    title: str = Field(min_length=1)
    kind: Literal["strength", "skill", "benchmark", "other"]
    exercise: str | None
    cycle_id: int | None
    unit: str | None
    baseline_value: float | None
    baseline_text: str | None
    baseline_date: date | None
    target_value: float | None
    target_text: str | None
    target_date: date | None
    notes: str | None


UpdateGoal = _partial("UpdateGoal", GoalFields, "Change a goal: its target, date, baseline, notes.")


@_register("update_goal", UpdateGoal, ("goal",))
def update_goal(conn, p, ctx: Context) -> Change:
    values = p.changes()
    if "exercise" in values:
        values["exercise_id"] = _exercise_id(conn, values.pop("exercise"))
    return _named(_update(conn, "goal", p.id, p.expected_version, values), "update_goal")


class SetGoalStatus(StrictModel):
    """Mark a goal achieved or abandoned, or active again."""

    id: int
    expected_version: int
    status: Literal["active", "achieved", "abandoned"]


@_register("set_goal_status", SetGoalStatus, ("goal",))
def set_goal_status(conn, p: SetGoalStatus, ctx: Context) -> Change:
    return _named(
        _update(conn, "goal", p.id, p.expected_version, {"status": p.status}), "set_goal_status"
    )


DeleteGoal = _delete_model("DeleteGoal", "Delete a goal with its milestones.")


@_register("delete_goal", DeleteGoal, ("goal", "goal_milestone"))
def delete_goal(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "goal", p.id, p.expected_version), "delete_goal")


class AddMilestone(MilestoneIn):
    """Add a dated step toward a goal (a value or a text)."""

    goal_id: int


@_register("add_milestone", AddMilestone, ("goal_milestone",))
def add_milestone(conn, p: AddMilestone, ctx: Context) -> Change:
    _existing(conn, "goal", p.goal_id)
    img = _insert(conn, "goal_milestone", p.model_dump())
    return Change(
        operation="add_milestone", entity="goal_milestone", entity_id=img.id, before=[], after=[img]
    )


class MilestoneFields(StrictModel):
    day: date
    label: str | None
    value: float | None
    value_text: str | None


UpdateMilestone = _partial("UpdateMilestone", MilestoneFields, "Change a milestone.")
DeleteMilestone = _delete_model("DeleteMilestone", "Delete a milestone.")


@_register("update_milestone", UpdateMilestone, ("goal_milestone",))
def update_milestone(conn, p, ctx: Context) -> Change:
    return _named(
        _update(conn, "goal_milestone", p.id, p.expected_version, p.changes()), "update_milestone"
    )


@_register("delete_milestone", DeleteMilestone, ("goal_milestone",))
def delete_milestone(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "goal_milestone", p.id, p.expected_version), "delete_milestone")


# Records


RecordType = Literal[
    "rep_max", "max_reps", "max_load", "max_distance", "max_time", "time", "rounds"
]


class RecordFields(StrictModel):
    name: str = Field(min_length=1)
    kind: Literal["lift", "gym", "cardio", "benchmark"]
    family: str | None = None
    record_type: RecordType
    unit: str | None = None
    description: str | None = None
    exercise: str | None = None


class CreateRecordDefinition(RecordFields):
    """Add something that can hold a record (a lift, a gymnastics skill, a cardio distance, a
    benchmark workout), under its kind and family."""


UpdateRecordDefinition = _partial(
    "UpdateRecordDefinition", RecordFields, "Change a record's definition."
)
DeleteRecordDefinition = _delete_model(
    "DeleteRecordDefinition", "Delete a record's definition with its entries."
)


def _record_values(values: dict, conn) -> dict:
    if "exercise" in values:
        values["exercise_id"] = _exercise_id(conn, values.pop("exercise"))
    return values


@_register("create_record_definition", CreateRecordDefinition, ("record_definition",))
def create_record_definition(conn, p: CreateRecordDefinition, ctx: Context) -> Change:
    img = _insert(conn, "record_definition", _record_values(p.model_dump(), conn))
    return Change(
        operation="create_record_definition",
        entity="record_definition",
        entity_id=img.id,
        before=[],
        after=[img],
    )


@_register("update_record_definition", UpdateRecordDefinition, ("record_definition",))
def update_record_definition(conn, p, ctx: Context) -> Change:
    return _named(
        _update(
            conn, "record_definition", p.id, p.expected_version, _record_values(p.changes(), conn)
        ),
        "update_record_definition",
    )


@_register(
    "delete_record_definition", DeleteRecordDefinition, ("record_definition", "record_entry")
)
def delete_record_definition(conn, p, ctx: Context) -> Change:
    return _named(
        _delete(conn, "record_definition", p.id, p.expected_version), "delete_record_definition"
    )


class SetRecord(StrictModel):
    """Record a new best (or correct one): the record by name, the day, and its value (load,
    reps, time in seconds, rounds) or a text; `reps` for a rep max (1 for a 1RM)."""

    record: str = Field(min_length=1)
    day: date
    reps: int | None = Field(default=None, gt=0)
    value: float | None = None
    value_text: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _has_value(self):
        if self.value is None and self.value_text is None:
            raise ValueError("a record needs a value or a value_text")
        return self


@_register("set_record", SetRecord, ("record_entry",))
def set_record(conn, p: SetRecord, ctx: Context) -> Change:
    found = conn.execute("select id from record_definition where name = %s", (p.record,)).fetchone()
    if found is None:
        raise OperationError(f"no record named {p.record!r}: create its definition first")
    img = _insert(
        conn,
        "record_entry",
        p.model_dump(exclude={"record"}) | {"definition_id": found[0], "source": ctx.source},
    )
    return Change(
        operation="set_record", entity="record_entry", entity_id=img.id, before=[], after=[img]
    )


DeleteRecordEntry = _delete_model("DeleteRecordEntry", "Delete a record entry (a wrong one).")


@_register("delete_record_entry", DeleteRecordEntry, ("record_entry",))
def delete_record_entry(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "record_entry", p.id, p.expected_version), "delete_record_entry")


# Profile, health, rules


class AthleteFields(StrictModel):
    first_name: str | None = None
    birth_date: date | None = None
    sex: Literal["male", "female", "other"] | None = None
    height_cm: float | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=30, le=250)
    weight_date: date | None = None
    handedness: Literal["right", "left", "both"] | None = None
    level: Literal["beginner", "intermediate", "advanced", "competitor"] | None = None
    practice_since: date | None = None
    sessions_per_week: int | None = Field(default=None, ge=0, le=14)
    training_places: list[str] | None = None
    context: str | None = None


class UpdateAthlete(AthleteFields):
    """Change the athlete's profile (weight, level, where they train, life context...).
    Partial: only the fields given change; an explicit null clears a field.
    `expected_version` is the profile's version as read (none before the profile exists)."""

    expected_version: int | None = None

    @model_validator(mode="after")
    def _changes_something(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("nothing to change: give at least one field")
        return self


@_register("update_athlete", UpdateAthlete, ("athlete",))
def update_athlete(conn, p: UpdateAthlete, ctx: Context) -> Change:
    values = p.model_dump(exclude_unset=True, exclude={"expected_version"})
    if "training_places" in values and values["training_places"] is None:
        values["training_places"] = []
    if _row(conn, "athlete", 1) is None:
        img = _insert(conn, "athlete", {"id": 1} | values)
        return Change(
            operation="update_athlete", entity="athlete", entity_id=1, before=[], after=[img]
        )
    if p.expected_version is None:
        raise StaleRow("the profile exists: read it and give its expected_version")
    values["updated_at"] = datetime.now(UTC)
    return _named(_update(conn, "athlete", 1, p.expected_version, values), "update_athlete")


class HealthFields(StrictModel):
    body_part: str = Field(min_length=1, max_length=40)
    side: Literal["left", "right", "both"] | None = None
    kind: Literal["pain", "injury", "limitation"]
    description: str = Field(min_length=1, max_length=500)
    guidance: str | None = Field(default=None, max_length=500)
    since: date | None = None


class AddHealthIssue(HealthFields):
    """Record a pain, injury or limitation the athlete declared, in English for `body_part`
    ("knee", "wrist"); the planner respects the active ones. The athlete's words are kept."""

    status: Literal["active", "monitoring"] = "active"


@_register("add_health_issue", AddHealthIssue, ("health_issue",))
def add_health_issue(conn, p: AddHealthIssue, ctx: Context) -> Change:
    img = _insert(
        conn,
        "health_issue",
        p.model_dump() | {"source": ctx.source, "reported_quote": ctx.quote},
    )
    return Change(
        operation="add_health_issue",
        entity="health_issue",
        entity_id=img.id,
        before=[],
        after=[img],
    )


class HealthUpdateFields(HealthFields):
    status: Literal["active", "monitoring"]


UpdateHealthIssue = _partial(
    "UpdateHealthIssue", HealthUpdateFields, "Change a health issue: description, guidance, status."
)


@_register("update_health_issue", UpdateHealthIssue, ("health_issue",))
def update_health_issue(conn, p, ctx: Context) -> Change:
    return _named(
        _update(conn, "health_issue", p.id, p.expected_version, p.changes()), "update_health_issue"
    )


class ResolveHealthIssue(StrictModel):
    """Mark a health issue resolved (the athlete says it no longer hurts)."""

    id: int
    expected_version: int
    resolved_on: date | None = None


@_register("resolve_health_issue", ResolveHealthIssue, ("health_issue",))
def resolve_health_issue(conn, p: ResolveHealthIssue, ctx: Context) -> Change:
    return _named(
        _update(
            conn,
            "health_issue",
            p.id,
            p.expected_version,
            {"status": "resolved", "resolved_on": p.resolved_on or date.today()},
        ),
        "resolve_health_issue",
    )


DeleteHealthIssue = _delete_model("DeleteHealthIssue", "Delete a health issue entered by mistake.")


@_register("delete_health_issue", DeleteHealthIssue, ("health_issue",))
def delete_health_issue(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "health_issue", p.id, p.expected_version), "delete_health_issue")


class AddRule(RuleIn):
    """Add a permanent rule of the athlete (context for the coach; a `code` the guardrail
    knows makes it checked in code)."""


@_register(
    "add_rule",
    AddRule,
    ("athlete_rule",),
    programme=True,
    weeks=lambda c, p: _live_weeks(c),
    report=True,
)
def add_rule(conn, p: AddRule, ctx: Context) -> Change:
    img = _insert(conn, "athlete_rule", p.model_dump())
    return Change(
        operation="add_rule", entity="athlete_rule", entity_id=img.id, before=[], after=[img]
    )


class RuleFields(StrictModel):
    code: str | None
    text: str = Field(min_length=1)
    params: dict[str, Any]
    active: bool


UpdateRule = _partial("UpdateRule", RuleFields, "Change a rule's text, parameters or activity.")


@_register(
    "update_rule",
    UpdateRule,
    ("athlete_rule",),
    programme=True,
    weeks=lambda c, p: _live_weeks(c),
    report=True,
)
def update_rule(conn, p, ctx: Context) -> Change:
    return _named(
        _update(conn, "athlete_rule", p.id, p.expected_version, p.changes()), "update_rule"
    )


class DeactivateRule(StrictModel):
    """Stop applying a rule (kept, inactive)."""

    id: int
    expected_version: int


@_register(
    "deactivate_rule",
    DeactivateRule,
    ("athlete_rule",),
    programme=True,
    weeks=lambda c, p: _live_weeks(c),
    report=True,
)
def deactivate_rule(conn, p: DeactivateRule, ctx: Context) -> Change:
    return _named(
        _update(conn, "athlete_rule", p.id, p.expected_version, {"active": False}),
        "deactivate_rule",
    )


# Exercise bank


class AddExercise(ExerciseIn):
    """Add a movement to the exercise bank."""


@_register("add_exercise", AddExercise, ("exercise",))
def add_exercise(conn, p: AddExercise, ctx: Context) -> Change:
    if conn.execute("select 1 from exercise where name = %s", (p.name,)).fetchone():
        raise OperationError(f"{p.name!r} is already in the bank")
    img = _insert(conn, "exercise", p.model_dump())
    return Change(
        operation="add_exercise", entity="exercise", entity_id=img.id, before=[], after=[img]
    )


UpdateExercise = _partial("UpdateExercise", ExerciseIn, "Change a movement of the bank.")


@_register(
    "update_exercise",
    UpdateExercise,
    ("exercise",),
    programme=True,
    weeks=lambda c, p: _weeks_using_exercise(c, p.id),
)
def update_exercise(conn, p, ctx: Context) -> Change:
    return _named(
        _update(conn, "exercise", p.id, p.expected_version, p.changes()), "update_exercise"
    )


DeleteExercise = _delete_model(
    "DeleteExercise", "Delete a movement of the bank; refused while a line or a goal uses it."
)


@_register("delete_exercise", DeleteExercise, ("exercise",))
def delete_exercise(conn, p, ctx: Context) -> Change:
    return _named(_delete(conn, "exercise", p.id, p.expected_version), "delete_exercise")


# Garmin annotations


class AnnotateActivity(StrictModel):
    """Correct or explain a Garmin activity without editing it: the field, the right value,
    a note (the raw data stays as the watch recorded it)."""

    activity_id: int
    field: str = Field(min_length=1, max_length=60)
    value: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _says_something(self):
        if self.value is None and self.note is None:
            raise ValueError("an annotation needs a value or a note")
        return self


@_register("annotate_activity", AnnotateActivity, ("activity_annotation",))
def annotate_activity(conn, p: AnnotateActivity, ctx: Context) -> Change:
    img = _insert(conn, "activity_annotation", p.model_dump() | {"source": ctx.source})
    return Change(
        operation="annotate_activity",
        entity="activity_annotation",
        entity_id=img.id,
        before=[],
        after=[img],
    )


DeleteAnnotation = _delete_model("DeleteAnnotation", "Delete an annotation of a Garmin activity.")


@_register("delete_annotation", DeleteAnnotation, ("activity_annotation",))
def delete_annotation(conn, p, ctx: Context) -> Change:
    return _named(
        _delete(conn, "activity_annotation", p.id, p.expected_version), "delete_annotation"
    )


# Undo


class Undo(StrictModel):
    """Revert one change the coach applied (by its change id): what it created is deleted,
    what it deleted comes back, what it changed is restored. Refused when those rows changed
    since. An undo is not undone: "redo" is a new instruction."""

    change_id: int


@_register("undo", Undo, (), short_quote=True, programme=True, weeks=_weeks_of_change)
def undo(conn, p: Undo, ctx: Context) -> Change:
    row = conn.execute(
        "select c.proposal_id, c.operation, c.entity, c.entity_id, c.before, c.after,"
        " p.undone_by from change_log c join proposal p on p.id = c.proposal_id"
        " where c.id = %s for update of p",
        (p.change_id,),
    ).fetchone()
    if row is None:
        raise OperationError(f"change {p.change_id} does not exist")
    proposal_id, operation, entity, entity_id, before, after, undone_by = row
    if undone_by is not None:
        raise OperationError(f"change {p.change_id} was already undone")
    if operation == "undo":
        raise OperationError("an undo is not undone: say again what you want")
    original = Change(
        operation=operation,
        entity=entity,
        entity_id=entity_id,
        before=[RowImage.model_validate(i) for i in before],
        after=[RowImage.model_validate(i) for i in after],
    )
    return revert(conn, original).model_copy(update={"undoes": proposal_id})


def _violation(v: Any) -> dict[str, Any]:
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json")
    return {"message": getattr(v, "message", str(v))}


# The entry point


def _replayed(conn, key: str, name: str, proposal_id: int | None) -> Change | None:
    """The change a retry with the same idempotency key already made, if any."""
    done = conn.execute(
        "select status, result, kind from proposal where idempotency_key = %s", (key,)
    ).fetchone()
    if done is None:
        return None
    if proposal_id is None and done[2] != name:
        raise OperationError(f"key {key!r} was used for {done[2]}, not {name}")
    if done[0] != "applied":
        raise OperationError(f"this request was already made and ended {done[0]}")
    return Change.model_validate(done[1])


def _check_message(conn, conversation_id: str, message_id: int) -> None:
    """Only the message being answered, the athlete's latest in the conversation, authorises."""
    latest = conn.execute(
        "select max(id) from conversation_message where conversation_id = %s and role = 'athlete'",
        (conversation_id,),
    ).fetchone()[0]
    if latest is None or latest != message_id:
        raise OperationError(
            f"message {message_id} is not the athlete's latest message in conversation"
            f" {conversation_id!r}: only the message being answered can authorise a change"
        )


def _picked(conn, proposal_id: int, conversation_id: str, message_id: int) -> tuple[str, Any]:
    """The operation and payload of the suggestion the athlete picks, locked for this change."""
    found = conn.execute(
        "select kind, payload, status, presented_in from proposal where id = %s for update",
        (proposal_id,),
    ).fetchone()
    if found is None:
        raise OperationError(f"suggestion {proposal_id} does not exist")
    if found[2] == "expired":
        raise OperationError(
            f"suggestion {proposal_id} expired: the coach's latest message did not present it;"
            " present it again for the athlete to answer"
        )
    if found[2] != "pending":
        raise OperationError(f"suggestion {proposal_id} is {found[2]}, not pending")
    # The athlete can only pick what the coach's latest message showed them: not an older
    # suggestion, nor one made during this turn (by a model misled into suggesting and
    # accepting at once), which no message has presented yet (audit N7).
    shown = conn.execute(
        "select max(id) from conversation_message"
        " where conversation_id = %s and role = 'coach' and id < %s",
        (conversation_id, message_id),
    ).fetchone()[0]
    if found[3] is None or found[3] != shown:
        raise OperationError(
            f"suggestion {proposal_id} was not presented in the coach's last message:"
            " the athlete has not seen it there, present it again"
        )
    return found[0], found[1]


def _apply_checked(conn, op: Operation, model: Any, ctx: Context) -> Change:
    """Apply `op`, then hold it to the guardrail on the weeks it touches: a change that
    introduces a violation is refused, a change of the rules reports it (see Operation)."""
    weeks: set[int] = set()
    before: dict[int, list] = {}
    if op.programme:
        if _programme_check is None:
            raise OperationError("no rule check registered: the programme cannot change")
        weeks = {w for w in op.weeks(conn, model) if w is not None} if op.weeks else set()
        before = {w: _programme_check[0](conn, w) for w in weeks}
    try:
        change = op.apply(conn, model, ctx).model_copy(update={"operation": op.name})
    except psycopg.errors.IntegrityError as exc:
        raise OperationError(f"refused by the database: {exc.diag.message_primary}") from None
    if not weeks:
        return change
    new = []
    # A week the change deleted has nothing left to check.
    for week in sorted(
        _ids(conn, "select id from training_week where id = any(%s)", (list(weeks),))
    ):
        new += _programme_check[1](before[week], _programme_check[0](conn, week))
    report = op.report or (op.name == "undo" and _undoes_a_rule(conn, model.change_id))
    if new and not report:
        raise RuleViolation(new)
    if new:
        change = change.model_copy(update={"violations": [_violation(v) for v in new]})
    return change


def _record(conn, change: Change, model: Any, *, trace: dict, proposal_id: int | None) -> None:
    """The trace: the proposal (the picked suggestion, or a new applied one) and the change log
    row `undo` rebuilds from; the database refuses the coach's commit without them."""
    trace = trace | {"result": Jsonb(change.model_dump(mode="json"))}
    try:
        if proposal_id is not None:
            conn.execute(
                "update proposal set status = 'applied', decided_at = now(), applied_at = now(),"
                " quote = %(quote)s, message_id = %(message_id)s,"
                " idempotency_key = %(idempotency_key)s, result = %(result)s where id = %(id)s",
                trace | {"id": proposal_id},
            )
            applied_id = proposal_id
        else:
            applied_id = conn.execute(
                "insert into proposal (kind, payload, rationale, author, status, decided_at,"
                " applied_at, quote, message_id, idempotency_key, result) values"
                " (%(kind)s, %(payload)s, %(rationale)s, %(author)s, 'applied', now(), now(),"
                " %(quote)s, %(message_id)s, %(idempotency_key)s, %(result)s) returning id",
                trace | {"kind": change.operation, "payload": Jsonb(model.model_dump(mode="json"))},
            ).fetchone()[0]
    except psycopg.errors.UniqueViolation:
        # The same request, retried while the first call was still running: that one wins.
        raise OperationError(
            "this request is being applied by another call: retry it to get its result"
        ) from None
    conn.execute(
        "insert into change_log (proposal_id, operation, entity, entity_id, before, after)"
        " values (%s, %s, %s, %s, %s, %s)",
        (
            applied_id,
            change.operation,
            change.entity,
            change.entity_id,
            Jsonb([i.model_dump(mode="json") for i in change.before]),
            Jsonb([i.model_dump(mode="json") for i in change.after]),
        ),
    )
    if change.undoes is not None:
        conn.execute(
            "update proposal set undone_by = %s where id = %s", (applied_id, change.undoes)
        )


def run(
    conn: psycopg.Connection,
    name: str,
    payload: dict[str, Any] | None,
    *,
    conversation_id: str,
    quote: str,
    message_id: int,
    idempotency_key: str,
    author: str,
    rationale: str = "",
    proposal_id: int | None = None,
) -> Change:
    """Apply one operation for the athlete, all or nothing (see the module docstring).

    `message_id` must be the athlete's latest message in `conversation_id`, the one being
    answered: an older message, another conversation's or the coach's own cannot authorise a
    change, even if the quote is in it. With `proposal_id`, the pending suggestion of that id is
    applied (its operation and payload), on the same proposal row. `idempotency_key` is derived
    by the caller (the conversation endpoint: message id and tool-call index), never by a model.
    """
    with conn.transaction():
        replayed = _replayed(conn, idempotency_key, name, proposal_id)
        if replayed is not None:
            return replayed
        _check_message(conn, conversation_id, message_id)
        if proposal_id is not None:
            name, payload = _picked(conn, proposal_id, conversation_id, message_id)
        op = CATALOGUE.get(name)
        if op is None:
            raise OperationError(f"unknown operation: {name}")
        verify_quote(conn, message_id, quote, short_ok=op.short_quote or proposal_id is not None)
        model = op.payload.model_validate(payload or {})
        source = "athlete" if author == "athlete" else "agent"
        change = _apply_checked(conn, op, model, Context(source=source, quote=quote))
        trace = {
            "quote": quote,
            "message_id": message_id,
            "idempotency_key": idempotency_key,
            "rationale": rationale or quote,
            "author": author,
        }
        _record(conn, change, model, trace=trace, proposal_id=proposal_id)
    return change


def present(
    conn: psycopg.Connection,
    *,
    conversation_id: str,
    coach_message_id: int,
    proposal_ids: list[int],
) -> None:
    """The coach's message `coach_message_id` showed these pending suggestions: only they can be
    accepted with the athlete's next message (an expired one presented again is pending again).
    Any other pending suggestion shown earlier in this conversation expires (no lifetime: the
    conversation moving on is what ends it). Called once per coach message, in the transaction
    that stores it, with an empty list when it showed none."""
    with conn.transaction():
        said = conn.execute(
            "select conversation_id, role from conversation_message where id = %s",
            (coach_message_id,),
        ).fetchone()
        if said != (conversation_id, "coach"):
            raise OperationError(
                f"message {coach_message_id} is not the coach's in conversation {conversation_id!r}"
            )
        conn.execute(
            "update proposal set status = 'expired', decided_at = now()"
            " where status = 'pending' and not (id = any(%s)) and presented_in in"
            " (select id from conversation_message where conversation_id = %s)",
            (proposal_ids, conversation_id),
        )
        # Presented again, an expired suggestion is back in front of the athlete.
        conn.execute(
            "update proposal set presented_in = %s, status = 'pending', decided_at = null"
            " where status in ('pending', 'expired') and id = any(%s)",
            (coach_message_id, proposal_ids),
        )


def suggest(
    conn: psycopg.Connection, name: str, payload: dict[str, Any], *, rationale: str, author: str
) -> int:
    """Record a suggestion of the coach as a pending proposal: validated now, applied only when
    the athlete picks it (`run(..., proposal_id=...)`)."""
    op = CATALOGUE.get(name)
    if op is None:
        raise OperationError(f"unknown operation: {name}")
    if not rationale.strip():
        raise OperationError("a suggestion needs a rationale")
    model = op.payload.model_validate(payload)
    return conn.execute(
        "insert into proposal (kind, payload, rationale, author) values (%s, %s, %s, %s)"
        " returning id",
        (name, Jsonb(model.model_dump(mode="json")), rationale, author),
    ).fetchone()[0]
