from pathlib import Path

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


def run_cli(monkeypatch, database_url, *argv):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    return main(list(argv))


def test_adding_a_session_then_seeing_it_in_the_calendar(monkeypatch, capsys, conn, database_url):
    assert run_cli(monkeypatch, database_url, "session-add", "2026-03-02", "Push + Metcon") == 0
    assert (
        run_cli(
            monkeypatch,
            database_url,
            "calendar",
            "--start",
            "2026-03-01",
            "--past",
            "0",
            "--ahead",
            "3",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "session 1 created" in out
    assert "Push + Metcon" in out and "missed" in out


def test_loading_the_example_program_then_reading_it(monkeypatch, capsys, conn, database_url):
    example = str(Path(__file__).parent.parent / "examples" / "program.yaml")
    assert run_cli(monkeypatch, database_url, "program", "load", example) == 0
    assert "sessions=5" in capsys.readouterr().out

    assert run_cli(monkeypatch, database_url, "program") == 0
    assert "accumulation" in capsys.readouterr().out
    assert run_cli(monkeypatch, database_url, "weeks") == 0
    assert "reference" in capsys.readouterr().out
    assert run_cli(monkeypatch, database_url, "week", "1") == 0
    assert "Benchmark metcon" in capsys.readouterr().out

    assert run_cli(monkeypatch, database_url, "session", "1") == 0
    out = capsys.readouterr().out
    assert "planned Bench press 3x10 @ 50 kg RIR 3, rest 120 s" in out
    assert "done    Bench press 3x10 @ 52.5 kg RIR 2" in out
    assert "amrap, 15 min, target 5 rounds, 5.5 rounds done" in out

    assert run_cli(monkeypatch, database_url, "program", "load", example) == 1  # loaded already
    assert "refused" in capsys.readouterr().out


def test_a_missing_program_file_is_reported(monkeypatch, capsys, conn, database_url):
    assert run_cli(monkeypatch, database_url, "program", "load", "nowhere.yaml") == 2
    assert "cannot read" in capsys.readouterr().out


def test_invalid_feedback_is_refused_without_a_traceback(monkeypatch, capsys, conn, database_url):
    assert run_cli(monkeypatch, database_url, "feedback", "--rpe", "11") == 2
    assert "invalid input: rpe" in capsys.readouterr().out


def test_approving_a_proposal_applies_it(monkeypatch, capsys, conn, database_url):
    from lifter import domain

    goal = {"title": "First muscle-up", "kind": "skill", "target_text": "one rep"}
    pid = domain.propose(conn, "create_goal", goal, "From chat.", "coach")
    assert run_cli(monkeypatch, database_url, "proposals") == 0
    assert "First muscle-up" in capsys.readouterr().out
    assert run_cli(monkeypatch, database_url, "proposal", "approve", str(pid)) == 0
    assert "applied" in capsys.readouterr().out
    assert run_cli(monkeypatch, database_url, "proposal", "approve", str(pid)) == 1  # not pending


def test_control_characters_are_escaped_in_tables():
    from lifter.cli import format_table

    out = format_table(("rationale",), [("ok\x1b[2K\rhidden",)])
    assert "\x1b" not in out and "\r" not in out
    assert "\\x1b[2K\\rhidden" in out


def test_error_messages_escape_control_characters(monkeypatch, capsys, conn, database_url):
    from lifter import domain

    session = {
        "day": "2026-03-02",
        "title": "Push",
        "parts": [{"kind": "strength", "planned": [{"exercise": "Bench\x1b[2K\rapplied"}]}],
    }
    pid = domain.propose(conn, "create_session", session, "Unknown exercise.", "coach")
    assert run_cli(monkeypatch, database_url, "proposal", "approve", str(pid)) == 1
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\r" not in out
    assert "refused:" in out and "\\x1b[2K\\rapplied" in out


def test_a_program_file_that_is_not_utf8_is_reported(
    monkeypatch, capsys, conn, database_url, tmp_path
):
    path = tmp_path / "program.yaml"
    path.write_bytes("name: Cycle d'été\n".encode("latin-1"))
    assert run_cli(monkeypatch, database_url, "program", "load", str(path)) == 2
    assert "cannot read" in capsys.readouterr().out


def test_a_malformed_setting_is_reported_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("LIFTER_RUN_TOKEN_BUDGET", "60k")
    assert main(["runs"]) == 2
    assert "LIFTER_RUN_TOKEN_BUDGET must be a whole number, got '60k'" in capsys.readouterr().out
