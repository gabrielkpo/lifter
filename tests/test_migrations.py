import psycopg
import pytest

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


def test_the_conversations_so_far_get_a_row_each(database_url):
    # 015 on a database that already holds messages: one conversation per id, named after its
    # first athlete message, dated by its messages; then a message needs a conversation.
    import uuid

    name = f"lifter_test_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(database_url, autocommit=True)
    admin.execute(f'create database "{name}"')
    try:
        url = psycopg.conninfo.make_conninfo(database_url, dbname=name)
        with psycopg.connect(url) as db:
            db.execute("set timezone = 'UTC'")
            files = migration_files()
            for _, sql in [f for f in files if f[0] < "015"]:
                with db.transaction():
                    db.execute("set local search_path = public")
                    db.execute(sql)
            db.execute(
                "insert into conversation_message (conversation_id, role, text, created_at) values"
                " ('main', 'coach', 'Bonjour', '2026-10-19 08:00+00'),"
                " ('main', 'athlete', '  Décale   jeudi\n à vendredi', '2026-10-19 08:01+00'),"
                " ('main', 'athlete', 'merci', '2026-10-19 09:00+00'),"
                " ('bench', 'athlete', 'ajoute de la mobilité', '2026-10-18 10:00+00'),"
                " ('essai', 'coach', 'seul', '2026-10-17 10:00+00')"
            )
            with db.transaction():
                db.execute("set local search_path = public")
                db.execute(dict(files)["015_conversation.sql"])
            rows = db.execute(
                "select id, title, source, created_at::text, last_message_at::text"
                " from public.conversation order by id"
            ).fetchall()
            assert rows == [
                ("bench", "ajoute de la mobilité", "bench", *["2026-10-18 10:00:00+00"] * 2),
                ("essai", "essai", "cli", *["2026-10-17 10:00:00+00"] * 2),
                (
                    "main",
                    "Décale jeudi à vendredi",
                    "app",
                    "2026-10-19 08:00:00+00",
                    "2026-10-19 09:00:00+00",
                ),
            ]
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                db.execute(
                    "insert into public.conversation_message (conversation_id, role, text)"
                    " values ('typo', 'athlete', 'x')"
                )
    finally:
        admin.execute(f'drop database "{name}" with (force)')
        admin.close()
