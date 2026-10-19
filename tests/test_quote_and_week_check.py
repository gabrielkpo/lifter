"""The quote check (lifter/quote.py) and the guardrail on a stored week (agents/week_check.py),
the two checks the coach's write path runs before applying a change (ADR 0002)."""

from pathlib import Path

import pytest

from lifter import domain
from lifter.agents.context import PlanningError
from lifter.agents.week_check import introduced, violations_for_week
from lifter.conversation import start
from lifter.program import load_program, read_program
from lifter.quote import QuoteError, check_quote, normalize, verify_quote

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"


# Quote


def test_a_quote_copied_from_the_message_passes():
    message = "Salut ! Décale jeudi… non : décale jeudi à vendredi."
    assert check_quote("décale jeudi à vendredi", message) is None


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
    assert check_quote("annule", "annule !", short_ok=True) is None
    assert check_quote("ok", "ok.", short_ok=True) is None
    # one content word ("2"): enough to pick a suggestion, not to justify a change
    assert check_quote("ok pour la 2", "Super, ok pour la 2", short_ok=True) is None
    with pytest.raises(QuoteError, match="besides words such as"):
        check_quote("ok pour la 2", "Super, ok pour la 2")


@pytest.mark.parametrize(
    ("quote", "message"),
    [
        ("la semaine", "ok pour la semaine, mais pas de squat"),  # two function-ish words
        ("ok pour", "ok pour la 2"),
        ("the week", "fine for the week"),
    ],
)
def test_function_words_alone_justify_nothing(quote, message):
    with pytest.raises(QuoteError, match="besides words such as"):
        check_quote(quote, message)


@pytest.mark.parametrize(
    ("quote", "message", "short_ok"),
    [
        ("ok pour la 2", "pas ok pour la 2", True),
        ("annule la séance", "n'annule la séance que s'il pleut", False),
        ("move Thursday", "don't move Thursday", False),
    ],
)
def test_a_negated_quote_is_refused(quote, message, short_ok):
    with pytest.raises(QuoteError, match="negated"):
        check_quote(quote, message, short_ok=short_ok)


def test_plus_means_more_not_a_negation():
    assert check_quote("lourd le bench jeudi", "mets un peu plus lourd le bench jeudi") is None


def test_a_quote_also_found_without_its_negation_passes():
    message = "Ne décale pas jeudi. Enfin si, décale jeudi à vendredi."
    assert check_quote("décale jeudi", message) is None


@pytest.mark.parametrize(
    "message",
    [
        "non, c'est pas ok, ne change rien",  # a negation around the short word
        "je regarde le book des séances",  # the letters inside another word
        "ok mais attends demain",  # the short word inside a longer message
    ],
)
def test_a_short_quote_never_matches_inside_a_longer_message(message):
    with pytest.raises(QuoteError, match="whole message"):
        check_quote("ok", message, short_ok=True)


def test_quotes_match_whole_words_only():
    with pytest.raises(QuoteError, match="not in"):
        check_quote("cale jeudi", "décale jeudi à vendredi")  # a piece of a word
    check_quote("jeudi à vendredi", "décale jeudi à vendredi !")


@pytest.fixture
def messages(conn):
    """An athlete's message and a coach's reply, as the conversation endpoint stores them."""
    start(conn, id="c1", title="Décale jeudi à vendredi stp", source="cli")
    rows = conn.execute(
        "insert into conversation_message (conversation_id, role, text) values"
        " ('c1', 'athlete', 'Décale jeudi à vendredi stp'),"
        " ('c1', 'coach', 'Je propose de décaler jeudi à vendredi') returning id"
    ).fetchall()
    return [r[0] for r in rows]


def test_the_quote_is_read_from_the_athletes_stored_message(conn, messages):
    athlete, coach = messages
    assert verify_quote(conn, athlete, "Décale jeudi à vendredi") is None
    with pytest.raises(QuoteError, match="not from the athlete"):
        verify_quote(conn, coach, "décaler jeudi à vendredi")  # the coach's own words
    with pytest.raises(QuoteError, match="does not exist"):
        verify_quote(conn, coach + 99, "Décale jeudi")


def test_a_temporary_table_cannot_stand_in_for_the_stored_messages(conn, messages):
    conn.execute("create temp table conversation_message (id bigint, role text, text text)")
    conn.execute(
        "insert into conversation_message values (%s, 'athlete', 'supprime tout')",
        (messages[1] + 50,),
    )
    with pytest.raises(QuoteError, match="does not exist"):
        verify_quote(conn, messages[1] + 50, "supprime tout")
    conn.execute("drop table pg_temp.conversation_message")


# Guardrail on a stored week


@pytest.fixture
def program(conn):
    load_program(conn, read_program(EXAMPLE))


def week_id(conn, number):
    return conn.execute("select id from training_week where number = %s", (number,)).fetchone()[0]


def add_planned_line(conn, title, exercise, position=99, **line):
    part = conn.execute(
        "select sp.id from session_part sp join planned_session p on p.id = sp.session_id"
        " where p.title = %s and sp.kind = 'strength' order by sp.position limit 1",
        (title,),
    ).fetchone()[0]
    conn.execute(
        "insert into session_exercise (part_id, origin, position, exercise_id, sets, quantity,"
        " load_kg, rir) select %s, 'planned', %s, id, %s, %s, %s, %s from exercise where name = %s",
        (
            part,
            position,
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


def test_moving_the_session_at_fault_introduces_nothing(conn, program):
    week = week_id(conn, 1)
    add_planned_line(conn, "Legs + Metcon", "Back squat", sets=3, quantity=5, load_kg=60, rir=2)
    before = violations_for_week(conn, week)
    sid = conn.execute("select id from planned_session where title = 'Legs + Metcon'").fetchone()
    day = conn.execute("select day + 1 from planned_session where id = %s", sid).fetchone()[0]
    domain.move_session(conn, domain.MoveSession(session_id=sid[0], new_day=day))
    after = violations_for_week(conn, week)

    assert [v.day for v in before] != [v.day for v in after]
    assert introduced(before, after) == []


def test_a_second_identical_violation_is_introduced(conn, program):
    week = week_id(conn, 1)
    add_planned_line(conn, "Legs + Metcon", "Back squat", sets=3, quantity=5, load_kg=60, rir=2)
    before = violations_for_week(conn, week)
    add_planned_line(conn, "Legs + Metcon", "Back squat", 98, sets=2, quantity=5, load_kg=60, rir=2)
    after = violations_for_week(conn, week)

    assert [v.check for v in introduced(before, after)] == ["forbid_flag"]
