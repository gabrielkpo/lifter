"""`lifter sync` never attempts DDL with a least-privilege role (lifter.db.ensure_schema)."""

import pytest

from lifter.cli import main
from lifter.db import SchemaOutOfDate, ensure_schema, schema_problems
from test_roles import as_role
from test_sync import FakeCaller, two_days


def stale_views(conn):
    conn.execute("update public.schema_views set sha256 = 'changed' where name = 'views.sql'")


def test_an_up_to_date_schema_has_no_problem(conn):
    assert schema_problems(conn) == []


def test_the_sync_role_checks_and_passes_when_up_to_date(conn, database_url):
    with as_role(database_url, "lifter_sync") as sync_conn:
        assert ensure_schema(sync_conn) == []


def test_the_sync_role_refuses_a_stale_schema_without_touching_it(conn, database_url):
    stale_views(conn)
    with as_role(database_url, "lifter_sync") as sync_conn:
        with pytest.raises(SchemaOutOfDate, match="views.sql changed"):
            ensure_schema(sync_conn)
    row = conn.execute("select sha256 from public.schema_views where name = 'views.sql'")
    assert row.fetchone() == ("changed",)  # nothing was applied


def test_a_missing_analytics_schema_is_a_problem(conn):
    conn.execute("drop schema analytics cascade")
    assert "the analytics views are missing" in schema_problems(conn)
    ensure_schema(conn)  # the owner rebuilds it
    assert schema_problems(conn) == []


def test_the_owner_migrates_on_the_way(conn):
    stale_views(conn)
    ensure_schema(conn)
    assert schema_problems(conn) == []


def test_no_migrate_only_checks_even_for_the_owner(conn):
    stale_views(conn)
    with pytest.raises(SchemaOutOfDate, match="lifter migrate"):
        ensure_schema(conn, allow_migrate=False)


class FakeMcp:
    """Stands in for lifter.garmin.McpToolCaller in the CLI."""

    def __init__(self, url, token):
        self.caller = FakeCaller(two_days())

    async def __aenter__(self):
        return self.caller

    async def __aexit__(self, *exc):
        return False


def test_the_cli_sync_stops_clearly_on_a_stale_schema(monkeypatch, capsys, conn, database_url):
    stale_views(conn)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("GARMIN_MCP_TOKEN", "test-token")
    monkeypatch.setenv("SYNC_DELAY_SECONDS", "0")
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setattr("lifter.garmin.McpToolCaller", FakeMcp)

    code = main(["sync", "--start", "2026-03-02", "--end", "2026-03-03", "--no-migrate"])

    assert code == 2
    assert "schema out of date: views.sql changed" in capsys.readouterr().out
    assert conn.execute("select count(*) from raw_garmin_payload").fetchone() == (0,)
