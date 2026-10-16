"""Roles and grants (src/lifter/sql/roles.sql): each login role can do exactly what it needs.

The matrix is checked with has_table_privilege (which follows role membership), then the real
code paths run under SET ROLE: a Garmin sync as lifter_sync, a proposal as lifter_agents, reads
as lifter_api, and every write outside a role's scope is refused.
"""

from contextlib import contextmanager

import psycopg
import pytest

from lifter import domain
from lifter.db import connect, migrate
from synthetic import activity
from test_sync import D1, D2, FakeCaller, listing, run_sync, two_days

READ, INSERT, UPDATE, DELETE = "SELECT", "INSERT", "UPDATE", "DELETE"

# role -> table -> privileges it must have; any privilege not listed must be absent.
MATRIX = {
    "lifter_api": {
        "public.raw_garmin_payload": {READ},
        "public.planned_session": {READ},
        "public.proposal": {READ},
        "public.agent_run": {READ},
        "analytics.daily_metrics": {READ},
        "analytics.week_summary": {READ},
    },
    "lifter_sync": {
        "public.raw_garmin_payload": {READ, INSERT, UPDATE},
        "public.sync_log": {READ, INSERT, UPDATE},
        "public.activity_tombstone": {READ, INSERT, DELETE},
        "analytics.stg_activity": {READ},
        "analytics.stg_activity_listed": {READ},
        "analytics.latest_garmin_payload": {READ},
        "public.schema_migrations": {READ},
        "public.schema_views": {READ},
        "public.planned_session": set(),
        "public.feedback": set(),
        "public.proposal": set(),
        "analytics.daily_metrics": set(),
    },
    "lifter_agents": {
        "public.proposal": {READ, INSERT},
        "public.agent_run": {READ, INSERT},
        "public.agent_step": {READ, INSERT},
        "public.planned_session": {READ},
        "public.goal": {READ},
        "public.raw_garmin_payload": {READ},
        "analytics.daily_metrics": {READ},
    },
}


def privileges(conn, role: str, table: str) -> set[str]:
    return {
        p
        for p in (READ, INSERT, UPDATE, DELETE)
        if conn.execute("select has_table_privilege(%s, %s, %s)", (role, table, p)).fetchone()[0]
    }


@pytest.mark.parametrize("role", sorted(MATRIX))
def test_each_role_has_exactly_its_privileges(conn, role):
    for table, expected in MATRIX[role].items():
        assert privileges(conn, role, table) == expected, f"{role} on {table}"


def test_login_roles_hold_no_privilege_of_their_own(conn):
    direct = conn.execute(
        "select grantee, table_schema || '.' || table_name, privilege_type"
        " from information_schema.role_table_grants"
        " where grantee in ('lifter_api', 'lifter_sync', 'lifter_agents')"
    ).fetchall()
    assert direct == []


def test_no_role_can_change_the_schema(conn):
    for role in MATRIX:
        for schema in ("public", "analytics"):
            row = conn.execute("select has_schema_privilege(%s, %s, 'CREATE')", (role, schema))
            assert row.fetchone() == (False,), f"{role} can create in {schema}"


@contextmanager
def as_role(database_url: str, role: str):
    """A connection acting as `role` (SET ROLE from the test's owner connection)."""
    with connect(database_url) as conn:
        conn.execute(f"set role {role}")
        yield conn


def test_a_garmin_sync_runs_as_lifter_sync(conn, database_url):
    with as_role(database_url, "lifter_sync") as sync_conn:
        report = run_sync(sync_conn, FakeCaller(two_days()), today=D2)
    assert report.counts["error"] == 0
    assert conn.execute("select count(*) from raw_garmin_payload").fetchone()[0] > 0


def test_the_sync_tombstones_and_restores_as_lifter_sync(conn, database_url):
    answers = two_days()
    with as_role(database_url, "lifter_sync") as sync_conn:
        run_sync(sync_conn, FakeCaller(answers), today=D2)
        # The activity disappears from the listing and Garmin answers "not found": tombstoned.
        answers[("get_activities_by_date", 0)] = listing([])
        del answers[("get_activity", 11)]
        run_sync(sync_conn, FakeCaller(answers), today=D2)
        assert sync_conn.execute("select count(*) from activity_tombstone").fetchone()[0] == 1
        # Listed again: restored (a DELETE on the tombstone).
        answers[("get_activities_by_date", 0)] = listing(
            [{"id": 11, "start_time": activity(11, D1, load=90)["start_time_local"]}]
        )
        answers[("get_activity", 11)] = activity(11, D1, load=90)
        run_sync(sync_conn, FakeCaller(answers), today=D2)
        assert sync_conn.execute("select count(*) from activity_tombstone").fetchone()[0] == 0


def test_lifter_sync_cannot_touch_the_program(database_url):
    with as_role(database_url, "lifter_sync") as sync_conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sync_conn.execute("delete from planned_session")


def test_lifter_agents_can_propose_but_not_decide(conn, database_url):
    with as_role(database_url, "lifter_agents") as agent_conn:
        pid = domain.propose(
            agent_conn,
            "create_goal",
            domain.GoalIn(title="Strict press 50 kg", target_value=50, unit="kg").model_dump(
                mode="json"
            ),
            rationale="Synthetic rationale.",
            author="week_planner",
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            domain.decide(agent_conn, pid, approve=True)
    with as_role(database_url, "lifter_agents") as agent_conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agent_conn.execute("insert into goal (title, target_text) values ('x', 'y')")
    assert conn.execute("select status from proposal where id = %s", (pid,)).fetchone() == (
        "pending",
    )


def test_lifter_api_only_reads(database_url):
    with as_role(database_url, "lifter_api") as api_conn:
        assert api_conn.execute("select count(*) from analytics.daily_metrics").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api_conn.execute("insert into exercise (name, category) values ('x', 'other')")


def test_grants_survive_the_views_being_recreated(conn):
    # A changed views.sql recreates the analytics schema; roles.sql must run again after it.
    conn.execute("update public.schema_views set sha256 = 'changed' where name = 'views.sql'")
    migrate(conn)
    assert privileges(conn, "lifter_sync", "analytics.stg_activity") == {READ}
    assert privileges(conn, "lifter_api", "analytics.daily_metrics") == {READ}


def test_login_roles_carry_their_guards(conn):
    # SET ROLE does not apply per-role settings: check them where Postgres stores them.
    settings = dict(
        conn.execute(
            "select rolname, rolconfig from pg_roles"
            " where rolname in ('lifter_api', 'lifter_sync', 'lifter_agents')"
        ).fetchall()
    )
    assert "default_transaction_read_only=on" in settings["lifter_api"]
    assert "statement_timeout=10s" in settings["lifter_api"]
    assert "statement_timeout=60s" in settings["lifter_sync"]
    assert "statement_timeout=30s" in settings["lifter_agents"]
