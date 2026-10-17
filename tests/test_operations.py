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


def coach_says(conn, text: str, shown: list[int]) -> int:
    """Store the coach's reply, which presents the suggestions `shown` (as respond() does)."""
    message = conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c1', 'coach', %s) returning id",
        (text,),
    ).fetchone()[0]
    operations.present(conn, conversation_id="c1", coach_message_id=message, proposal_ids=shown)
    return message


_keys = iter(range(1, 1_000_000))


def do(conn, name: str, payload: dict, said: str, quote: str | None = None, **kw):
    """Apply an operation the athlete asked for in `said` (quoted whole unless told)."""
    message = say(conn, said)
    return run(
        conn,
        name,
        payload,
        conversation_id="c1",
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
    with pytest.raises(OperationError, match="latest message"):
        run(
            conn,
            "add_rule",
            {"text": "x"},
            conversation_id="c1",
            quote="je supprime le bloc 2",
            message_id=coach,
            idempotency_key="coach-quote",
            author="coach",
        )


def test_only_the_message_being_answered_authorises_a_change(conn, program):
    # Audit N1: a true quote from an older message, or from another conversation, is refused.
    old = say(conn, "supprime la règle sur le rameur")
    say(conn, "comment va mon squat ?")
    other = conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c2', 'athlete', 'ajoute une règle pas de saut') returning id"
    ).fetchone()[0]
    for message, quote in ((old, "supprime la règle sur le rameur"), (other, "pas de saut")):
        with pytest.raises(OperationError, match="latest message"):
            run(
                conn,
                "add_rule",
                {"text": "Pas de saut"},
                conversation_id="c1",
                quote=quote,
                message_id=message,
                idempotency_key=f"stale-{message}",
                author="coach",
            )
    assert conn.execute("select count(*) from proposal").fetchone() == (0,)


def test_a_retry_with_the_same_key_changes_nothing_more(conn, program):
    message = say(conn, "note que j'ai mal au poignet droit")
    payload = {"body_part": "wrist", "side": "right", "kind": "pain", "description": "Pain"}
    args = {
        "conversation_id": "c1",
        "quote": "j'ai mal au poignet droit",
        "message_id": message,
        "author": "coach",
    }
    first = run(conn, "add_health_issue", payload, idempotency_key="m1-0", **args)
    again = run(conn, "add_health_issue", payload, idempotency_key="m1-0", **args)
    assert again == first
    assert conn.execute("select count(*) from health_issue").fetchone() == (1,)
    issue = conn.execute("select source, reported_quote from health_issue").fetchone()
    assert issue == ("agent", "j'ai mal au poignet droit")


def test_the_profile_is_created_then_changed_at_its_version(conn, program):
    do(conn, "update_athlete", {"weight_kg": 80}, "je pèse 80 kilos")
    with pytest.raises(StaleRow):
        do(conn, "update_athlete", {"weight_kg": 81}, "je pèse 81 kilos")
    do(conn, "update_athlete", {"weight_kg": 81, "expected_version": 1}, "je pèse 81 kilos")
    assert conn.execute("select weight_kg from athlete").fetchone()[0] == 81


def test_a_key_reused_for_another_operation_is_refused(conn, program):
    message = say(conn, "pas de saut, et note mon genou")
    run(
        conn,
        "add_rule",
        {"text": "Pas de saut"},
        conversation_id="c1",
        quote="pas de saut",
        message_id=message,
        idempotency_key="same",
        author="coach",
    )
    with pytest.raises(OperationError, match="was used for add_rule"):
        run(
            conn,
            "add_health_issue",
            {"body_part": "knee", "kind": "pain", "description": "x"},
            conversation_id="c1",
            quote="note mon genou",
            message_id=message,
            idempotency_key="same",
            author="coach",
        )


def test_a_change_based_on_a_stale_row_is_refused(conn, program):
    goal = conn.execute("select id, version from goal order by id limit 1").fetchone()
    do(
        conn,
        "update_goal",
        {"id": goal[0], "expected_version": goal[1], "notes": "a"},
        "note alpha",
    )
    with pytest.raises(StaleRow):
        do(
            conn,
            "update_goal",
            {"id": goal[0], "expected_version": goal[1], "notes": "b"},
            "note bravo",
        )


def test_an_update_changes_only_the_fields_given_and_null_clears(conn, program):
    goal_id, goal_version, title = conn.execute(
        "select id, version, title from goal where notes is null order by id limit 1"
    ).fetchone()
    do(
        conn,
        "update_goal",
        {"id": goal_id, "expected_version": goal_version, "notes": "x"},
        "note x",
    )
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


def running_sessions(c, week):
    """A fake guardrail: each session called "Running" breaks the rule, if the rule is on."""
    rule = c.execute("select count(*) from athlete_rule where active and text = 'Pas de course'")
    n = c.execute(
        "select count(*) from planned_session where week_id = %s and title = 'Running'", (week,)
    ).fetchone()[0]
    return ["running"] * n * min(1, rule.fetchone()[0])


def new_items(before, after):
    return after[len(before) :]


def a_running_session(conn) -> tuple[int, int]:
    """A "Running" session in a week that is not over (rules and the bank check those)."""
    week = conn.execute("select id from training_week order by id limit 1").fetchone()[0]
    conn.execute("update training_week set start_date = current_date where id = %s", (week,))
    change = do(
        conn,
        "create_session",
        {"day": str(date.today()), "title": "Running", "week_id": week},
        "ajoute un footing aujourd'hui",
    )
    return week, change.entity_id


def test_a_new_rule_flags_the_planned_sessions_it_breaks_without_being_refused(conn, program):
    # Audit N9: the rules go through the guardrail too; what a new rule flags in sessions already
    # planned is reported to the coach, which adapts them, rather than refusing the rule.
    a_running_session(conn)
    operations.set_programme_check(running_sessions, new_items)
    change = do(conn, "add_rule", {"text": "Pas de course"}, "plus de course à pied pour moi")
    assert change.violations == [{"message": "running"}]
    assert conn.execute(
        "select count(*) from athlete_rule where text = 'Pas de course'"
    ).fetchone() == (1,)


def test_an_undo_that_brings_back_a_forbidden_session_is_refused(conn, program):
    # Audit N9: undo goes through the guardrail like any change of the programme.
    _, session_id = a_running_session(conn)
    do(conn, "add_rule", {"text": "Pas de course"}, "plus de course à pied pour moi")
    version = conn.execute(
        "select version from planned_session where id = %s", (session_id,)
    ).fetchone()[0]
    do(
        conn,
        "delete_session",
        {"id": session_id, "expected_version": version},
        "supprime le footing",
    )
    deleted = change_id(conn)
    operations.set_programme_check(running_sessions, new_items)
    with pytest.raises(RuleViolation):
        do(conn, "undo", {"change_id": deleted}, "annule")
    assert conn.execute(
        "select count(*) from planned_session where id = %s", (session_id,)
    ).fetchone() == (0,)


def test_without_a_rule_check_the_programme_cannot_change(conn, program):
    operations._programme_check = None
    with pytest.raises(OperationError, match="no rule check"):
        do(conn, "create_session", {"day": "2026-03-05", "title": "X"}, "ajoute une séance")
    # The athlete's rules are part of it now (audit N9); what is not the programme still can.
    with pytest.raises(OperationError, match="no rule check"):
        do(conn, "add_rule", {"text": "Pas de rameur"}, "pas de rameur dans les metcons")
    do(conn, "update_athlete", {"weight_kg": 80}, "je pèse 80 kilos")


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


def test_a_week_an_agent_planned_can_be_deleted_then_brought_back(conn, program):
    # Audit N2: the agent's run keeps its own history (its link to the week is cleared); it is
    # neither copied into the change log nor in the way of the undo.
    week_id, week_version = conn.execute(
        "select id, version from training_week order by id desc limit 1"
    ).fetchone()
    conn.execute(
        "insert into agent_run (agent, trigger, status, target_week_id, context, started_at)"
        " values ('week_planner', 'cli', 'refused', %s, '{\"health\": \"knee\"}', now())",
        (week_id,),
    )
    before = snapshot(conn)
    do(
        conn,
        "delete_week",
        {"id": week_id, "expected_version": week_version},
        "supprime la semaine",
    )
    logged = conn.execute("select before::text from change_log order by id desc limit 1").fetchone()
    assert "agent_run" not in logged[0]
    do(conn, "undo", {"change_id": change_id(conn)}, "annule")
    assert snapshot(conn) == before


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
    do(
        conn,
        "update_goal",
        {"id": goal[0], "expected_version": goal[1], "notes": "a"},
        "note alpha",
    )
    first = change_id(conn)
    do(
        conn,
        "update_goal",
        {"id": goal[0], "expected_version": goal[1] + 1, "notes": "b"},
        "note bravo",
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
        "select undone_by from proposal"
        " where id = (select proposal_id from change_log where id = %s)",
        (rule_change,),
    ).fetchone()[0]
    assert undone_by is not None


def test_a_session_log_is_undone_in_one_step(conn, program):
    session_id, part_id, part_version = conn.execute(
        "select p.session_id, p.id, p.version from session_part p where p.kind = 'metcon'"
        " order by p.id limit 1"
    ).fetchone()
    before = snapshot(conn)
    do(
        conn,
        "log_session",
        {
            "session_id": session_id,
            "parts": [
                {"part_id": part_id, "expected_version": part_version, "result_seconds": 600}
            ],
            "feedback": {"rpe": 8, "pain": 0},
        },
        "fait en 10 minutes, rpe 8",
    )
    assert conn.execute(
        "select result_seconds from session_part where id = %s", (part_id,)
    ).fetchone() == (600,)
    do(conn, "undo", {"change_id": change_id(conn)}, "annule")
    assert snapshot(conn) == before


def test_a_second_log_from_the_same_reading_is_refused(conn, program):
    # Audit N10: a log overwrites nothing it did not read.
    session_id, part_id, version = conn.execute(
        "select p.session_id, p.id, p.version from session_part p where p.kind = 'metcon'"
        " order by p.id limit 1"
    ).fetchone()
    part = {"part_id": part_id, "expected_version": version, "result_seconds": 600}
    do(conn, "log_session", {"session_id": session_id, "parts": [part]}, "fait en 10 minutes")
    with pytest.raises(StaleRow):
        part = part | {"result_seconds": 720}
        do(conn, "log_session", {"session_id": session_id, "parts": [part]}, "fait en 12 minutes")
    assert conn.execute(
        "select result_seconds from session_part where id = %s", (part_id,)
    ).fetchone() == (600,)


def test_parts_reordered_since_they_were_read_are_refused(conn, program):
    session_id, parts = conn.execute(
        "select session_id, array_agg(id order by position) from session_part"
        " group by session_id having count(*) > 1 order by session_id limit 1"
    ).fetchone()
    reversed_ = list(reversed(parts))
    payload = {"session_id": session_id, "part_ids": reversed_, "expected_order": parts}
    do(conn, "reorder_parts", payload, "inverse les parties de la séance")
    with pytest.raises(StaleRow):
        do(conn, "reorder_parts", payload, "inverse les parties de la séance")


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
    coach_says(conn, "Je propose de retirer le rameur des metcons, ok ?", [pid])
    run(
        conn,
        "",
        None,
        conversation_id="c1",
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
            conversation_id="c1",
            quote="ok",
            message_id=say(conn, "ok"),
            idempotency_key="pick-again",
            author="coach",
            proposal_id=pid,
        )


def test_ok_accepts_only_what_the_coachs_last_message_presented(conn, program):
    # Audit N7 (owner's decision of 17/10): no lifetime, the conversation moving on ends it.
    old = suggest(conn, "add_rule", {"text": "Pas de rameur"}, rationale="Far.", author="coach")
    coach_says(conn, "Je propose de retirer le rameur, ok ?", [old])
    say(conn, "parlons plutôt de ma séance de demain")
    new = suggest(conn, "add_rule", {"text": "Pas de saut"}, rationale="Knee.", author="coach")
    coach_says(conn, "Demain, pas de saut, ok ?", [new])
    assert conn.execute("select status from proposal where id = %s", (old,)).fetchone() == (
        "expired",
    )
    with pytest.raises(OperationError, match="expired"):
        run(
            conn,
            "",
            None,
            conversation_id="c1",
            quote="ok",
            message_id=say(conn, "ok"),
            idempotency_key="old",
            author="coach",
            proposal_id=old,
        )
    # A pending suggestion the last message did not show is refused too (the planner's, say).
    shown_before = suggest(conn, "add_rule", {"text": "x"}, rationale="Not shown.", author="coach")
    with pytest.raises(OperationError, match="not presented"):
        run(
            conn,
            "",
            None,
            conversation_id="c1",
            quote="ok",
            message_id=say(conn, "ok"),
            idempotency_key="unshown",
            author="coach",
            proposal_id=shown_before,
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


def test_an_applied_change_keeps_the_words_that_authorised_it(conn, database_url, program):
    # Audit N6: the coach's role may not rewrite the quote of a change already applied.
    do(conn, "add_rule", {"text": "Pas de saut"}, "pas de saut cette semaine")
    applied = conn.execute("select max(id) from proposal").fetchone()[0]
    with as_role(database_url, "lifter_coach") as coach:
        with pytest.raises(psycopg.errors.RaiseException, match="cannot change"):
            coach.execute("update proposal set quote = 'oui' where id = %s", (applied,))
    assert conn.execute("select quote from proposal where id = %s", (applied,)).fetchone() == (
        "pas de saut cette semaine",
    )


def test_a_pending_suggestion_given_a_quote_by_hand_is_no_trace(conn, database_url, program):
    pid = suggest(conn, "add_rule", {"text": "x"}, rationale="Why not.", author="coach")
    message = say(conn, "pas de saut")
    with as_role(database_url, "lifter_coach") as coach:
        with pytest.raises(psycopg.errors.RaiseException, match="without a trace"):
            with coach.transaction():
                coach.execute(
                    "update proposal set quote = 'pas de saut', message_id = %s where id = %s",
                    (message, pid),
                )
                coach.execute(
                    "insert into change_log (proposal_id, operation, entity, before,"
                    " after) values (%s, 'add_rule', 'athlete_rule', '[]', '[]')",
                    (pid,),
                )
                coach.execute("insert into athlete_rule (text) values ('sneaky')")


def test_switching_to_the_group_role_does_not_escape_the_trace(conn, database_url, program):
    with as_role(database_url, "lifter_coach") as coach:
        coach.execute("set role lifter_write")
        with pytest.raises(psycopg.errors.RaiseException, match="without a trace"):
            with coach.transaction():
                coach.execute("insert into athlete_rule (text) values ('sneaky')")


def test_undo_touches_only_the_catalogues_tables(conn, program):
    do(conn, "add_rule", {"text": "Pas de rameur"}, "pas de rameur dans les metcons")
    conn.execute(
        "update change_log set after = jsonb_set(after, '{0,table}', '\"schema_views\"')"
        " where id = %s",
        (change_id(conn),),
    )
    with pytest.raises(OperationError, match="catalogue's tables"):
        do(conn, "undo", {"change_id": change_id(conn)}, "annule")


def test_the_coach_writes_through_the_catalogue(conn, database_url, program):
    message = say(conn, "pas de saut cette semaine")
    with as_role(database_url, "lifter_coach") as coach:
        run(
            coach,
            "add_rule",
            {"text": "Pas de saut"},
            conversation_id="c1",
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


def test_the_real_guardrail_refuses_a_forbidden_movement(conn, program):
    from lifter.agents.week_check import introduced, violations_for_week

    operations.set_programme_check(violations_for_week, introduced)
    part_id, part_version = conn.execute(
        "select p.id, p.version from session_part p join planned_session s on s.id = p.session_id"
        " where s.week_id is not null and p.kind = 'metcon' order by p.id limit 1"
    ).fetchone()
    with pytest.raises(RuleViolation):
        do(
            conn,
            "add_line",
            {"part_id": part_id, "exercise": "Run", "quantity": 400, "unit": "m"},
            "ajoute 400 m de course dans le metcon",
        )
    assert conn.execute(
        "select version from session_part where id = %s", (part_id,)
    ).fetchone() == (part_version,)


def test_a_suggestion_made_after_the_message_cannot_be_picked_by_it(conn, program):
    # A model misled by planted text suggests a change and accepts it in the same turn,
    # quoting the athlete's message that came before the suggestion existed.
    message = say(conn, "ok pour la semaine")
    conn.execute("select pg_sleep(0.01)")
    pid = suggest(conn, "add_rule", {"text": "Sneaky rule"}, rationale="Planted.", author="coach")
    with pytest.raises(OperationError, match="has not seen it"):
        run(
            conn,
            "",
            None,
            conversation_id="c1",
            quote="ok pour la semaine",
            message_id=message,
            idempotency_key="same-turn",
            author="coach",
            proposal_id=pid,
        )
    assert conn.execute("select status from proposal where id = %s", (pid,)).fetchone() == (
        "pending",
    )
