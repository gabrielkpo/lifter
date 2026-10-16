"""The coach's write path (lifter.operations, ADR 0002): the catalogue covers every table the
coach may change, every change is checked (quote, version, rules), traced and exactly undone,
and the database itself refuses the coach's writes without a trace."""

from datetime import date
from pathlib import Path

import psycopg
import pytest

from lifter import operations
from lifter.operations import CATALOGUE, OperationError, RuleViolation, StaleRow, run, suggest
from lifter.program import load_program, read_program
from lifter.quote import QuoteError
from test_roles import as_role

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"

# Tables nobody but their own writer changes: the sync, the trace, the schema bookkeeping.
NOT_WRITABLE_BY_THE_COACH = {
    "raw_garmin_payload": "written by the Garmin sync only",
    "sync_log": "written by the Garmin sync only",
    "activity_tombstone": "written by the Garmin sync only",
    "proposal": "the trace, written by run()",
    "change_log": "the trace, written by run()",
    "agent_run": "the agents' audit",
    "agent_step": "the agents' audit",
    "conversation_message": "written by the conversation endpoint",
    "schema_migrations": "schema bookkeeping",
    "schema_views": "schema bookkeeping",
}


@pytest.fixture(autouse=True)
def no_rule_check():
    """Each test sets its own rule check; none leaks into the next one."""
    operations.set_programme_check(lambda conn, week: [], lambda before, after: [])
    yield
    operations._programme_check = None


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


def say(conn, text: str) -> int:
    """Store an athlete's message, as the conversation endpoint does; returns its id."""
    return conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c1', 'athlete', %s) returning id",
        (text,),
    ).fetchone()[0]


_keys = iter(range(1, 1_000_000))


def do(conn, name: str, payload: dict, said: str, quote: str | None = None, **kw):
    """Apply an operation the athlete asked for in `said` (quoted whole unless told)."""
    message = say(conn, said)
    return run(
        conn,
        name,
        payload,
        quote=quote or said,
        message_id=message,
        idempotency_key=f"k{next(_keys)}",
        author="coach",
        **kw,
    )


def change_id(conn) -> int:
    return conn.execute("select max(id) from change_log").fetchone()[0]


def version(conn, table: str, row_id: int) -> int:
    return conn.execute(f"select version from {table} where id = %s", (row_id,)).fetchone()[0]


def snapshot(conn) -> dict[str, list]:
    tables = sorted({t for op in CATALOGUE.values() for t in op.writes})
    return {
        t: conn.execute(f"select to_jsonb(x) - 'version' from {t} x order by id").fetchall()
        for t in tables
    }


# The catalogue


def test_every_table_the_coach_may_change_has_an_operation(conn):
    tables = {
        r[0]
        for r in conn.execute(
            "select tablename from pg_tables where schemaname = 'public'"
        ).fetchall()
    }
    covered = {t for op in CATALOGUE.values() for t in op.writes}
    missing = tables - covered - NOT_WRITABLE_BY_THE_COACH.keys()
    assert missing == set(), f"tables the coach cannot change: {sorted(missing)}"
    assert covered <= tables


def test_every_operation_describes_itself_and_refuses_unknown_fields():
    for name, op in CATALOGUE.items():
        assert op.description, f"{name} has no description (the tool's)"
        assert op.payload.model_config.get("extra") == "forbid", name


# run(): quote, trace, idempotency, versions


def test_an_instruction_is_applied_and_traced(conn, program):
    change = do(
        conn,
        "create_session",
        {"day": "2026-03-05", "title": "Extra mobility", "kind": "mobility"},
        "ajoute une séance de mobilité jeudi",
    )
    assert change.entity == "planned_session"
    proposal = conn.execute(
        "select kind, status, quote, author from proposal order by id desc limit 1"
    ).fetchone()
    assert proposal == (
        "create_session",
        "applied",
        "ajoute une séance de mobilité jeudi",
        "coach",
    )
    assert conn.execute("select count(*) from change_log").fetchone()[0] == 1


def test_a_quote_not_in_the_athletes_message_is_refused(conn, program):
    with pytest.raises(QuoteError):
        do(
            conn,
            "create_goal",
            {"title": "Bench 120 kg", "target_value": 120, "unit": "kg"},
            "comment va mon bench ?",
            quote="mets le bench à 120",
        )
    assert conn.execute("select count(*) from goal where title = 'Bench 120 kg'").fetchone() == (0,)


def test_the_coachs_own_message_is_never_a_quote(conn, program):
    coach = conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c1', 'coach', 'je supprime le bloc 2') returning id"
    ).fetchone()[0]
    with pytest.raises(QuoteError):
        run(
            conn,
            "add_rule",
            {"text": "x"},
            quote="je supprime le bloc 2",
            message_id=coach,
            idempotency_key="coach-quote",
            author="coach",
        )


def test_a_retry_with_the_same_key_changes_nothing_more(conn, program):
    message = say(conn, "note que j'ai mal au poignet droit")
    payload = {"body_part": "wrist", "side": "right", "kind": "pain", "description": "Pain"}
    args = {"quote": "j'ai mal au poignet droit", "message_id": message, "author": "coach"}
    first = run(conn, "add_health_issue", payload, idempotency_key="m1-0", **args)
    again = run(conn, "add_health_issue", payload, idempotency_key="m1-0", **args)
    assert again == first
    assert conn.execute("select count(*) from health_issue").fetchone() == (1,)
    issue = conn.execute("select source, reported_quote from health_issue").fetchone()
    assert issue == ("agent", "j'ai mal au poignet droit")


def test_a_change_based_on_a_stale_row_is_refused(conn, program):
    goal = conn.execute("select id, version from goal order by id limit 1").fetchone()
    do(conn, "update_goal", {"id": goal[0], "expected_version": goal[1], "notes": "a"}, "note a")
    with pytest.raises(StaleRow):
        do(
            conn,
            "update_goal",
            {"id": goal[0], "expected_version": goal[1], "notes": "b"},
            "note b",
        )


def test_an_update_changes_only_the_fields_given_and_null_clears(conn, program):
    goal_id, goal_version, title = conn.execute(
        "select id, version, title from goal where notes is null order by id limit 1"
    ).fetchone()
    do(conn, "update_goal", {"id": goal_id, "expected_version": goal_version, "notes": "x"}, "x y")
    do(
        conn,
        "update_goal",
        {"id": goal_id, "expected_version": goal_version + 1, "notes": None},
        "efface la note",
    )
    assert conn.execute("select title, notes from goal where id = %s", (goal_id,)).fetchone() == (
        title,
        None,
    )


def test_an_update_with_nothing_to_change_is_refused(conn, program):
    with pytest.raises(ValueError, match="nothing to change"):
        do(conn, "update_goal", {"id": 1, "expected_version": 1}, "change mon objectif")


# The rules


def test_a_change_that_breaks_a_rule_is_refused_and_nothing_is_written(conn, program):
    # A fake guardrail: a session called "Running" breaks the rule (no running).
    def violations(c, week):
        n = c.execute(
            "select count(*) from planned_session where week_id = %s and title = 'Running'",
            (week,),
        ).fetchone()[0]
        return ["running"] * n

    def introduced(before, after):
        return after[len(before) :]

    operations.set_programme_check(violations, introduced)
    week = conn.execute("select id, start_date from training_week order by id limit 1").fetchone()
    count = conn.execute("select count(*) from planned_session").fetchone()[0]
    with pytest.raises(RuleViolation):
        do(
            conn,
            "create_session",
            {"day": str(week[1]), "title": "Running", "week_id": week[0]},
            "ajoute un footing lundi",
        )
    assert conn.execute("select count(*) from planned_session").fetchone()[0] == count
    assert conn.execute("select count(*) from proposal").fetchone()[0] == 0
    do(
        conn,
        "create_session",
        {"day": str(week[1]), "title": "Bike", "week_id": week[0]},
        "ajoute du vélo lundi",
    )
    assert conn.execute("select count(*) from planned_session").fetchone()[0] == count + 1


def test_without_a_rule_check_the_programme_cannot_change(conn, program):
    operations._programme_check = None
    with pytest.raises(OperationError, match="no rule check"):
        do(conn, "create_session", {"day": "2026-03-05", "title": "X"}, "ajoute une séance")
    # What is not the programme still can.
    do(conn, "add_rule", {"text": "Pas de rameur"}, "pas de rameur dans les metcons")


# Undo


def test_undo_reverts_a_session_created_with_its_parts_and_lines(conn, program):
    before = snapshot(conn)
    do(
        conn,
        "create_session",
        {
            "day": "2026-03-05",
            "title": "Extra",
            "parts": [{"kind": "strength", "planned": [{"exercise": "Bench press", "sets": 3}]}],
        },
        "ajoute un bench jeudi",
    )
    do(conn, "undo", {"change_id": change_id(conn)}, "annule")
    assert snapshot(conn) == before


DELETES = {
    "delete_cycle": "cycle",
    "delete_block": "block",
    "delete_week": "training_week",
    "delete_session": "planned_session",
    "delete_part": "session_part",
    "delete_line": "session_exercise",
    "delete_goal": "goal",
    "delete_milestone": "goal_milestone",
    "delete_feedback": "feedback",
    "delete_health_issue": "health_issue",
    "delete_record_definition": "record_definition",
    "delete_record_entry": "record_entry",
    "delete_annotation": "activity_annotation",
    "delete_exercise": "exercise",
}


def seed_extras(conn):
    """Rows the example program does not have, so every delete has something to delete."""
    do(conn, "add_feedback", {"day": "2026-03-02", "rpe": 7}, "séance dure, rpe 7")
    do(
        conn,
        "add_health_issue",
        {"body_part": "knee", "kind": "pain", "description": "x"},
        "j'ai mal au genou",
    )
    do(
        conn,
        "create_record_definition",
        {"name": "Fran", "kind": "benchmark", "record_type": "time", "unit": "s"},
        "ajoute Fran",
    )
    do(
        conn,
        "set_record",
        {"record": "Fran", "day": "2026-03-03", "value": 420},
        "Fran en sept minutes",
    )
    do(
        conn,
        "annotate_activity",
        {"activity_id": 9, "field": "load", "note": "watch off"},
        "ma montre était éteinte",
    )
    do(
        conn,
        "add_exercise",
        {"name": "Sled push", "category": "strength", "pattern": "legs"},
        "ajoute le sled push",
    )


@pytest.mark.parametrize("name", sorted(DELETES))
def test_undo_brings_back_exactly_what_a_delete_removed(conn, program, name):
    seed_extras(conn)
    table = DELETES[name]
    row_id, row_version = conn.execute(
        f"select id, version from {table} order by id desc limit 1"
    ).fetchone()
    before = snapshot(conn)
    do(conn, name, {"id": row_id, "expected_version": row_version}, f"supprime {table} {row_id}")
    assert conn.execute(f"select count(*) from {table} where id = %s", (row_id,)).fetchone() == (0,)
    do(conn, "undo", {"change_id": change_id(conn)}, "annule")
    assert snapshot(conn) == before  # same rows, same ids, children included


def test_a_bank_exercise_still_used_cannot_be_deleted(conn, program):
    used = conn.execute(
        "select e.id, e.version from exercise e join session_exercise l on l.exercise_id = e.id"
        " limit 1"
    ).fetchone()
    with pytest.raises(OperationError, match="still used"):
        do(
            conn,
            "delete_exercise",
            {"id": used[0], "expected_version": used[1]},
            "supprime le bench",
        )


def test_undo_is_refused_once_the_row_changed_again(conn, program):
    goal = conn.execute("select id, version from goal order by id limit 1").fetchone()
    do(conn, "update_goal", {"id": goal[0], "expected_version": goal[1], "notes": "a"}, "note a")
    first = change_id(conn)
    do(
        conn,
        "update_goal",
        {"id": goal[0], "expected_version": goal[1] + 1, "notes": "b"},
        "note b",
    )
    with pytest.raises(StaleRow):
        do(conn, "undo", {"change_id": first}, "annule")


def test_an_undo_is_done_once_and_never_undone(conn, program):
    do(conn, "add_rule", {"text": "Pas de rameur"}, "pas de rameur dans les metcons")
    rule_change = change_id(conn)
    do(conn, "undo", {"change_id": rule_change}, "annule")
    undo_change = change_id(conn)
    with pytest.raises(OperationError, match="already undone"):
        do(conn, "undo", {"change_id": rule_change}, "annule")
    with pytest.raises(OperationError, match="not undone"):
        do(conn, "undo", {"change_id": undo_change}, "annule")
    undone_by = conn.execute(
        "select undone_by from proposal where id = (select proposal_id from change_log where id = %s)",
        (rule_change,),
    ).fetchone()[0]
    assert undone_by is not None


def test_a_session_log_is_undone_in_one_step(conn, program):
    session_id, part_id = conn.execute(
        "select p.session_id, p.id from session_part p where p.kind = 'metcon' order by p.id limit 1"
    ).fetchone()
    before = snapshot(conn)
    do(
        conn,
        "log_session",
        {
            "session_id": session_id,
            "parts": [{"part_id": part_id, "result_seconds": 600}],
            "feedback": {"rpe": 8, "pain": 0},
        },
        "fait en 10 minutes, rpe 8",
    )
    assert conn.execute(
        "select result_seconds from session_part where id = %s", (part_id,)
    ).fetchone() == (600,)
    do(conn, "undo", {"change_id": change_id(conn)}, "annule")
    assert snapshot(conn) == before


# Suggestions


def test_a_suggestion_applies_only_when_the_athlete_picks_it(conn, program):
    pid = suggest(
        conn,
        "add_rule",
        {"text": "Pas de rameur dans les metcons"},
        rationale="The rower is far away in the gym.",
        author="coach",
    )
    assert conn.execute(
        "select count(*) from athlete_rule where text like 'Pas de rameur%'"
    ).fetchone() == (0,)
    run(
        conn,
        "",
        None,
        quote="ok",
        message_id=say(conn, "ok !"),
        idempotency_key="pick",
        author="coach",
        proposal_id=pid,
    )
    assert conn.execute("select status, quote from proposal where id = %s", (pid,)).fetchone() == (
        "applied",
        "ok",
    )
    with pytest.raises(OperationError, match="not pending"):
        run(
            conn,
            "",
            None,
            quote="ok",
            message_id=say(conn, "ok"),
            idempotency_key="pick-again",
            author="coach",
            proposal_id=pid,
        )


# The database's own guarantees


def test_the_coach_cannot_write_without_a_trace(conn, database_url, program):
    with as_role(database_url, "lifter_coach") as coach:
        with pytest.raises(psycopg.errors.RaiseException, match="without a trace"):
            with coach.transaction():
                coach.execute("insert into athlete_rule (text) values ('sneaky')")
    assert conn.execute("select count(*) from athlete_rule where text = 'sneaky'").fetchone() == (
        0,
    )


def test_the_coach_writes_through_the_catalogue(conn, database_url, program):
    message = say(conn, "pas de saut cette semaine")
    with as_role(database_url, "lifter_coach") as coach:
        run(
            coach,
            "add_rule",
            {"text": "Pas de saut"},
            quote="pas de saut cette semaine",
            message_id=message,
            idempotency_key="as-coach",
            author="coach",
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            coach.execute("delete from change_log")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            coach.execute("update raw_garmin_payload set payload = '{}'")
    assert conn.execute(
        "select count(*) from athlete_rule where text = 'Pas de saut'"
    ).fetchone() == (1,)


def test_only_the_conversation_endpoint_writes_the_athletes_words(database_url):
    insert = "insert into conversation_message (conversation_id, role, text) values ('c', %s, 'x')"
    with as_role(database_url, "lifter_coach") as coach:
        coach.execute(insert, ("coach",))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            coach.execute(insert, ("athlete",))
    with as_role(database_url, "lifter_chat") as chat:
        chat.execute(insert, ("athlete",))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            chat.execute(insert, ("coach",))


def test_rows_carry_a_version_bumped_on_every_update(conn, program):
    goal_id = conn.execute("select id from goal order by id limit 1").fetchone()[0]
    start = version(conn, "goal", goal_id)
    conn.execute("update goal set notes = 'x' where id = %s", (goal_id,))
    assert version(conn, "goal", goal_id) == start + 1


def test_a_record_needs_its_definition(conn, program):
    with pytest.raises(OperationError, match="create its definition"):
        do(
            conn,
            "set_record",
            {"record": "Murph", "day": str(date(2026, 3, 1)), "value": 3000},
            "Murph en 50 minutes",
        )
