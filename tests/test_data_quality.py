"""The analytics layer built by dbt: contracts at build, data tests and freshness on real paths."""

from datetime import date
from pathlib import Path

import pytest

from lifter import transform
from lifter.program import load_program, read_program
from synthetic import load_days

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"


def test_the_data_tests_pass_on_the_synthetic_program_and_garmin_days(conn):
    load_program(conn, read_program(EXAMPLE))
    load_days(conn, date(2026, 2, 1), [{"load": 60, "hrv": 60, "rhr": 50, "sleep_hours": 7.5}] * 40)
    transform.test(conn)


def test_freshness_fails_when_garmin_data_is_old(conn):
    load_days(conn, date(2026, 2, 1), [{"hrv": 60}])
    conn.execute("update raw_garmin_payload set last_seen_at = now() - interval '4 days'")
    with pytest.raises(transform.TransformError, match="freshness"):
        transform.freshness(conn)
    conn.execute("update raw_garmin_payload set last_seen_at = now() - interval '1 hour'")
    transform.freshness(conn)


def test_a_broken_rule_fails_the_data_tests(conn):
    # The same Garmin activity stored under two keys: stg_activity would list it twice, which
    # its unique test on activity_id must catch.
    from lifter.sync import store_payload
    from synthetic import activity

    store_payload(conn, "get_activity", "1", {}, activity(1, date(2026, 3, 2), load=50))
    store_payload(conn, "get_activity", "1-copy", {}, activity(1, date(2026, 3, 2), load=50))
    with pytest.raises(transform.TransformError, match="dbt test failed"):
        transform.test(conn)


def test_the_layer_is_rebuilt_only_when_the_project_changes(conn):
    from lifter.db import migrate

    built_at = conn.execute("select applied_at from schema_views where name = 'dbt'").fetchone()
    migrate(conn)
    assert (
        conn.execute("select applied_at from schema_views where name = 'dbt'").fetchone()
        == built_at
    )
