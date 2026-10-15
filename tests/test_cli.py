import pytest

from lifter import __version__
from lifter.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_sync_without_token_stops_before_any_call(monkeypatch, capsys):
    monkeypatch.setenv("GARMIN_MCP_TOKEN", "")
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    assert main(["sync", "--days", "1"]) == 2
    assert "GARMIN_MCP_TOKEN is not set" in capsys.readouterr().out


def test_recovery_prints_the_last_days(monkeypatch, capsys, conn, database_url):
    from datetime import date

    from lifter.sync import store_payload
    from synthetic import daily_stats

    store_payload(conn, "get_stats", "2026-04-06", {}, daily_stats(date(2026, 4, 6)))
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)

    assert main(["recovery", "--days", "3"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:2] == ["day", "sleep_hours"]
    assert lines[1].split()[:2] == ["2026-04-06", "-"]  # no sleep that day: "-", not a gap


def test_format_table_keeps_columns_aligned_with_missing_values():
    from lifter.cli import format_table

    out = format_table(("day", "a", "b"), [("2026-01-01", None, 3), ("2026-01-02", 10, None)])
    lines = out.splitlines()
    assert lines == ["day         a   b", "2026-01-01  -   3", "2026-01-02  10  -"]
