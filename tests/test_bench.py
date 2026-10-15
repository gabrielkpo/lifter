"""The evaluation bench: scenarios, setup, expectations and runner, with the copy baseline."""

from pathlib import Path

import pytest

from lifter.agents.context import build_context
from lifter.bench.athlete import base_program
from lifter.bench.baseline import CopyLastWeek
from lifter.bench.runner import reset, run_scenario, summary
from lifter.bench.scenario import Scenario, apply_setup, read_scenarios

SCENARIOS = Path(__file__).parent.parent / "bench" / "scenarios"


@pytest.fixture(scope="module")
def scenarios():
    return {s.name: s for s in read_scenarios(SCENARIOS)}


def status(conn, week, title):
    return conn.execute(
        "select s.status from planned_session_status s join training_week w on w.id = s.week_id"
        " where w.number = %s and s.title = %s",
        (week, title),
    ).fetchone()[0]


def test_twenty_scenarios_with_known_checks(scenarios):
    assert len(scenarios) == 20
    categories = {s.category for s in scenarios.values()}
    assert categories == {"phase", "review", "health", "calendar"}


def test_an_unknown_check_is_refused():
    with pytest.raises(ValueError, match="unknown check"):
        Scenario.model_validate(
            {
                "name": "x",
                "category": "phase",
                "description": "x",
                "target_week": 3,
                "expect": [{"check": "looks_good"}],
                "review": "x",
            }
        )


def test_the_base_program_is_a_valid_twelve_week_cycle():
    program = base_program()
    assert [w.phase for w in program.weeks][3] == "deload"
    assert sum(len(w.sessions) for w in program.weeks) == 5 * 4 + 4


def test_setup_logs_skips_and_reports(conn, scenarios):
    apply_setup(conn, scenarios["knee_pain"])
    assert status(conn, 2, "Legs + Metcon") == "done"
    assert conn.execute(
        "select count(*) from planned_session p join training_week w on w.id = p.week_id"
        " where w.number = 3"
    ).fetchone() == (0,)  # the target week is programmed from scratch
    ctx = build_context(conn, week_number=3, today=scenarios["knee_pain"].today)
    assert [(f.session_title, f.pain, f.pain_location) for f in ctx.feedback] == [
        ("Legs + Metcon", 5, "knee")
    ]

    reset(conn)
    apply_setup(conn, scenarios["legs_skipped"])
    assert status(conn, 2, "Legs + Metcon") == "missed"


def test_recovery_profiles_raise_the_expected_alerts(conn, scenarios):
    apply_setup(conn, scenarios["critical_alert"])
    ctx = build_context(conn, week_number=3, today=scenarios["critical_alert"].today)
    assert {a.alert for a in ctx.alerts if a.severity == "critical"} == {
        "abnormal_hrv",
        "abnormal_rhr",
    }

    reset(conn)
    apply_setup(conn, scenarios["load_spike"])
    ctx = build_context(conn, week_number=3, today=scenarios["load_spike"].today)
    assert ctx.recovery[-1].acwr > 1.5


def test_reset_empties_every_table(conn, scenarios):
    apply_setup(conn, scenarios["deload_week"])
    reset(conn)
    for table in ("cycle", "planned_session", "raw_garmin_payload", "exercise"):
        assert conn.execute(f"select count(*) from {table}").fetchone() == (0,)


def test_the_copy_baseline_on_every_scenario(conn, scenarios):
    results = {}
    for scenario in scenarios.values():
        (run,) = run_scenario(conn, scenario, CopyLastWeek, runs=1)
        results[scenario.name] = run

    # what copying last week gets right, and where it fails, by design
    assert results["volume_peak_week"].expectations_met == 6
    assert not results["critical_alert"].accepted
    failed = {name: {o.check for o in r.outcomes if not o.passed} for name, r in results.items()}
    assert "load_at_least Bench press 65" in failed["after_deload"]
    assert "volume_vs_previous" in failed["deload_week"]
    assert "load_at_most Leg press 105" in failed["knee_pain"]
    assert "sessions" in failed["drafts_already_planned"]
    assert "light_first_days 2" in failed["low_recovery"]
    assert "includes_metcon amrap" not in failed["intensification_week"]

    totals = summary(list(results.values()))
    assert totals["runs"] == 20
    assert totals["input_tokens"] == 0
    assert 0.5 < totals["expectations_met_rate"] < 0.8


def test_the_bench_refuses_a_database_that_is_not_a_bench_one(monkeypatch, capsys):
    from lifter.cli import main

    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("BENCH_DATABASE_URL", "postgresql:///lifter")
    assert main(["bench"]) == 2
    assert "lifter_bench" in capsys.readouterr().out
