"""The quote check (agents/quote.py) and the guardrail on a stored week (agents/week_check.py),
the two checks the coach's write path runs before applying a change (ADR 0002)."""

from pathlib import Path

import pytest

from lifter import domain
from lifter.agents.context import PlanningError
from lifter.agents.quote import QuoteError, check_quote, normalize, verify_quote
from lifter.agents.week_check import introduced, violations_for_week
from lifter.program import load_program, read_program

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"


# Quote


def test_a_quote_copied_from_the_message_passes():
    check_quote("décale jeudi à vendredi", "Salut ! Décale jeudi… non : décale jeudi à vendredi.")


def test_only_formatting_is_normalised():
    # French guillemets keep their inner spaces: only the characters change
    assert normalize("l’haltéro  du\n« jeudi »") == 'l\'haltéro du " jeudi "'
    check_quote("l'haltéro du jeudi", "Passe l’haltéro   du jeudi en fin de séance")
    check_quote("été lourd", "un été lourd")  # decomposed accents (NFD)


@pytest.mark.parametrize(
    ("quote", "message", "short_ok", "reason"),
    [
        ("décale vendredi", "décale jeudi à vendredi", False, "not in"),  # paraphrase
        ("Décale jeudi", "décale jeudi à vendredi", False, "not in"),  # case is kept
        ("ok", "ok pour la 2", False, "at least 2 words"),
        ("   ", "ok", True, "cites nothing"),
    ],
)
def test_anything_but_the_athletes_words_is_refused(quote, message, short_ok, reason):
    with pytest.raises(QuoteError, match=reason):
        check_quote(quote, message, short_ok=short_ok)


def test_a_short_quote_passes_where_the_operation_allows_it():
    check_quote("annule", "annule", short_ok=True)
    check_quote("ok pour la 2", "ok pour la 2", short_ok=False)


@pytest.fixture
def messages(conn):
    # The table belongs to the app's migration; a temporary one stands in for it here.
    conn.execute(
        "create temp table conversation_message (id bigint primary key, role text, text text)"
    )
    conn.execute(
        "insert into conversation_message values"
        " (1, 'athlete', 'Décale jeudi à vendredi stp'),"
        " (2, 'coach', 'Je propose de décaler jeudi à vendredi')"
    )
    yield
    conn.execute("drop table pg_temp.conversation_message")


def test_the_quote_is_read_from_the_athletes_stored_message(conn, messages):
    verify_quote(conn, 1, "Décale jeudi à vendredi")
    with pytest.raises(QuoteError, match="not from the athlete"):
        verify_quote(conn, 2, "décaler jeudi à vendredi")  # the coach's own words
    with pytest.raises(QuoteError, match="does not exist"):
        verify_quote(conn, 99, "Décale jeudi")


# Guardrail on a stored week


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


def week_id(conn, number):
    return conn.execute("select id from training_week where number = %s", (number,)).fetchone()[0]


def add_planned_line(conn, title, exercise, **line):
    part = conn.execute(
        "select sp.id from session_part sp join planned_session p on p.id = sp.session_id"
        " where p.title = %s and sp.kind = 'strength' order by sp.position limit 1",
        (title,),
    ).fetchone()[0]
    conn.execute(
        "insert into session_exercise (part_id, origin, position, exercise_id, sets, quantity,"
        " load_kg, rir) select %s, 'planned', 99, id, %s, %s, %s, %s from exercise where name = %s",
        (
            part,
            line.get("sets"),
            line.get("quantity"),
            line.get("load_kg"),
            line.get("rir"),
            exercise,
        ),
    )


def test_a_valid_stored_week_has_no_violation(conn, program):
    assert violations_for_week(conn, week_id(conn, 1)) == []


def test_a_change_that_breaks_a_rule_is_reported_as_introduced(conn, program):
    week = week_id(conn, 1)
    before = violations_for_week(conn, week)
    add_planned_line(conn, "Legs + Metcon", "Back squat", sets=3, quantity=5, load_kg=60, rir=2)
    after = violations_for_week(conn, week)

    new = introduced(before, after)
    assert [v.check for v in new] == ["forbid_flag"]
    assert "Back squat" in new[0].message


def test_an_old_violation_does_not_block_an_unrelated_change(conn, program):
    week = week_id(conn, 1)
    add_planned_line(conn, "Legs + Metcon", "Back squat", sets=3, quantity=5, load_kg=60, rir=2)
    before = violations_for_week(conn, week)
    sid = conn.execute("select id from planned_session where title = 'Benchmark metcon'").fetchone()
    domain.move_session(conn, domain.MoveSession(session_id=sid[0], new_day="2026-03-08"))
    after = violations_for_week(conn, week)

    assert before and introduced(before, after) == []


def test_cancelled_sessions_are_not_checked(conn, program):
    week = week_id(conn, 1)
    add_planned_line(conn, "Legs + Metcon", "Box jump", quantity=10)
    sid = conn.execute("select id from planned_session where title = 'Legs + Metcon'").fetchone()
    domain.cancel_session(conn, domain.CancelSession(session_id=sid[0]))
    assert violations_for_week(conn, week) == []


def test_an_unknown_week_is_refused(conn, program):
    with pytest.raises(PlanningError):
        violations_for_week(conn, 999)
