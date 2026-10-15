"""Postgres connection and schema migrations."""

from importlib import resources

import psycopg


def connect(url: str) -> psycopg.Connection:
    """Autocommit connection: callers group writes with `conn.transaction()`."""
    return psycopg.connect(url, autocommit=True)


def migration_files() -> list[tuple[str, str]]:
    files = [f for f in resources.files("lifter.sql").iterdir() if f.name.endswith(".sql")]
    return [(f.name, f.read_text()) for f in sorted(files, key=lambda f: f.name)]


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply the migrations not applied yet, each in its own transaction. Returns their names."""
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
    return done
