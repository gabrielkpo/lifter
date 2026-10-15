from lifter.db import migrate, migration_files


def test_migrations_are_ordered_and_idempotent(conn):
    names = [name for name, _ in migration_files()]
    assert names == sorted(names)
    assert migrate(conn) == []  # the session fixture already applied everything
    applied = [r[0] for r in conn.execute("select name from schema_migrations order by name")]
    assert applied == names
