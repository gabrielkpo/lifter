"""Recovery and form views built from Garmin's own values (synthetic payloads)."""

from datetime import date
from decimal import Decimal

from lifter.sync import store_payload
from synthetic import daily_stats, sleep, training_readiness, training_status

DAY = date(2026, 4, 6)


def recovery(conn, day=DAY) -> dict:
    cur = conn.execute("select * from daily_recovery where day = %s", (day,))
    names = [c.name for c in cur.description]
    row = cur.fetchone()
    assert row is not None
    return dict(zip(names, row, strict=True))


def test_daily_recovery_joins_garmin_values(conn):
    night = dict(
        sleep(7.5, 50),
        deep_sleep_seconds=5400,
        rem_sleep_seconds=6300,
        awake_seconds=900,
        awake_count=2,
        avg_sleep_stress=18,
    )
    store_payload(conn, "get_sleep_summary", DAY.isoformat(), {}, night)
    store_payload(conn, "get_stats", DAY.isoformat(), {}, daily_stats(DAY, bb_high=88, bb_low=21))
    store_payload(
        conn,
        "get_training_readiness",
        DAY.isoformat(),
        {},
        training_readiness(DAY, ("07:10", 74, "HIGH")),
    )
    store_payload(conn, "get_training_status", DAY.isoformat(), {}, training_status(DAY))

    r = recovery(conn)
    assert r["sleep_hours"] == Decimal("7.50")
    assert (r["deep_sleep_minutes"], r["rem_sleep_minutes"], r["awake_minutes"]) == (90, 105, 15)
    assert (r["body_battery_highest"], r["body_battery_lowest"]) == (88, 21)
    assert r["intensity_minutes"] == 50  # 20 moderate + 2 x 15 vigorous, Garmin's convention
    assert (r["readiness_score"], r["readiness_level"]) == (74, "HIGH")
    assert r["garmin_training_status"] == "PRODUCTIVE"
    assert (r["garmin_acute_load"], r["garmin_chronic_load"]) == (420, 400)
    assert r["vo2_max"] == Decimal("52.3")


def test_morning_readiness_is_the_earliest_snapshot(conn):
    snapshots = training_readiness(DAY, ("18:30", 40, "LOW"), ("06:55", 81, "HIGH"))
    store_payload(conn, "get_training_readiness", DAY.isoformat(), {}, snapshots)
    store_payload(conn, "get_stats", DAY.isoformat(), {}, daily_stats(DAY))

    assert recovery(conn)["readiness_score"] == 81


def test_a_day_with_only_daily_stats_is_in_the_calendar(conn):
    store_payload(conn, "get_stats", DAY.isoformat(), {}, daily_stats(DAY))

    r = recovery(conn)
    assert r["sleep_hours"] is None
    assert r["readiness_score"] is None
    assert r["avg_stress"] == 30


def test_intensity_minutes_with_only_vigorous_minutes(conn):
    stats = daily_stats(DAY)
    del stats["moderate_intensity_minutes"]
    store_payload(conn, "get_stats", DAY.isoformat(), {}, stats)

    assert recovery(conn)["intensity_minutes"] == 30


def test_unexpected_status_code_does_not_break_the_view(conn):
    status = dict(training_status(DAY), training_status="PRODUCTIVE")  # not the usual integer
    store_payload(conn, "get_training_status", DAY.isoformat(), {}, status)
    store_payload(conn, "get_stats", DAY.isoformat(), {}, daily_stats(DAY))

    assert recovery(conn)["garmin_training_status"] == "PRODUCTIVE"  # label still read
    code = conn.execute(
        "select garmin_training_status_code from stg_training_status where day = %s", (DAY,)
    ).fetchone()
    assert code == (None,)
