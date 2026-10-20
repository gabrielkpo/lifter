"""Roles and grants (src/lifter/sql/roles.sql): each login role can do exactly what it needs.

The matrix is checked with has_table_privilege (which follows role membership), then the real
code paths run under SET ROLE: a Garmin sync as lifter_sync, a proposal as lifter_agents, reads
as lifter_api, and every write outside a role's scope is refused.
"""

from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from lifter import domain
from lifter.conversation import start
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
        # Not the agents' audit, the conversation nor the change log (audit N5).
        "public.agent_run": set(),
        "public.agent_step": set(),
        "public.conversation": set(),
        "public.conversation_message": set(),
        "public.change_log": set(),
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
    "lifter_backup": {
        "public.raw_garmin_payload": {READ},
        "public.planned_session": {READ},
        "public.schema_migrations": {READ},
        "public.agent_run": {READ},
        "public.agent_step": {READ},
        "public.conversation": {READ},
        "public.conversation_message": {READ},
        "public.change_log": {READ},
        "analytics.daily_metrics": {READ},
    },
    "lifter_coach": {
        "public.planned_session": {READ, INSERT, UPDATE, DELETE},
        "public.session_exercise": {READ, INSERT, UPDATE, DELETE},
        "public.health_issue": {READ, INSERT, UPDATE, DELETE},
        "public.athlete": {READ, INSERT, UPDATE, DELETE},
        "public.record_entry": {READ, INSERT, UPDATE, DELETE},
        "public.change_log": {READ, INSERT},
        # Update on the status and trace columns only (column grants).
        "public.proposal": {READ, INSERT},
        "public.conversation": {READ},
        "public.conversation_message": {READ, INSERT},
        "public.agent_run": {READ, INSERT},
        "public.raw_garmin_payload": {READ},
        "public.sync_log": {READ},
        "public.schema_migrations": {READ},
        "analytics.daily_metrics": {READ},
    },
    "lifter_chat": {
        "public.conversation": {READ, INSERT},
        "public.conversation_message": {READ, INSERT},
        "public.proposal": {READ},
        "public.agent_run": set(),
        "public.change_log": set(),
        "public.planned_session": {READ},
        "analytics.daily_metrics": {READ},
    },
    "lifter_agents": {
        # Insert on its kind, payload, rationale and author only (column grants).
        "public.proposal": {READ},
        "public.agent_run": {READ, INSERT},
        "public.agent_step": {READ, INSERT},
        "public.conversation": set(),
        "public.conversation_message": set(),
        "public.change_log": set(),
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
        " where grantee in ('lifter_api', 'lifter_sync', 'lifter_agents', 'lifter_backup',"
        " 'lifter_coach', 'lifter_chat')"
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


def test_an_agent_proposes_only_a_pending_suggestion(database_url):
    # Security review of #72: the agents' role cannot plant an applied proposal or backdate one.
    with as_role(database_url, "lifter_agents") as agents:
        agents.execute(
            "insert into proposal (kind, payload, rationale, author)"
            " values ('add_rule', '{}', 'why', 'planner')"
        )
        for column, value in (("status", "applied"), ("created_at", "2020-01-01")):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                agents.execute(
                    f"insert into proposal (kind, payload, rationale, author, {column})"
                    " values ('add_rule', '{}', 'why', 'planner', %s)",
                    (value,),
                )


def test_lifter_api_only_reads(database_url):
    with as_role(database_url, "lifter_api") as api_conn:
        assert api_conn.execute("select count(*) from analytics.daily_metrics").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api_conn.execute("insert into exercise (name, category) values ('x', 'other')")


def test_grants_survive_the_views_being_recreated(conn):
    # A changed dbt project rebuilds the analytics schema; roles.sql must run again after it.
    conn.execute("update public.schema_views set sha256 = 'changed' where name = 'dbt'")
    migrate(conn)
    assert privileges(conn, "lifter_sync", "analytics.stg_activity") == {READ}
    assert privileges(conn, "lifter_api", "analytics.daily_metrics") == {READ}


def test_a_database_granted_before_loses_the_agents_table_wide_insert(conn):
    # roles.sql runs on a database that already holds earlier grants (Neon): the agents' old
    # insert on the whole proposal table must go, not only a new column grant come (v0.1.2).
    conn.execute("grant insert on proposal to lifter_propose")
    assert INSERT in privileges(conn, "lifter_agents", "public.proposal")
    conn.execute("update public.schema_views set sha256 = 'changed' where name = 'roles.sql'")
    migrate(conn)
    assert INSERT not in privileges(conn, "lifter_agents", "public.proposal")
    column = "select has_column_privilege('lifter_agents', 'proposal', %s, 'INSERT')"
    assert conn.execute(column, ("payload",)).fetchone() == (True,)
    assert conn.execute(column, ("status",)).fetchone() == (False,)


def test_login_roles_carry_their_guards(conn):
    # SET ROLE does not apply per-role settings: check them where Postgres stores them.
    settings = dict(
        conn.execute(
            "select rolname, rolconfig from pg_roles"
            " where rolname in ('lifter_api', 'lifter_sync', 'lifter_agents', 'lifter_backup',"
            " 'lifter_coach', 'lifter_chat')"
        ).fetchall()
    )
    assert "default_transaction_read_only=on" in settings["lifter_api"]
    assert "statement_timeout=10s" in settings["lifter_api"]
    assert "statement_timeout=60s" in settings["lifter_sync"]
    assert "statement_timeout=30s" in settings["lifter_agents"]
    assert "default_transaction_read_only=on" in settings["lifter_backup"]
    assert "statement_timeout=30s" in settings["lifter_coach"]
    assert "statement_timeout=10s" in settings["lifter_chat"]


def test_the_coach_updates_only_the_status_and_trace_of_a_proposal(conn):
    column = "select has_column_privilege('lifter_coach', 'proposal', %s, 'UPDATE')"
    assert conn.execute(column, ("status",)).fetchone() == (True,)
    assert conn.execute(column, ("quote",)).fetchone() == (True,)
    assert conn.execute(column, ("payload",)).fetchone() == (False,)
    assert conn.execute(column, ("author",)).fetchone() == (False,)


def test_lifter_backup_can_read_every_sequence(conn):
    # pg_dump records sequence values; a dump taken as lifter_backup must be able to read them.
    missing = conn.execute(
        "select sequence_name from information_schema.sequences"
        " where sequence_schema = 'public'"
        " and not has_sequence_privilege('lifter_backup', 'public.' || sequence_name, 'SELECT')"
    ).fetchall()
    assert missing == []


def test_the_athletes_words_reach_only_the_roles_that_need_them(conn, database_url):
    # Audit N5: the API does not read the conversation, the audit nor the change log; the
    # endpoint and the coach read the conversation, and the backup reads every row of it.
    with as_role(database_url, "lifter_chat") as chat:
        start(chat, id="c", title="genou douloureux", source="app")
        said = chat.execute(
            "insert into conversation_message (conversation_id, role, text)"
            " values ('c', 'athlete', 'genou douloureux') returning id"
        ).fetchone()[0]
    for role in ("lifter_coach", "lifter_backup"):
        with as_role(database_url, role) as reader:
            row = reader.execute(
                "select text from conversation_message where id = %s", (said,)
            ).fetchone()
            assert row == ("genou douloureux",), role
    with as_role(database_url, "lifter_api") as api:
        for table in (
            "conversation",
            "conversation_message",
            "agent_run",
            "agent_step",
            "change_log",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                api.execute(f"select count(*) from {table}")


def test_the_coach_writes_every_table_of_the_catalogue_and_no_other(conn):
    from lifter.operations import CATALOGUE

    writable = {t for op in CATALOGUE.values() for t in op.writes}
    for table in sorted(writable):
        assert privileges(conn, "lifter_coach", f"public.{table}") == {
            READ,
            INSERT,
            UPDATE,
            DELETE,
        }, table
    for table in ("raw_garmin_payload", "sync_log", "agent_run", "change_log", "proposal"):
        assert not privileges(conn, "lifter_coach", f"public.{table}") & {UPDATE, DELETE}, table


def test_the_backup_sees_every_row_of_the_conversation(conn, database_url):
    # pg_dump --enable-row-security leaves out, silently, the rows a policy hides: the backup's
    # role must see as many rows as the owner.
    start(conn, id="c", title="a", source="cli")
    conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('c', 'athlete', 'a'), ('c', 'coach', 'b')"
    )
    owner = conn.execute("select count(*) from conversation_message").fetchone()
    with as_role(database_url, "lifter_backup") as backup:
        assert backup.execute("select count(*) from conversation_message").fetchone() == owner


def test_the_backup_dumps_tables_under_row_level_security(conn):
    # pg_dump turns row security off by default and then refuses, for a role that does not own
    # them, the tables that have policies: the daily backup must dump with them on.
    secured = conn.execute(
        "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = 'public' and c.relrowsecurity"
    ).fetchall()
    script = (Path(__file__).parent.parent / "ops" / "lifter-backup.sh").read_text()
    assert secured, "no table has row-level security: drop this test or the flag"
    assert "--enable-row-security" in script
