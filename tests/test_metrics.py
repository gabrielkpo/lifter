"""Business metrics on synthetic days. Expected values are computed by hand in the comments."""

from datetime import date, timedelta
from decimal import Decimal

from lifter.sync import store_payload
from synthetic import activity, hr_zones, load_days

DAY0 = date(2026, 1, 5)  # a Monday


def metrics(conn, offset: int) -> dict:
    cur = conn.execute("select * from daily_metrics where day = %s", (DAY0 + timedelta(offset),))
    names = [c.name for c in cur.description]
    row = cur.fetchone()
    assert row is not None, f"no metrics for day {offset}"
    return dict(zip(names, row, strict=True))


def alerts(conn, offset: int) -> set[str]:
    rows = conn.execute(
        "select alert from daily_alerts where day = %s", (DAY0 + timedelta(offset),)
    ).fetchall()
    return {r[0] for r in rows}


def steady(days: int, **values) -> list[dict]:
    base = {"load": 50, "hrv": 60, "rhr": 50, "sleep_hours": 7.25}
    return [dict(base, **values) for _ in range(days)]


def test_load_spike_day(conn):
    # 28 days at load 50, then 7 days at 100; the last night HRV 48 and resting HR 53.
    days = steady(28) + steady(7, load=100)
    days[-1] = dict(days[-1], hrv=48, rhr=53)
    load_days(conn, DAY0, days)

    m = metrics(conn, 34)
    assert m["history_days"] == 35
    assert m["acute_load_7d"] == Decimal("700.0")  # 7 x 100
    assert m["chronic_load_28d"] == Decimal("437.5")  # (21 x 50 + 7 x 100) / 4
    assert m["acwr"] == Decimal("1.60")  # 700 / 437.5
    assert m["hrv_baseline_28d"] == Decimal("60.0")  # previous 28 nights, today excluded
    assert m["hrv_delta_pct"] == Decimal("-20.0")  # (48 - 60) / 60
    assert m["rhr_delta_bpm"] == Decimal("3.0")
    assert m["sleep_hours"] == Decimal("7.25")
    # components: HRV 50 + 2.5 x -20 = 0 ; RHR 50 - 10 x 3 = 20 ; sleep 100 x 2.25 / 3 = 75
    assert m["recovery_score"] == 32  # round(95 / 3)
    assert m["recovery_status"] == "low"
    # six days at round(175 / 3) = 58, then 32: 380 / 7
    assert m["recovery_7d_avg"] == Decimal("54.3")
    assert m["trend"] == "stable"  # no chronic load 14 days earlier to compare with
    assert alerts(conn, 34) == {"load_spike", "hrv_drop"}


def test_windows_wait_for_enough_history(conn):
    load_days(conn, DAY0, steady(28))

    assert metrics(conn, 5)["acute_load_7d"] is None
    assert metrics(conn, 6)["acute_load_7d"] == Decimal("350.0")
    assert metrics(conn, 26)["acwr"] is None  # 27 days of history
    assert metrics(conn, 27)["acwr"] == Decimal("1.00")  # 350 / (1400 / 4)
    assert metrics(conn, 13)["hrv_delta_pct"] is None  # 13 previous nights
    assert metrics(conn, 14)["hrv_delta_pct"] == Decimal("0.0")  # 14 previous nights


def test_rest_days_count_as_zero_load(conn):
    days = steady(28)
    for i in range(21, 28):
        days[i] = dict(days[i], load=None)  # last week without any activity
    load_days(conn, DAY0, days)

    m = metrics(conn, 27)
    assert m["acute_load_7d"] == Decimal("0.0")
    assert m["acwr"] == Decimal("0.00")
    assert "load_drop" in alerts(conn, 27)


def test_score_uses_available_components(conn):
    days = steady(20, sleep_hours=None)
    days[-1] = dict(days[-1], hrv=66)  # +10 % -> HRV component 75
    load_days(conn, DAY0, days)

    m = metrics(conn, 19)
    assert m["sleep_hours"] is None
    assert m["recovery_score"] == 63  # round((75 + 50) / 2)
    assert m["recovery_status"] == "normal"


def test_no_hrv_means_unknown_recovery(conn):
    load_days(conn, DAY0, steady(20, hrv=None))

    m = metrics(conn, 19)
    assert m["recovery_score"] is None
    assert m["recovery_status"] == "unknown"
    assert m["trend"] == "unknown"


def test_fatigue_trend(conn):
    days = steady(23, sleep_hours=5.5) + steady(7, hrv=42, sleep_hours=5.5)
    load_days(conn, DAY0, days)

    m = metrics(conn, 29)
    assert m["recovery_7d_avg"] < 45
    assert m["trend"] == "fatigue"
    assert alerts(conn, 29) == {"hrv_drop", "short_sleep"}


def test_improving_trend(conn):
    # chronic load: (6 x 40 + 22 x 60) / 4 = 390 now, (20 x 40 + 8 x 60) / 4 = 320 14 days ago
    days = steady(28, load=40, sleep_hours=8) + steady(22, load=60, sleep_hours=8)
    load_days(conn, DAY0, days)

    m = metrics(conn, 49)
    assert m["chronic_load_28d"] == Decimal("390.0")
    assert m["recovery_score"] == 67  # round((50 + 50 + 100) / 3)
    assert m["trend"] == "improving"


def test_abnormal_signal_is_critical(conn):
    days = steady(30)
    days[-1] = dict(days[-1], hrv=39, rhr=61)  # -35 %, +11 bpm
    load_days(conn, DAY0, days)

    rows = conn.execute(
        "select alert, severity from daily_alerts where day = %s", (DAY0 + timedelta(29),)
    ).fetchall()
    assert set(rows) == {
        ("hrv_drop", "warning"),
        ("abnormal_hrv", "critical"),
        ("rhr_elevated", "warning"),
        ("abnormal_rhr", "critical"),
    }


def test_weekly_training_sums_sessions_and_zones(conn):
    store_payload(conn, "get_activity", "1", {}, activity(1, DAY0, load=80, minutes=45))
    store_payload(
        conn, "get_activity", "2", {}, activity(2, DAY0 + timedelta(2), load=None, minutes=30)
    )
    store_payload(conn, "get_activity_hr_in_timezones", "1", {}, hr_zones([600, 1200, 900, 0, 0]))
    store_payload(conn, "get_activity_hr_in_timezones", "2", {}, hr_zones([1800, 0, 0, 0, 0]))

    row = conn.execute(
        "select week_start, sessions, duration_minutes, load, zone1_minutes, zone2_minutes,"
        " zone3_minutes from weekly_training"
    ).fetchall()
    assert row == [
        (
            DAY0,
            2,
            Decimal("75.0"),
            Decimal("80.0"),
            Decimal("40.0"),
            Decimal("20.0"),
            Decimal("15.0"),
        )
    ]


def test_zero_hrv_baseline_does_not_break_the_view(conn):
    load_days(conn, DAY0, steady(20, hrv=0))

    m = metrics(conn, 19)
    assert m["hrv_delta_pct"] is None
    assert m["recovery_status"] == "unknown"


def test_resting_hr_comes_from_daily_stats_when_sleep_lacks_it(conn):
    from synthetic import daily_stats

    # Like the author's watch: the sleep summary never carries the resting HR.
    load_days(conn, DAY0, steady(20, rhr=None))
    for offset in range(20):
        day = DAY0 + timedelta(offset)
        stats = dict(daily_stats(day), resting_heart_rate_bpm=50 if offset < 19 else 56)
        store_payload(conn, "get_stats", day.isoformat(), {}, stats)

    m = metrics(conn, 19)
    assert m["resting_hr_bpm"] == 56
    assert m["rhr_delta_bpm"] == Decimal("6.0")
    assert "rhr_elevated" in alerts(conn, 19)


def test_daily_stats_resting_hr_wins_over_the_sleep_value(conn):
    from synthetic import daily_stats

    load_days(conn, DAY0, steady(1, rhr=48))
    store_payload(conn, "get_stats", DAY0.isoformat(), {}, daily_stats(DAY0))  # 50 bpm

    assert metrics(conn, 0)["resting_hr_bpm"] == 50


def test_load_is_rounded_to_one_decimal(conn):
    store_payload(conn, "get_activity", "1", {}, activity(1, DAY0, load=163.6713409423828))

    row = conn.execute("select load from daily_load where day = %s", (DAY0,)).fetchone()
    assert row == (Decimal("163.7"),)
