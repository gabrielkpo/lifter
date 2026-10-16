"""The analytics layer, built with dbt (docs/adr/0001-dbt-for-the-analytics-layer.md).

`build` runs `dbt run` into a fresh schema, then swaps it in place of `analytics` in one
transaction: readers never see a half-built layer, and a failed build leaves the previous one
untouched. Views reference their relations by identifier, not by name, so renaming the schema
keeps every view and function working. `test` runs the data tests against `analytics`.

dbt is imported only here, by whoever migrates (the owner, the tests): the API and the scheduled
sync never load it.
"""

import hashlib
import os
import tempfile
import uuid
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

import psycopg

PROJECT_FILES = ("dbt_project.yml", "profiles.yml")
PROJECT_DIRS = ("models", "macros", "tests")
SCHEMA = "analytics"
# Connection settings dbt's profile cannot carry, handed to libpq (which dbt-postgres uses) by
# environment: a read-only `options`, channel binding and the CA file keep applying to dbt.
LIBPQ_ENV = {
    "options": "PGOPTIONS",
    "channel_binding": "PGCHANNELBINDING",
    "sslrootcert": "PGSSLROOTCERT",
}


class TransformError(Exception):
    """dbt could not build or test the analytics layer."""


def project_dir() -> Path:
    return Path(str(resources.files("lifter.transform")))


def project_digest() -> str:
    """Hash of everything that defines the layer, to rebuild only when it changed."""
    root = project_dir()
    digest = hashlib.sha256()
    files = [root / name for name in PROJECT_FILES]
    for folder in PROJECT_DIRS:
        files += sorted((root / folder).rglob("*")) if (root / folder).exists() else []
    for path in files:
        if path.is_file() and path.suffix in {".sql", ".yml", ".yaml"}:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@contextmanager
def _profile_env(conn: psycopg.Connection, schema: str):
    """The dbt profile's variables, taken from the live connection, for this run only."""
    info = conn.info
    params = info.get_parameters()
    values = {
        "LIFTER_DBT_HOST": info.host,
        "LIFTER_DBT_PORT": str(info.port),
        "LIFTER_DBT_USER": info.user,
        "LIFTER_DBT_PASSWORD": info.password or "",
        "LIFTER_DBT_DBNAME": info.dbname,
        "LIFTER_DBT_SCHEMA": schema,
        "LIFTER_DBT_SSLMODE": params.get("sslmode", "prefer"),
    }
    values |= {env: params[key] for key, env in LIBPQ_ENV.items() if key in params}
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _dbt(conn: psycopg.Connection, schema: str, *args: str) -> None:
    try:
        from dbt.cli.main import dbtRunner
    except ImportError as exc:
        raise TransformError(
            "dbt is not installed: install lifter with its `transform` extra"
            " (uv sync in a clone, or uv tool install 'lifter[transform] @ git+...')"
        ) from exc

    root = project_dir()
    with tempfile.TemporaryDirectory(prefix="lifter-dbt-") as work, _profile_env(conn, schema):
        result = dbtRunner().invoke(
            [
                *args,
                "--project-dir",
                str(root),
                "--profiles-dir",
                str(root),
                "--target-path",
                str(Path(work) / "target"),
                "--log-path",
                str(Path(work) / "logs"),
                "--quiet",
            ]
        )
    if not result.success:
        detail = result.exception or "see the failing nodes above"
        raise TransformError(f"dbt {' '.join(args)} failed: {detail}")


def build(conn: psycopg.Connection) -> None:
    """Build every model into a scratch schema, then swap it in as `analytics`."""
    scratch = f"analytics_build_{uuid.uuid4().hex[:8]}"
    try:
        _dbt(conn, scratch, "run")
    except BaseException:
        conn.execute(f'drop schema if exists "{scratch}" cascade')
        raise
    with conn.transaction():
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(f'alter schema "{scratch}" rename to {SCHEMA}')


def test(conn: psycopg.Connection) -> None:
    """Run the data tests (contracts are checked at build) against `analytics`."""
    _dbt(conn, SCHEMA, "test")


def freshness(conn: psycopg.Connection) -> None:
    """Check that the raw Garmin layer received data recently (sources.yml thresholds)."""
    _dbt(conn, SCHEMA, "source", "freshness")
