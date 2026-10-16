"""Postgres connection and schema migrations.

Tables live in numbered migrations (`NNN_name.sql`, schema `public`), applied once each.
Views and functions (schema `analytics`) are dbt models (src/lifter/transform), rebuilt only
when the dbt project changes and swapped in at once, so changing a view never needs a new
migration and an unchanged project never drops views that a reader may be using. Roles and
grants live in `roles.sql`, applied after the views when either changes (recreated views lose
their grants).
"""

import hashlib
from importlib import resources

import psycopg
from psycopg.conninfo import conninfo_to_dict

# Key of the analytics layer (the dbt project's hash) in public.schema_views.
TRANSFORM_KEY = "dbt"
# The analytics layer before dbt; its row is dropped once the dbt layer is built.
LEGACY_VIEWS_KEY = "views.sql"
# Roles and grants (RBAC). Applied after the views: recreating a view drops its grants.
ROLES_FILE = "roles.sql"
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
    """Apply the table migrations not applied yet, then rebuild the analytics layer (dbt) if its
    project changed, then the roles and grants (roles.sql) if they changed or the layer was
    rebuilt.

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
    exists = conn.execute(
        "select 1 from information_schema.schemata where schema_name = 'analytics'"
    ).fetchone()
    views_rebuilt = _build_analytics(conn, force=not exists)
    _apply_repeatable(conn, ROLES_FILE, force=views_rebuilt)
    return done


def _build_analytics(conn: psycopg.Connection, force: bool = False) -> bool:
    """Rebuild the analytics layer with dbt when its project changed; True when it ran."""
    from lifter import transform

    digest = transform.project_digest()
    row = conn.execute(
        "select sha256 from public.schema_views where name = %s", (TRANSFORM_KEY,)
    ).fetchone()
    if row is not None and row[0] == digest and not force:
        return False
    transform.build(conn)
    with conn.transaction():
        conn.execute("delete from public.schema_views where name = %s", (LEGACY_VIEWS_KEY,))
        conn.execute(
            "insert into public.schema_views (name, sha256) values (%s, %s)"
            " on conflict (name) do update set sha256 = excluded.sha256, applied_at = now()",
            (TRANSFORM_KEY, digest),
        )
    return True


def _apply_repeatable(conn: psycopg.Connection, name: str, force: bool = False) -> bool:
    """Run a repeatable SQL file when it changed (or when forced); True when it ran."""
    sql = resources.files("lifter.sql").joinpath(name).read_text()
    digest = hashlib.sha256(sql.encode()).hexdigest()
    row = conn.execute("select sha256 from public.schema_views where name = %s", (name,)).fetchone()
    if row is not None and row[0] == digest and not force:
        return False
    with conn.transaction():
        conn.execute(sql)
        conn.execute(
            "insert into public.schema_views (name, sha256) values (%s, %s)"
            " on conflict (name) do update set sha256 = excluded.sha256, applied_at = now()",
            (name, digest),
        )
    return True


class SchemaOutOfDate(Exception):
    """The database lags behind the code and the connected role may not update it."""


def schema_problems(conn: psycopg.Connection) -> list[str]:
    """What `migrate` would change, read-only: pending migrations, changed repeatable files."""
    if conn.execute("select to_regclass('public.schema_migrations')").fetchone()[0] is None:
        return ["the schema was never created"]
    applied = {row[0] for row in conn.execute("select name from public.schema_migrations")}
    problems = [
        f"migration {name} not applied" for name, _ in migration_files() if name not in applied
    ]
    if conn.execute("select to_regnamespace('analytics')").fetchone()[0] is None:
        problems.append("the analytics views are missing")
    hashes = dict(conn.execute("select name, sha256 from public.schema_views").fetchall())
    if hashes.get(TRANSFORM_KEY) != _transform_digest():
        problems.append("the analytics models changed")
    roles = resources.files("lifter.sql").joinpath(ROLES_FILE).read_text()
    if hashes.get(ROLES_FILE) != hashlib.sha256(roles.encode()).hexdigest():
        problems.append(f"{ROLES_FILE} changed")
    return problems


def _transform_digest() -> str:
    # Hashing the project needs no dbt: the scheduled sync checks the schema without it.
    from lifter.transform import project_digest

    return project_digest()


def ensure_schema(conn: psycopg.Connection, *, allow_migrate: bool = True) -> list[str]:
    """Bring the schema up to date when the connected role may (it can create in `public`, like
    the owner); otherwise only check it, never attempting DDL. Returns the migrations applied.

    Raises SchemaOutOfDate when the schema lags and may not be updated here: the owner runs
    `lifter migrate`. A least-privilege role (lifter_sync) thus fails clearly, not halfway.
    """
    can_migrate = conn.execute(
        "select has_schema_privilege(current_user, 'public', 'CREATE')"
    ).fetchone()[0]
    if allow_migrate and can_migrate:
        return migrate(conn)
    problems = schema_problems(conn)
    if problems:
        raise SchemaOutOfDate(
            "; ".join(problems) + " (run `lifter migrate` with the owner's connection)"
        )
    return []
