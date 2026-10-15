"""Postgres connection and schema migrations.

Tables live in numbered migrations (`NNN_name.sql`, schema `public`), applied once each.
Views and functions live in `views.sql` (schema `analytics`), recreated only when the file
changes, so changing a view never needs a new migration and an unchanged file never drops
views that a reader may be using.
"""

import hashlib
from importlib import resources

import psycopg
from psycopg.conninfo import conninfo_to_dict

VIEWS_FILE = "views.sql"
SEARCH_PATH = "analytics,public"


def connect(url: str) -> psycopg.Connection:
    """Autocommit connection: callers group writes with `conn.transaction()`.

    The search_path is appended to any `options` already set in the URL, not substituted.
    """
    options = conninfo_to_dict(url).get("options", "")
    options = f"{options} -c search_path={SEARCH_PATH}".strip()
    return psycopg.connect(url, autocommit=True, options=options)


def migration_files() -> list[tuple[str, str]]:
    files = [
        f
        for f in resources.files("lifter.sql").iterdir()
        if f.name.endswith(".sql") and f.name[:3].isdigit()
    ]
    return [(f.name, f.read_text()) for f in sorted(files, key=lambda f: f.name)]


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply the table migrations not applied yet, then recreate the views if they changed.

    Returns the names of the migrations applied by this call.
    """
    conn.execute(
        "create table if not exists public.schema_migrations ("
        " name text primary key, applied_at timestamptz not null default now())"
    )
    conn.execute(
        "create table if not exists public.schema_views ("
        " name text primary key, sha256 text not null,"
        " applied_at timestamptz not null default now())"
    )
    applied = {row[0] for row in conn.execute("select name from public.schema_migrations")}
    done = []
    for name, sql in migration_files():
        if name in applied:
            continue
        with conn.transaction():
            # Tables belong to `public`, whatever the connection's search_path.
            conn.execute("set local search_path = public")
            conn.execute(sql)
            conn.execute("insert into public.schema_migrations (name) values (%s)", (name,))
        done.append(name)
    _apply_views(conn)
    return done


def _apply_views(conn: psycopg.Connection) -> None:
    sql = resources.files("lifter.sql").joinpath(VIEWS_FILE).read_text()
    digest = hashlib.sha256(sql.encode()).hexdigest()
    row = conn.execute(
        "select sha256 from public.schema_views where name = %s", (VIEWS_FILE,)
    ).fetchone()
    exists = conn.execute(
        "select 1 from information_schema.schemata where schema_name = 'analytics'"
    ).fetchone()
    if row is not None and row[0] == digest and exists:
        return
    with conn.transaction():
        conn.execute(sql)
        conn.execute(
            "insert into public.schema_views (name, sha256) values (%s, %s)"
            " on conflict (name) do update set sha256 = excluded.sha256, applied_at = now()",
            (VIEWS_FILE, digest),
        )
