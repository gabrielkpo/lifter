"""Pins what the README says about its synthetic example (scripts/readme_example.py)."""

import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "readme_example.py"
spec = importlib.util.spec_from_file_location("readme_example", SCRIPT)
readme_example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readme_example)


def test_example_day_matches_the_readme(conn):
    from synthetic import load_days

    load_days(conn, readme_example.FIRST_DAY, readme_example.synthetic_days())
    row = conn.execute(
        "select hrv_delta_pct, recovery_score, recovery_status, trend from daily_metrics"
        " where day = %s",
        (date(2026, 9, 26),),
    ).fetchone()
    assert row == (Decimal("-22.4"), 33, "low", "fatigue")
    alerts = {
        r[0]
        for r in conn.execute("select alert from daily_alerts where day = %s", (date(2026, 9, 26),))
    }
    assert "hrv_drop" in alerts


def test_script_refuses_a_database_with_data(conn, database_url):
    from synthetic import load_days

    load_days(conn, date(2026, 1, 1), [{"hrv": 60}])
    with pytest.raises(SystemExit, match="refusing"):
        readme_example.main(database_url)
