"""Postgres connection and schema migrations.

Tables live in numbered migrations (`NNN_name.sql`), applied once each. Views and functions
live in `views.sql`, dropped and recreated on every migrate, so changing a view never needs
a new migration.
"""

from importlib import resources

import psycopg

VIEWS_FILE = "views.sql"


def connect(url: str) -> psycopg.Connection:
    """Autocommit connection: callers group writes with `conn.transaction()`."""
    return psycopg.connect(url, autocommit=True)


def migration_files() -> list[tuple[str, str]]:
    files = [
        f
        for f in resources.files("lifter.sql").iterdir()
        if f.name.endswith(".sql") and f.name[:3].isdigit()
    ]
    return [(f.name, f.read_text()) for f in sorted(files, key=lambda f: f.name)]


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply the table migrations not applied yet, then recreate the views.

    Returns the names of the migrations applied by this call.
    """
    conn.execute(
        "create table if not exists schema_migrations ("
        " name text primary key, applied_at timestamptz not null default now())"
    )
    applied = {row[0] for row in conn.execute("select name from schema_migrations")}
    done = []
    for name, sql in migration_files():
        if name in applied:
            continue
        with conn.transaction():
            conn.execute(sql)
            conn.execute("insert into schema_migrations (name) values (%s)", (name,))
        done.append(name)
    with conn.transaction():
        conn.execute(resources.files("lifter.sql").joinpath(VIEWS_FILE).read_text())
    return done
