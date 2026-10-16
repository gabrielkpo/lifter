"""The agents' audit keeps the full context 90 days, then the metrics only (ADR 0002,
migration 010): purge_agent_audit() and who may run it."""

import psycopg
import pytest
from psycopg.types.json import Jsonb

from test_roles import as_role


def run(conn, days_ago: int) -> int:
    """A synthetic agent run with its context, plan, warnings and one attempt."""
    run_id = conn.execute(
        "insert into agent_run (agent, trigger, status, attempts, input_tokens, context, plan,"
        " warnings, started_at) values ('week_planner', 'cli', 'refused', 1, 900, %s, %s, %s,"
        " now() - make_interval(days => %s)) returning id",
        (
            Jsonb({"health": {"pain_location": "knee"}}),
            Jsonb({"summary": "Lighter week"}),
            Jsonb(["pain 5/10 (knee)"]),
            days_ago,
        ),
    ).fetchone()[0]
    conn.execute(
        "insert into agent_step (run_id, attempt, plan, violations, input_tokens)"
        " values (%s, 1, %s, %s, 900)",
        (
            run_id,
            Jsonb({"summary": "Lighter week"}),
            Jsonb([{"check": "stop_rule", "message": "pain 5/10 (knee)", "day": "2026-03-02"}]),
        ),
    )
    return run_id


def test_runs_older_than_90_days_keep_their_metrics_only(conn):
    old, recent = run(conn, 91), run(conn, 30)

    assert conn.execute("select purge_agent_audit()").fetchone() == (1,)

    purged = conn.execute(
        "select context, plan, warnings, purged_at is not null, status, input_tokens"
        " from agent_run where id = %s",
        (old,),
    ).fetchone()
    assert purged == (None, None, [], True, "refused", 900)
    step = conn.execute(
        "select plan, violations, input_tokens from agent_step where run_id = %s", (old,)
    ).fetchone()
    assert step == (None, [{"check": "stop_rule"}], 900)  # the rule's name, not the pain
    kept = conn.execute("select context, purged_at from agent_run where id = %s", (recent,))
    assert kept.fetchone()[1] is None


def test_a_second_purge_changes_nothing(conn):
    run(conn, 120)
    assert conn.execute("select purge_agent_audit()").fetchone() == (1,)
    assert conn.execute("select purge_agent_audit()").fetchone() == (0,)


def test_the_sync_triggers_the_purge_but_cannot_read_the_audit(conn, database_url):
    old = run(conn, 100)
    with as_role(database_url, "lifter_sync") as sync:
        assert sync.execute("select purge_agent_audit()").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sync.execute("select context from agent_run")
    assert conn.execute("select context from agent_run where id = %s", (old,)).fetchone() == (None,)


def test_the_api_cannot_trigger_the_purge(database_url):
    with as_role(database_url, "lifter_api") as api:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("select purge_agent_audit()")
