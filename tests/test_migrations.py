import psycopg

from lifter.db import connect, migrate, migration_files


def test_migrations_are_ordered_and_idempotent(conn):
    names = [name for name, _ in migration_files()]
    assert names == sorted(names)
    assert migrate(conn) == []  # the session fixture already applied everything
    applied = [r[0] for r in conn.execute("select name from schema_migrations order by name")]
    assert applied == names


def test_upgrade_from_views_in_public(conn):
    # A database migrated before the views moved to the analytics schema.
    conn.execute("delete from schema_migrations where name = '004_activity_tombstone.sql'")
    conn.execute("insert into schema_migrations (name) values ('002_staging.sql')")
    conn.execute("create view public.daily_metrics as select 1 as legacy")

    assert migrate(conn) == ["004_activity_tombstone.sql"]
    legacy = conn.execute(
        "select count(*) from information_schema.views where table_schema = 'public'"
    ).fetchone()
    assert legacy == (0,)
    assert conn.execute("select count(*) from daily_metrics").fetchone() == (0,)


def test_unchanged_views_are_not_recreated(conn):
    before = conn.execute("select applied_at from schema_views").fetchone()
    migrate(conn)
    assert conn.execute("select applied_at from schema_views").fetchone() == before


def test_tables_are_created_in_public(conn):
    rows = conn.execute(
        "select table_schema from information_schema.tables"
        " where table_name in ('raw_garmin_payload', 'sync_log', 'activity_tombstone')"
    ).fetchall()
    assert rows == [("public",)] * 3


def test_connect_keeps_options_from_the_url(database_url):
    url = psycopg.conninfo.make_conninfo(database_url, options="-c statement_timeout=1234")
    with connect(url) as conn:
        assert conn.execute("show statement_timeout").fetchone() == ("1234ms",)
        assert conn.execute("show search_path").fetchone() == ("analytics,public",)
