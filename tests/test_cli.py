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
