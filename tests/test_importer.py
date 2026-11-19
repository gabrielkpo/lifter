"""lifter import: a log kept elsewhere, written through the coach's write path."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from lifter import operations
from lifter.api.hosted import coach_urls
from lifter.config import Settings
from lifter.conversation import start
from lifter.db import connect
from lifter.importer import ImportFile, read_import, run_import
from lifter.program import load_program, read_program

EXAMPLE = Path(__file__).parent.parent / "examples" / "program.yaml"

LOG = {
    "title": "Journal de mars",
    "items": [
        {
            "key": "s-03-12",
            "said": "Jeudi 12/03, push : bench 4x6 à 55 kg RIR 2, dips 3x6",
            "op": "create_session",
            "ref": "push-12",
            "payload": {
                "day": "2026-03-12",
                "title": "Push",
                "parts": [
                    {
                        "kind": "strength",
                        "done": [
                            {
                                "exercise": "Bench press",
                                "sets": 4,
                                "quantity": 6,
                                "load_kg": 55,
                                "rir": 2,
                            },
                            {"exercise": "Dips", "sets": 3, "quantity": 6},
                        ],
                    }
                ],
            },
        },
        {
            "key": "f-03-12",
            "said": "Après le push du 12/03 : fatigue 2, aucune douleur, séance facile",
            "op": "add_feedback",
            "payload": {
                "day": "2026-03-12",
                "planned_session_id": "$push-12",
                "fatigue": 2,
                "pain": 0,
                "notes": "Séance facile",
            },
        },
        {
            "key": "s-03-04",
            "said": "Mercredi 04/03, pull fait : tractions strictes 4x5, rowing 3x10 à 37,5 kg",
            "op": "log_session",
            "payload": {
                "session_id": {"$id": ["planned_session", {"day": "2026-03-04"}]},
                "parts": [
                    {
                        "part_id": {
                            "$id": [
                                "session_part",
                                {
                                    "session_id": {
                                        "$id": ["planned_session", {"day": "2026-03-04"}]
                                    },
                                    "kind": "strength",
                                },
                            ]
                        },
                        "expected_version": "$current",
                        "done": [
                            {"exercise": "Strict pull-up", "sets": 4, "quantity": 5},
                            {"exercise": "Barbell row", "sets": 3, "quantity": 10, "load_kg": 37.5},
                        ],
                    }
                ],
            },
        },
    ],
}


@pytest.fixture(autouse=True)
def no_rule_check():
    operations.set_programme_check(lambda conn, week: [], lambda before, after: [])
    yield
    operations._programme_check = None


@pytest.fixture
def roles(conn, database_url):
    load_program(conn, read_program(EXAMPLE))
    chat_url, coach_url = coach_urls(
        Settings.from_env({"DATABASE_URL": database_url}), hosted=False
    )
    assert chat_url and coach_url
    with connect(chat_url) as chat, connect(coach_url) as coach:
        yield chat, coach


def test_a_log_is_written_traced_and_once(conn, roles):
    chat, coach = roles
    outcomes = run_import(ImportFile.model_validate(LOG), chat, coach)

    assert [o.skipped for o in outcomes] == [False, False, False]
    # every item is a traced change, authorised by its own words, as the athlete
    rows = conn.execute(
        "select p.kind, p.author, m.text from change_log c join proposal p on p.id = c.proposal_id"
        " join conversation_message m on m.id = p.message_id order by c.id"
    ).fetchall()
    assert [(k, a) for k, a, _ in rows] == [
        ("create_session", "athlete"),
        ("add_feedback", "athlete"),
        ("log_session", "athlete"),
    ]
    assert rows[0][2].startswith("Jeudi 12/03")
    feedback = conn.execute("select planned_session_id, fatigue from feedback").fetchone()
    assert feedback == (outcomes[0].entity_id, 2)
    rows_done = conn.execute(
        "select e.load_kg from session_exercise e join session_part p on p.id = e.part_id"
        " join planned_session s on s.id = p.session_id"
        " where s.day = '2026-03-04' and e.origin = 'done' and e.load_kg is not null"
    ).fetchall()
    assert rows_done == [(37.5,)]

    again = run_import(ImportFile.model_validate(LOG), chat, coach)
    assert [o.skipped for o in again] == [True, True, True]
    assert [o.entity_id for o in again] == [o.entity_id for o in outcomes]
    assert conn.execute("select count(*) from change_log").fetchone() == (3,)


def test_an_imported_change_can_be_undone(conn, roles):
    chat, coach = roles
    run_import(ImportFile.model_validate(LOG), chat, coach)
    change_id = conn.execute(
        "select c.id from change_log c join proposal p on p.id = c.proposal_id"
        " where p.kind = 'add_feedback'"
    ).fetchone()[0]
    text = "annule le retour du 12/03, je l'ai mal noté"
    start(conn, id="app", title=text, source="app")
    message_id = conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('app', 'athlete', %s) returning id",
        (text,),
    ).fetchone()[0]
    operations.run(
        conn,
        "undo",
        {"change_id": change_id},
        conversation_id="app",
        quote=text,
        message_id=message_id,
        idempotency_key="undo-1",
        author="athlete",
    )
    assert conn.execute("select count(*) from feedback").fetchone() == (0,)


def test_undo_is_not_an_import_item():
    undo = {
        "title": "Correction",
        "items": [{"key": "u", "said": "annule le changement 3", "op": "undo"}],
    }
    with pytest.raises(ValidationError, match="unknown operation"):
        ImportFile.model_validate(undo)  # undoing stays the athlete's, in the app or the coach


def test_a_reference_to_nothing_stops_the_import(conn, roles):
    chat, coach = roles
    log = {
        "title": "Journal cassé",
        "items": [
            {
                "key": "f",
                "said": "Retour du 12/03 : fatigue 2, aucune douleur",
                "op": "add_feedback",
                "payload": {"day": "2026-03-12", "planned_session_id": "$nowhere"},
            }
        ],
    }
    with pytest.raises(operations.OperationError, match="no earlier item"):
        run_import(ImportFile.model_validate(log), chat, coach)
    assert conn.execute("select count(*) from feedback").fetchone() == (0,)


def test_a_file_is_checked_before_anything_runs(tmp_path):
    bad = dict(LOG, items=[*LOG["items"], dict(LOG["items"][0])])  # the same key twice
    path = tmp_path / "log.yaml"
    path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError, match="key used twice"):
        read_import(path)


def test_the_command_imports_a_file_and_reports_each_item(
    conn, database_url, tmp_path, monkeypatch, capsys
):
    from lifter.cli import main

    load_program(conn, read_program(EXAMPLE))
    path = tmp_path / "log.yaml"
    path.write_text(yaml.safe_dump(LOG, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("LIFTER_CHAT_DATABASE_URL", raising=False)
    monkeypatch.delenv("LIFTER_COACH_DATABASE_URL", raising=False)
    assert main(["import", str(path)]) == 0  # a preview first: nothing written
    out = capsys.readouterr().out
    assert "s-03-12: create_session to apply" in out and "3 to apply, nothing written" in out
    assert conn.execute("select count(*) from change_log").fetchone() == (0,)
    assert main(["import", str(path), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "s-03-12: create_session applied" in out and "3 applied, 0 already there" in out
    assert main(["import", str(path), "--apply"]) == 0
    assert "0 applied, 3 already there" in capsys.readouterr().out
    assert main(["import", str(path)]) == 0
    assert "f-03-12: add_feedback already applied" in capsys.readouterr().out

    broken = tmp_path / "broken.yaml"
    broken.write_text("title: x\nitems: []\n", encoding="utf-8")
    assert main(["import", str(broken)]) == 2
    broken.write_text("title: [x\n", encoding="utf-8")  # not YAML: said, no traceback
    assert main(["import", str(broken)]) == 2
    assert "not valid YAML" in capsys.readouterr().out

    unknown = tmp_path / "unknown.yaml"
    item = {
        "key": "s",
        "said": "Vendredi 13/03 : séance de lancers",
        "op": "create_session",
        "payload": {
            "day": "2026-03-13",
            "title": "Lancers",
            "parts": [{"kind": "strength", "done": [{"exercise": "Javelin", "sets": 1}]}],
        },
    }
    unknown.write_text(yaml.safe_dump({"title": "Inconnu", "items": [item]}), encoding="utf-8")
    for _ in range(2):  # stopped, not a traceback; the second run writes no second message
        assert main(["import", str(unknown), "--apply"]) == 1
        assert "stopped:" in capsys.readouterr().out
    said = "select count(*) from conversation_message where text = %s"
    assert conn.execute(said, (item["said"],)).fetchone() == (1,)


def test_a_key_applied_with_other_words_is_not_skipped(conn, roles):
    chat, coach = roles
    run_import(ImportFile.model_validate(LOG), chat, coach)
    other = {
        "title": LOG["title"],
        "items": [dict(LOG["items"][0], said="Jeudi 12/03, push : bench 5x5 à 60 kg")],
    }
    with pytest.raises(operations.OperationError, match="applied with other words"):
        run_import(ImportFile.model_validate(other), chat, coach)


def test_a_dollar_amount_in_a_text_is_text(conn, roles):
    chat, coach = roles
    log = {
        "title": "Note",
        "items": [
            {
                "key": "n",
                "said": "Note de méthode : la ceinture a coûté $5 de plus",
                "op": "add_coaching_note",
                "payload": {"title": "Matériel", "text": "$5 de plus pour la ceinture"},
            }
        ],
    }
    run_import(ImportFile.model_validate(log), chat, coach)
    assert conn.execute("select text from coaching_note").fetchone() == (
        "$5 de plus pour la ceinture",
    )


def test_a_ref_a_payload_could_not_name_is_refused():
    log = dict(LOG, items=[dict(LOG["items"][0], ref="12-push")])
    with pytest.raises(ValidationError, match="ref '12-push'"):
        ImportFile.model_validate(log)


@pytest.mark.parametrize("target", ["planned_session", ["planned_session"], [1, {}]])
def test_an_id_lookup_of_the_wrong_shape_is_refused(conn, roles, target):
    chat, coach = roles
    log = {
        "title": "Forme",
        "items": [
            {
                "key": "f",
                "said": "Retour du 12/03 : fatigue 2, aucune douleur",
                "op": "add_feedback",
                "payload": {"day": "2026-03-12", "planned_session_id": {"$id": target}},
            }
        ],
    }
    with pytest.raises(operations.OperationError, match=r"\$id"):
        run_import(ImportFile.model_validate(log), chat, coach)


def test_an_id_lookup_takes_one_value_per_column(conn, roles):
    chat, coach = roles
    lookup = {"$id": ["planned_session", {"day": {"nested": 1}}]}
    log = {
        "title": "Forme",
        "items": [
            {
                "key": "f",
                "said": "Retour du 12/03 : fatigue 2, aucune douleur",
                "op": "add_feedback",
                "payload": {"day": "2026-03-12", "planned_session_id": lookup},
            }
        ],
    }
    with pytest.raises(operations.OperationError, match="one value"):
        run_import(ImportFile.model_validate(log), chat, coach)


def test_an_item_undone_since_is_reported_and_names_nothing(conn, roles):
    chat, coach = roles
    first = {**LOG, "items": LOG["items"][:1]}  # the session alone
    run_import(ImportFile.model_validate(first), chat, coach)
    change_id = conn.execute("select max(id) from change_log").fetchone()[0]
    text = "annule la séance du 12/03"
    start(conn, id="app", title=text, source="app")
    message_id = conn.execute(
        "insert into conversation_message (conversation_id, role, text)"
        " values ('app', 'athlete', %s) returning id",
        (text,),
    ).fetchone()[0]
    operations.run(
        conn,
        "undo",
        {"change_id": change_id},
        conversation_id="app",
        quote=text,
        message_id=message_id,
        idempotency_key="undo-push",
        author="athlete",
    )
    again = run_import(ImportFile.model_validate(first), chat, coach)
    assert [(o.skipped, o.undone) for o in again] == [(True, True)]
    with pytest.raises(operations.OperationError, match="undone since"):
        run_import(ImportFile.model_validate(LOG), chat, coach)  # the feedback names it
    assert conn.execute("select count(*) from feedback").fetchone() == (0,)


def test_a_destructive_item_needs_to_be_allowed_by_name(
    conn, database_url, tmp_path, monkeypatch, capsys
):
    from lifter.cli import main

    load_program(conn, read_program(EXAMPLE))
    item = {
        "key": "d",
        "said": "Supprime la note de méthode Échauffement",
        "op": "delete_coaching_note",
        "payload": {"id": 1, "expected_version": 1},
    }
    path = tmp_path / "log.yaml"
    path.write_text(yaml.safe_dump({"title": "Ménage", "items": [item]}), encoding="utf-8")
    monkeypatch.setattr("lifter.config.load_dotenv", lambda: None)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("LIFTER_CHAT_DATABASE_URL", raising=False)
    monkeypatch.delenv("LIFTER_COACH_DATABASE_URL", raising=False)
    assert main(["import", str(path)]) == 0  # the preview shows it
    assert "d: delete_coaching_note to apply (needs --allow-destructive)" in capsys.readouterr().out
    assert main(["import", str(path), "--apply"]) == 2
    assert "d (delete_coaching_note)" in capsys.readouterr().out
    assert conn.execute("select count(*) from conversation_message").fetchone() == (0,)
