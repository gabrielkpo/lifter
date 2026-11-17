"""The scheduled jobs' shell helpers (ops/common.sh): a time limit and keepalives."""

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
