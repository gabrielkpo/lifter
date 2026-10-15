import os
import uuid

import psycopg
import pytest

from lifter.db import connect, migrate

# A server where the tests may create and drop a throwaway database.
ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql:///postgres")


@pytest.fixture(scope="session")
def database_url():
    name = f"lifter_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True)
    except psycopg.OperationalError as exc:
        if os.environ.get("CI"):
            raise  # in CI a missing database must fail, not skip the database tests
        pytest.skip(f"no Postgres for tests at TEST_DATABASE_URL ({exc})")
    admin.execute(f'create database "{name}"')
    url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name)
    with connect(url) as conn:
        migrate(conn)
    yield url
    admin.execute(f'drop database "{name}" with (force)')
    admin.close()


@pytest.fixture
def conn(database_url):
    with connect(database_url) as conn:
        conn.execute(
            "truncate raw_garmin_payload, sync_log, activity_tombstone, proposal, feedback,"
            " planned_session, training_plan, goal restart identity"
        )
        yield conn
