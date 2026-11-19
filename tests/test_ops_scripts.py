"""The scheduled jobs' shell helpers (ops/common.sh) and the restore test's age check."""

import os
import subprocess
import time
from pathlib import Path

COMMON = Path(__file__).parent.parent / "ops" / "common.sh"


def bash(tmp_path: Path, script: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LIFTER_CONFIG_DIR": str(tmp_path / "config"),
        "LIFTER_LOG_DIR": str(tmp_path / "logs"),
    }
    return subprocess.run(
        ["bash", "-c", f'source "{COMMON}"; {script}'],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_a_stuck_command_is_stopped_at_its_limit(tmp_path):
    started = time.monotonic()
    out = bash(tmp_path, "run_with_timeout 1 sleep 20; echo $?")
    assert out.stdout.strip() == "124"
    assert time.monotonic() - started < 10
    assert not list((tmp_path / "logs").glob(".timed-out-*"))


def test_a_command_within_its_limit_keeps_its_exit_code_and_ends_with_it(tmp_path):
    started = time.monotonic()
    out = bash(tmp_path, "run_with_timeout 30 true; echo $?; run_with_timeout 30 false; echo $?")
    assert out.stdout.split() == ["0", "1"]
    assert time.monotonic() - started < 10  # the watchdog does not hold the job to its limit


def test_keepalives_are_added_to_a_url(tmp_path):
    out = bash(
        tmp_path,
        'with_keepalives "postgresql://u@h/db"; echo; with_keepalives "postgresql://u@h/db?sslmode=require"',
    )
    first, second = out.stdout.split()
    assert first.startswith("postgresql://u@h/db?connect_timeout=10&keepalives=1")
    assert second.startswith("postgresql://u@h/db?sslmode=require&connect_timeout=10")


def test_a_job_stopped_from_outside_stops_its_command(tmp_path):
    marker = tmp_path / "still-running"
    script = (
        f'run_with_timeout 60 bash -c "sleep 3; touch {marker}" & job=$!; '
        "sleep 1; kill -TERM $job; wait $job; echo $?"
    )
    out = bash(tmp_path, script)
    assert out.stdout.strip() == "143"
    time.sleep(3)
    assert not marker.exists()  # the command died with the job


RESTORE_CHECK = COMMON.parent / "lifter-restore-check.sh"


def restore_check(tmp_path: Path, dump_age_hours: float) -> tuple[int, str]:
    """Run the restore test on one dump of the given age; the Postgres tools are stubs that fail,
    so a dump that passes the age check stops at the restore."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for tool in ("osascript", "dropdb", "createdb", "pg_restore", "psql"):
        (stubs / tool).write_text("#!/bin/sh\nexit 1\n")
        (stubs / tool).chmod(0o755)
    backups = tmp_path / "backups"
    backups.mkdir()
    dump = backups / "lifter-20260101-130000.dump"
    dump.write_bytes(b"")
    when = time.time() - dump_age_hours * 3600
    os.utime(dump, (when, when))
    env = {
        "PATH": f"{stubs}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LIFTER_AWAKE": "1",
        "LIFTER_CONFIG_DIR": str(tmp_path / "config"),
        "LIFTER_LOG_DIR": str(tmp_path / "logs"),
        "LIFTER_BACKUP_DIR": str(backups),
        "PG_BIN": str(stubs),
    }
    out = subprocess.run(["bash", str(RESTORE_CHECK)], env=env, timeout=60, check=False)
    return out.returncode, (tmp_path / "logs" / "restore-check.log").read_text()


def test_the_restore_test_fails_when_the_latest_backup_is_old(tmp_path):
    code, log = restore_check(tmp_path, dump_age_hours=72)
    assert code == 1 and "is older than 48 h" in log


def test_a_recent_backup_goes_on_to_the_restore(tmp_path):
    code, log = restore_check(tmp_path, dump_age_hours=1)
    assert "older than" not in log and "restore-check: FAILED" in log  # the stubbed restore
