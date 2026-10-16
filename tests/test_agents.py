"""The week planner agent: context, guardrail, graph and proposals, on the synthetic program.

The LLM is replaced by scripted planners: these tests check everything around the model
(what it reads, what is refused, what gets proposed), deterministically and offline.
"""

from datetime import date
from pathlib import Path

import pytest

from lifter import domain
from lifter.agents import guardrail
from lifter.agents.context import Alert, PlanningError, RecentLoad, build_context
from lifter.agents.plan import PlanLine, PlanPart, PlanSession, WeekPlan
from lifter.agents.planner import MistralPlanner, PlannerOutputError, Usage, user_message
from lifter.agents.week import run_week_planner
from lifter.program import load_program, read_program

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"
TODAY = date(2026, 3, 8)  # the Sunday before week 2


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


@pytest.fixture
def ctx(conn, program):
    return build_context(conn, week_number=2, today=TODAY)


def good_plan(**changes) -> WeekPlan:
    push = PlanSession(
        day=date(2026, 3, 9),
        title="Weightlifting + Push + Metcon",
        rationale="Bench press was 52.5 kg at RIR 2: same load, one more set.",
        parts=[
            PlanPart(
                kind="weightlifting",
                lines=[PlanLine(exercise="Power clean", sets=5, quantity=3, load_kg=45, rir=3)],
            ),
            PlanPart(
                kind="strength",
                lines=[
                    PlanLine(exercise="Bench press", sets=4, quantity=10, load_kg=52.5, rir=3),
                    PlanLine(exercise="Dips", sets=4, quantity=6, rir=3),
                ],
            ),
            PlanPart(
                kind="metcon",
                format="amrap",
                duration_minutes=15,
                target_rounds=5,
                lines=[
                    PlanLine(exercise="Ski erg", quantity=12, unit="cal"),
                    PlanLine(exercise="Burpee", quantity=10),
                ],
            ),
        ],
    )
    legs = PlanSession(
        day=date(2026, 3, 11),
        title="Legs + Metcon",
        rationale="Leg press was 105 kg for 12 reps at RIR 3: unilateral work added.",
        parts=[
            PlanPart(
                kind="strength",
                lines=[
                    PlanLine(exercise="Leg press", sets=4, quantity=12, load_kg=105, rir=3),
                    PlanLine(exercise="Leg curl", sets=3, quantity=12, rir=3),
                ],
            ),
        ],
    )
    plan = WeekPlan(summary="Week 2 adds one set, not more load.", sessions=[push, legs])
    return plan.model_copy(update=changes)


def checks(plan, ctx):
    return {v.check for v in guardrail.check(plan, ctx).violations}


class Scripted:
    """A planner that returns (or raises) the given answers in order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.feedback: list[list[str]] = []
        self.usage = Usage()

    def __call__(self, ctx, feedback):
        self.feedback.append(feedback)
        self.usage.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


# Context


def test_the_context_holds_the_week_the_review_and_the_last_loads(ctx):
    assert (ctx.target_week.number, ctx.target_week.phase) == (2, "volume")
    assert ctx.target_week.intent["push"] == "One more set, not more load. RIR 3."
    review = ctx.previous_week
    assert (review.number, review.done, review.missed) == (1, 2, 2)
    loads = {(r.exercise, r.reps): (r.load_kg, r.rir) for r in ctx.recent_loads}
    assert loads[("Bench press", 10)] == (52.5, 2)
    assert loads[("Leg press", 12)] == (105, 3)
    assert ctx.target_week.block_target_strength_sessions == 12
    assert [g.title for g in ctx.goals][0] == "Bench press 80 kg"


def test_indicators_mode_sends_the_programme_text_and_nothing_written_after(conn, program):
    # Free text written about the training (notes, deviations, reviews) stays out by default;
    # the programme the athlete wrote for the coach to follow (titles, intents, rules, goals)
    # is the planner's input and is sent in every mode (docs/agents.md).
    conn.execute("update planned_session set notes = 'CANARY-note', deviation = 'CANARY-dev'")
    conn.execute("update training_week set review = 'CANARY-review'")
    conn.execute("update goal set notes = 'CANARY-goal'")
    conn.execute("update athlete_rule set text = text || ' RULE-text'")
    domain.add_feedback(conn, domain.FeedbackIn(day=TODAY, kind="morning", notes="CANARY-fb"))

    lean = build_context(conn, week_number=2, today=TODAY).model_dump_json()
    full = build_context(conn, week_number=2, today=TODAY, mode="full").model_dump_json()

    for canary in ("CANARY-note", "CANARY-dev", "CANARY-review", "CANARY-goal", "CANARY-fb"):
        assert canary not in lean and canary in full
    assert "RULE-text" in lean


def test_no_cycle_means_nothing_to_plan(conn):
    with pytest.raises(PlanningError):
        build_context(conn, today=TODAY)


def test_the_default_week_is_the_next_one(conn, program):
    assert build_context(conn, today=date(2026, 3, 4)).target_week.number == 2


# Guardrail


def test_a_plan_within_the_rules_is_accepted(ctx):
    verdict = guardrail.check(good_plan(), ctx)
    assert verdict.violations == []
    assert verdict.unchecked_rules == [
        "Weightlifting and skills while fresh, never after a metcon."
    ]


def test_sessions_outside_the_week_and_unknown_exercises_are_refused(ctx):
    plan = good_plan()
    plan.sessions[0].day = date(2026, 3, 20)
    plan.sessions[1].parts[0].lines.append(PlanLine(exercise="Squat snatch", quantity=3, rir=3))
    assert checks(plan, ctx) == {"days", "exercise_bank"}


def test_forbidden_exercises_are_refused(ctx):
    plan = good_plan()
    plan.sessions[1].parts[0].lines += [
        PlanLine(exercise="Back squat", sets=3, quantity=5, load_kg=60, rir=3),
        PlanLine(exercise="Box jump", quantity=10),
    ]
    messages = [v.message for v in guardrail.check(plan, ctx).violations]
    assert any("Back squat" in m and "free_barbell_legs" in m for m in messages)
    assert any("Box jump" in m and "impact" in m for m in messages)


def test_legs_to_failure_are_refused(ctx):
    plan = good_plan()
    plan.sessions[1].parts[0].lines[0].rir = 0
    assert checks(plan, ctx) == {"no_failure_on_legs"}


def test_a_load_jump_bigger_than_one_step_is_refused(ctx):
    plan = good_plan()
    plan.sessions[0].parts[1].lines[0].load_kg = 57.5  # last logged 52.5 at 10 reps: max 55
    violations = guardrail.check(plan, ctx).violations
    assert [v.check for v in violations] == ["progression"]
    assert "at most 55 kg" in violations[0].message


def test_fewer_reps_allow_a_heavier_load(ctx):
    plan = good_plan()
    plan.sessions[0].parts[1].lines[0] = PlanLine(
        exercise="Bench press", sets=5, quantity=5, load_kg=62.5, rir=2
    )
    assert "progression" not in checks(plan, ctx)


def test_numbers_found_nowhere_in_the_context_are_refused(ctx):
    plan = good_plan()
    plan.sessions[0].rationale = "Recovery improved by 41.3 % since last week."
    violations = guardrail.check(plan, ctx).violations
    assert [v.check for v in violations] == ["sources"]
    assert "41.3" in violations[0].message


def test_only_planned_sessions_of_the_week_can_be_cancelled(ctx):
    assert checks(good_plan(cancel_session_ids=[1]), ctx) == {"cancellations"}


def test_a_critical_alert_allows_easy_work_only(ctx):
    alert = Alert(day=TODAY, alert="abnormal_hrv", severity="critical", value=-35, threshold=-30)
    alarmed = ctx.model_copy(update={"alerts": [alert]})
    assert "critical_alert" in checks(good_plan(), alarmed)


def test_loads_logged_in_another_unit_are_not_reps(conn, program):
    part = conn.execute(
        "select part_id from session_exercise e join exercise x on x.id = e.exercise_id"
        " where e.origin = 'done' and x.name = 'Power clean'"
    ).fetchone()[0]
    conn.execute(
        "insert into session_exercise (part_id, origin, position, exercise_id, sets, quantity,"
        " unit, load_kg) select %s, 'done', 99, id, 4, 40, 'm', 24 from exercise"
        " where name = 'Farmer carry'",
        (part,),
    )
    ctx = build_context(conn, week_number=2, today=TODAY)
    assert "Farmer carry" not in {r.exercise for r in ctx.recent_loads}


def test_a_change_of_unit_does_not_skip_the_progression(ctx):
    plan = good_plan()
    line = plan.sessions[0].parts[1].lines[0]  # bench press, logged at most 70 kg in 28 days
    line.unit, line.quantity, line.load_kg = "s", 30, 80
    violations = [v for v in guardrail.check(plan, ctx).violations if v.check == "progression"]
    assert len(violations) == 1 and "at most 72.5 kg" in violations[0].message
    line.load_kg = 70
    assert "progression" not in checks(plan, ctx)


def test_a_number_from_a_note_is_not_a_source(ctx):
    plan = good_plan()
    plan.sessions[0].parts[1].notes = "437 reps in total"
    plan.sessions[0].rationale = "437 reps in total this session."
    violations = [v for v in guardrail.check(plan, ctx).violations if v.check == "sources"]
    assert [v.items for v in violations] == [("437",)]


def legs_only(*lines: PlanLine) -> WeekPlan:
    plan = good_plan()
    plan.sessions = plan.sessions[1:]
    plan.sessions[0].parts[0].lines = list(lines)
    return plan


def test_a_line_without_rir_or_count_is_refused(ctx):
    plan = legs_only(PlanLine(exercise="Leg press", sets=4, load_kg=100))
    messages = [v.message for v in guardrail.check(plan, ctx).violations]
    assert messages == ["'Leg press' has no reps count", "'Leg press' has no target RIR"]


def test_rir_is_only_required_where_it_means_something(ctx):
    plan = legs_only(
        PlanLine(exercise="Leg press", sets=4, quantity=12, load_kg=100, rir=3),
        PlanLine(exercise="Farmer carry", sets=4, quantity=40, unit="m", load_kg=24),
    )
    assert checks(plan, ctx) == set()


def test_a_missing_rir_counts_as_hard_under_a_critical_alert(ctx):
    alert = Alert(day=TODAY, alert="abnormal_hrv", severity="critical", value=-35, threshold=-30)
    alarmed = ctx.model_copy(update={"alerts": [alert]})
    easy = legs_only(PlanLine(exercise="Leg press", sets=4, quantity=12, load_kg=100, rir=3))
    assert checks(easy, alarmed) == set()
    unknown = legs_only(PlanLine(exercise="Leg press", sets=4, quantity=12, load_kg=100))
    assert checks(unknown, alarmed) == {"prescription", "critical_alert"}


@pytest.mark.parametrize("note", ["to failure", "last set AMRAP", "new PR", "1RM"])
def test_failure_words_in_a_note_are_a_max_on_the_legs(ctx, note):
    line = PlanLine(exercise="Leg press", sets=3, quantity=12, load_kg=100, rir=3, notes=note)
    assert checks(legs_only(line), ctx) == {"no_failure_on_legs"}


@pytest.mark.parametrize("note", ["stay 2 reps from failure", "3 séries pr le quad"])
def test_prudent_notes_are_not_a_max(ctx, note):
    line = PlanLine(exercise="Leg press", sets=3, quantity=12, load_kg=100, rir=3, notes=note)
    assert checks(legs_only(line), ctx) == set()


def test_an_amrap_metcon_is_not_a_max_attempt(ctx):
    assert ctx.target_week.phase not in ("peak", "test")
    rule = guardrail.Rule(code="no_max_before_test", text="No max before the test.", params={})
    plan = good_plan()
    metcon = plan.sessions[0].parts[-1]
    assert metcon.kind == "metcon"
    metcon.lines[0].notes = "AMRAP 12 min, steady"
    assert list(guardrail.rule_no_max_before_test(rule, plan, ctx)) == []


def test_rule_checks_know_the_fresh_first_rule():
    rule = guardrail.Rule(code="fresh_first", text="Fresh first.", params={})
    plan = good_plan()
    plan.sessions[0].parts.reverse()  # metcon first
    violations = list(guardrail.rule_fresh_first(rule, plan, None))
    assert [v.check for v in violations] == ["fresh_first"]


# Graph and proposals


def test_a_refused_plan_is_corrected_with_the_guardrail_reasons(conn, program):
    bad = good_plan()
    bad.sessions[1].parts[0].lines[0].rir = 0
    planner = Scripted(bad, good_plan())

    result = run_week_planner(conn, planner, week_number=2, today=TODAY)

    assert result.accepted and result.attempts == 2
    assert planner.feedback[0] == []
    assert "no_failure_on_legs" in planner.feedback[1][0]
    assert conn.execute("select count(*) from proposal").fetchone() == (0,)  # dry run


def test_a_plan_still_refused_after_the_retries_proposes_nothing(conn, program):
    bad = good_plan()
    bad.sessions[0].day = date(2026, 4, 1)
    planner = Scripted(bad, bad, bad)

    result = run_week_planner(conn, planner, week_number=2, today=TODAY, propose=True)

    assert not result.accepted and result.attempts == 3
    assert result.proposal_ids == []
    assert conn.execute("select count(*) from proposal").fetchone() == (0,)


def test_an_unparsable_answer_counts_as_a_refused_attempt(conn, program):
    planner = Scripted(PlannerOutputError("not JSON"), good_plan())

    result = run_week_planner(conn, planner, week_number=2, today=TODAY)

    assert result.accepted and result.attempts == 2
    assert "not JSON" in planner.feedback[1][0]


def test_an_accepted_plan_becomes_proposals_that_create_the_week(conn, program):
    result = run_week_planner(conn, Scripted(good_plan()), week_number=2, today=TODAY, propose=True)

    rows = conn.execute(
        "select kind, author, status, rationale from proposal order by id"
    ).fetchall()
    assert [r[:3] for r in rows] == [("create_session", "week_planner", "pending")] * 2
    assert rows[0][3].startswith("Bench press was 52.5 kg")

    domain.decide(conn, result.proposal_ids[0], approve=True)
    domain.apply(conn, result.proposal_ids[0])
    week = conn.execute(
        "select w.number, s.source from planned_session s join training_week w on w.id = s.week_id"
        " where s.title = 'Weightlifting + Push + Metcon' and s.day = '2026-03-09'"
    ).fetchone()
    assert week == (2, "agent")
    lines = conn.execute(
        "select count(*) from session_line l join planned_session s on s.id = l.session_id"
        " where s.day = '2026-03-09' and l.origin = 'planned'"
    ).fetchone()
    assert lines == (5,)


def test_a_plan_can_replace_a_draft_session(conn, program):
    draft = domain.create_session(
        conn, domain.SessionIn(day=date(2026, 3, 10), title="Draft", week_id=2)
    )
    planner = Scripted(good_plan(cancel_session_ids=[draft]))

    result = run_week_planner(conn, planner, week_number=2, today=TODAY, propose=True)

    kinds = conn.execute("select kind from proposal order by id").fetchall()
    assert result.accepted and kinds[0] == ("cancel_session",)


# The Mistral planner, without calling Mistral


def test_the_user_message_carries_the_context_and_the_feedback(ctx):
    text = user_message(ctx, ["[days] outside the week"])
    assert "Program week 2 (2026-03-09 to 2026-03-15)" in text
    assert '"phase":"volume"' in text
    assert "- [days] outside the week" in text


class FakeStructuredLLM:
    def __init__(self, out):
        self.out = out
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return self.out


class FakeRaw:
    usage_metadata = {"input_tokens": 1200, "output_tokens": 300}


def test_the_mistral_planner_counts_tokens_and_checks_the_output(ctx):
    planner = MistralPlanner(api_key="test-key", model="mistral-small-latest", language="French")
    planner._llm = FakeStructuredLLM(
        {"raw": FakeRaw(), "parsed": good_plan(), "parsing_error": None}
    )

    assert planner(ctx, []) == good_plan()
    assert (planner.usage.calls, planner.usage.input_tokens, planner.usage.output_tokens) == (
        1,
        1200,
        300,
    )
    assert "in French" in planner._llm.messages[0][1]

    planner._llm = FakeStructuredLLM({"raw": FakeRaw(), "parsed": None, "parsing_error": "bad"})
    with pytest.raises(PlannerOutputError):
        planner(ctx, [])


def test_plan_week_prints_the_plan_and_the_verdict(
    monkeypatch, capsys, conn, program, database_url
):
    from lifter.cli import main

    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(
        "lifter.agents.planner.MistralPlanner", lambda **kwargs: Scripted(good_plan())
    )

    assert main(["plan-week", "--week", "2", "--today", "2026-03-08"]) == 0
    out = capsys.readouterr().out
    assert "week 2 (volume), 2026-03-09 to 2026-03-15" in out
    assert "Bench press 4x10 @ 52.5 kg RIR 3" in out
    assert "guardrail: accepted after 1 attempt(s)" in out
    assert "dry run: nothing proposed" in out


def test_plan_week_needs_a_key(monkeypatch, capsys):
    from lifter.cli import main

    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("MISTRAL_API_KEY", "")
    assert main(["plan-week"]) == 2
    assert "MISTRAL_API_KEY is not set" in capsys.readouterr().out


def test_a_deload_week_is_not_the_progression_reference(conn, program, ctx):
    from lifter.agents.context import RecentLoad

    deload = RecentLoad(
        exercise="Bench press", pattern="push", reps=8, load_kg=40, rir=4, day=date(2026, 3, 7)
    )
    after_deload = ctx.model_copy(update={"recent_loads": [*ctx.recent_loads, deload]})
    plan = good_plan()
    plan.sessions[0].parts[1].lines[0] = PlanLine(
        exercise="Bench press", sets=4, quantity=8, load_kg=55, rir=2
    )
    # heaviest at 8 reps or more: 52.5 x 10, so 55 is one step up; the 40 x 8 deload is ignored
    assert "progression" not in checks(plan, after_deload)


def test_kept_draft_sessions_count_for_legs_and_for_alerts(conn, program):
    draft = domain.create_session(
        conn,
        domain.SessionIn(
            day=date(2026, 3, 12),
            title="Legs draft",
            week_id=2,
            parts=[
                domain.PartIn(
                    kind="strength",
                    planned=[domain.LineIn(exercise="Leg press", sets=3, quantity=12, rir=2)],
                )
            ],
        ),
    )
    ctx = build_context(conn, week_number=2, today=TODAY)
    legs_rule = guardrail.Rule(
        code="weekly_pattern", text="Legs every week.", params={"pattern": "legs"}
    )
    ctx = ctx.model_copy(update={"rules": [*ctx.rules, legs_rule]})
    no_legs = good_plan()
    no_legs.sessions.pop()  # the plan keeps the draft for the legs
    assert "weekly_pattern" not in checks(no_legs, ctx)
    assert "weekly_pattern" in checks(
        no_legs.model_copy(update={"cancel_session_ids": [draft]}), ctx
    )

    alert = Alert(day=TODAY, alert="abnormal_hrv", severity="critical", value=-35, threshold=-30)
    alarmed = ctx.model_copy(update={"alerts": [alert]})
    easy = WeekPlan(summary="Week 2 stays easy.", sessions=[])
    messages = [v.message for v in guardrail.check(easy, alarmed).violations]
    assert any("Legs draft" in m for m in messages)


# Stop rule


STOP = guardrail.Rule(
    code="stop_rule", text="Pain above 3/10: two steps back.", params={"pain_max": 3, "steps": 2}
)


def report_pain(conn, pain, title="Legs + Metcon", day=date(2026, 3, 7)):
    session = conn.execute(
        "select id from planned_session where title = %s and day = %s", (title, day)
    ).fetchone()
    domain.add_feedback(
        conn,
        domain.FeedbackIn(day=day, planned_session_id=session[0], pain=pain, pain_location="knee"),
    )
    ctx = build_context(conn, week_number=2, today=TODAY)
    return ctx.model_copy(update={"rules": [*ctx.rules, STOP]})


def test_pain_above_the_threshold_caps_the_session_loads_two_steps_down(conn, program):
    ctx = report_pain(conn, pain=5)
    assert [(line.exercise, line.load_kg) for line in ctx.feedback[0].lines] == [("Leg press", 105)]

    plan = good_plan()  # leg press 105 kg, as logged on the painful day
    violations = [v for v in guardrail.check(plan, ctx).violations if v.check == "stop_rule"]
    assert len(violations) == 1
    assert "at most 95 kg" in violations[0].message and "pain 5/10 (knee)" in violations[0].message

    plan.sessions[1].parts[0].lines[0].load_kg = 95
    assert "stop_rule" not in checks(plan, ctx)


def stop_rule_messages(plan, ctx):
    return [v.message for v in guardrail.check(plan, ctx).violations if v.check == "stop_rule"]


def test_the_cap_covers_the_whole_pattern_of_the_painful_session(conn, program):
    ctx = report_pain(conn, pain=5)  # knee, after leg press 105 kg
    plan = good_plan()
    plan.sessions[1].parts[0].lines = [
        PlanLine(exercise="Leg press", sets=4, quantity=12, load_kg=95, rir=3),
        PlanLine(exercise="Leg curl", sets=4, quantity=12, load_kg=80, rir=3),
    ]
    # Leg curl is on the same pattern (legs) and has no logged load to step back from
    (message,) = stop_rule_messages(plan, ctx)
    assert "'Leg curl' at 80 kg on a painful pattern without a logged load" in message

    logged = RecentLoad(
        exercise="Leg curl", pattern="legs", reps=12, load_kg=40, rir=3, day=date(2026, 3, 4)
    )
    ctx = ctx.model_copy(update={"recent_loads": [*ctx.recent_loads, logged]})
    (message,) = stop_rule_messages(plan, ctx)
    assert "40 kg its heaviest logged load, so at most 30 kg" in message
    plan.sessions[1].parts[0].lines[1].load_kg = 30
    assert stop_rule_messages(plan, ctx) == []


def test_a_light_pain_free_session_on_the_pattern_keeps_the_painful_exercise_capped(ctx):
    from lifter.agents.context import Feedback, LineInfo

    def fb(day, pain, exercise, load):
        line = LineInfo(
            exercise=exercise,
            sets=3,
            quantity=12,
            unit="reps",
            load_kg=load,
            load_kg_max=None,
            rir=3,
        )
        return Feedback(
            day=day,
            kind="session",
            session_id=None,
            session_title="Legs",
            lines=[line],
            rpe=None,
            fatigue=None,
            pain=pain,
            pain_location="knee",
        )

    feedback = [fb(date(2026, 3, 6), 5, "Leg press", 105), fb(date(2026, 3, 7), 0, "Leg curl", 20)]
    ctx = ctx.model_copy(update={"feedback": feedback, "rules": [*ctx.rules, STOP]})
    plan = good_plan()
    plan.sessions[1].parts[0].lines[0].load_kg = 110
    (message,) = stop_rule_messages(plan, ctx)
    assert "'Leg press' at 110 kg" in message and "at most 95 kg" in message


def test_another_pattern_is_not_capped(conn, program):
    ctx = report_pain(conn, pain=5)
    plan = good_plan()
    plan.sessions[1].parts[0].lines.append(
        PlanLine(exercise="Romanian deadlift", sets=3, quantity=8, load_kg=90, rir=3)
    )
    plan.sessions[1].parts[0].lines[0].load_kg = 95
    assert stop_rule_messages(plan, ctx) == []  # hinge, the painful session loaded legs only


def test_pain_at_or_under_the_threshold_changes_nothing(conn, program):
    ctx = report_pain(conn, pain=3)
    assert "stop_rule" not in checks(good_plan(), ctx)


def test_pain_without_a_loaded_session_is_a_warning(conn, program):
    domain.add_feedback(
        conn, domain.FeedbackIn(day=TODAY, kind="morning", pain=6, pain_location="shoulder")
    )
    ctx = build_context(conn, week_number=2, today=TODAY)
    ctx = ctx.model_copy(update={"rules": [*ctx.rules, STOP]})

    verdict = guardrail.check(good_plan(), ctx)
    assert "stop_rule" not in {v.check for v in verdict.violations}
    assert any("pain 6/10" in w and "not checked by code" in w for w in verdict.warnings)


def test_a_later_pain_free_session_lifts_the_cap(conn, program):
    report_pain(conn, pain=5)  # legs on 2026-03-07, leg press 105
    later = domain.create_session(
        conn,
        domain.SessionIn(
            day=date(2026, 3, 8),
            title="Legs check",
            parts=[
                domain.PartIn(
                    kind="strength",
                    done=[domain.LineIn(exercise="Leg press", sets=2, quantity=10, load_kg=95)],
                )
            ],
        ),
    )
    domain.add_feedback(
        conn, domain.FeedbackIn(day=date(2026, 3, 8), planned_session_id=later, pain=0)
    )
    ctx = build_context(conn, week_number=2, today=TODAY)
    ctx = ctx.model_copy(update={"rules": [*ctx.rules, STOP]})

    assert "stop_rule" not in checks(good_plan(), ctx)


def test_the_cap_starts_from_the_heaviest_load_of_the_painful_day(conn, program):
    session = domain.create_session(
        conn,
        domain.SessionIn(
            day=date(2026, 3, 8),
            title="Push with back-off",
            parts=[
                domain.PartIn(
                    kind="strength",
                    done=[
                        domain.LineIn(exercise="Bench press", sets=4, quantity=8, load_kg=65),
                        domain.LineIn(exercise="Bench press", sets=1, quantity=10, load_kg=50),
                    ],
                )
            ],
        ),
    )
    domain.add_feedback(
        conn, domain.FeedbackIn(day=date(2026, 3, 8), planned_session_id=session, pain=5)
    )
    ctx = build_context(conn, week_number=2, today=TODAY)
    ctx = ctx.model_copy(update={"rules": [*ctx.rules, STOP]})

    plan = good_plan()
    plan.sessions[0].parts[1].lines[0].load_kg = 60  # 65 − 2 × 2.5
    assert "stop_rule" not in checks(plan, ctx)
    plan.sessions[0].parts[1].lines[0].load_kg = 62.5
    assert "stop_rule" in checks(plan, ctx)
