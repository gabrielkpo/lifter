"""The agents' audit log: every run of the week planner, its attempts, verdicts and cost."""

from datetime import date
from pathlib import Path

import pytest

from lifter.agents.planner import PlannerOutputError
from lifter.agents.week import run_week_planner
from lifter.program import load_program, read_program
from test_agents import TODAY, Scripted, good_plan

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


class Costly(Scripted):
    """A scripted planner that also reports tokens, like a model would."""

    model = "fake-model"

    def __call__(self, ctx, feedback):
        self.usage.input_tokens += 1000
        self.usage.output_tokens += 200
        return super().__call__(ctx, feedback)


def run_row(conn, run_id):
    return conn.execute(
        "select agent, trigger, model, status, attempts, input_tokens, output_tokens,"
        " proposal_ids, context -> 'target_week' ->> 'number', plan ->> 'summary'"
        " from agent_run where id = %s",
        (run_id,),
    ).fetchone()


def steps(conn, run_id):
    return conn.execute(
        "select attempt, plan is not null, violations, input_tokens"
        " from agent_step where run_id = %s order by attempt",
        (run_id,),
    ).fetchall()


def test_a_run_is_recorded_with_each_attempt_and_its_verdict(conn, program):
    bad = good_plan()
    bad.sessions[1].parts[0].lines[0].rir = 0
    result = run_week_planner(
        conn, Costly(bad, good_plan()), week_number=2, today=TODAY, propose=True, trigger="cli"
    )

    agent, trigger, model, status, attempts, tin, tout, proposals, week, summary = run_row(
        conn, result.run_id
    )
    assert (agent, trigger, model, status, attempts) == (
        "week_planner",
        "cli",
        "fake-model",
        "accepted",
        2,
    )
    assert (tin, tout) == (2000, 400)
    assert proposals == result.proposal_ids and len(proposals) == 2
    assert (week, summary) == ("2", "Week 2 adds one set, not more load.")

    first, second = steps(conn, result.run_id)
    assert first[:2] == (1, True) and first[3] == 1000
    assert [v["check"] for v in first[2]] == ["no_failure_on_legs"]
    assert second[:3] == (2, True, [])


def test_a_refused_run_and_an_unparsable_answer_are_recorded(conn, program):
    outside = good_plan()
    outside.sessions[0].day = date(2026, 4, 1)
    planner = Costly(PlannerOutputError("not JSON"), outside, outside)
    result = run_week_planner(conn, planner, week_number=2, today=TODAY, trigger="bench")

    assert run_row(conn, result.run_id)[3:5] == ("refused", 3)
    first = steps(conn, result.run_id)[0]
    assert first[1] is False  # the answer did not parse: no plan stored
    assert [v["check"] for v in first[2]] == ["schema"]


def test_a_crashed_run_is_recorded_with_its_error(conn, program):
    planner = Costly(ConnectionError("Mistral unreachable"))
    with pytest.raises(ConnectionError):
        run_week_planner(conn, planner, week_number=2, today=TODAY, trigger="cli")

    row = conn.execute("select status, error, attempts from agent_run").fetchone()
    assert row == ("error", "ConnectionError: Mistral unreachable", 0)


def test_no_trigger_records_nothing(conn, program):
    run_week_planner(conn, Scripted(good_plan()), week_number=2, today=TODAY)
    assert conn.execute("select count(*) from agent_run").fetchone() == (0,)


def test_runs_and_run_print_the_audit(monkeypatch, capsys, conn, program, database_url):
    from lifter.cli import main

    bad = good_plan()
    bad.sessions[1].parts[0].lines[0].rir = 0
    result = run_week_planner(
        conn, Costly(bad, good_plan()), week_number=2, today=TODAY, trigger="cli"
    )
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert main(["runs"]) == 0
    assert "week_planner" in capsys.readouterr().out
    assert main(["run", str(result.run_id)]) == 0
    out = capsys.readouterr().out
    assert "accepted after 2 attempt(s), 2000 + 400 tokens" in out
    assert "attempt 1: 2 session(s)" in out
    assert "[no_failure_on_legs] (2026-03-11)" in out
    assert main(["run", "999"]) == 1
