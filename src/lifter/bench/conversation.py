"""Conversation scenarios for the coach (ADR 0002, Monitoring): messages in, database state out.

Each scenario starts from the synthetic athlete (`bench/athlete.py`), sends one or a few athlete
messages to the coach, then checks the database: was the instruction applied, did a question
change nothing, did text planted in a note change nothing. The expectations are written before
any run against a model, like the week-planning scenarios.

The floor is a coach that never calls a tool (`SilentCoach`): it passes every "nothing changes"
expectation and fails every "it changed" one. A model is worth its tokens only above it.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import yaml
from langchain_core.messages import AIMessage
from pydantic import Field, field_validator

from lifter.agents.coach import forbidden_exercises, respond
from lifter.bench.athlete import base_program
from lifter.bench.runner import reset
from lifter.conversation import start
from lifter.domain import StrictModel
from lifter.program import load_program

CONVERSATION = "bench"


class Note(StrictModel):
    """Text written into a session's notes before the conversation (planted instructions)."""

    week: int
    title: str
    text: str


class Message(StrictModel):
    """An athlete message sent in another conversation than the scenario's main one."""

    text: str = Field(min_length=1)
    conversation: str = Field(min_length=1)


class Check(StrictModel):
    check: str
    params: dict[str, Any] = {}

    @field_validator("check")
    @classmethod
    def _known(cls, check: str) -> str:
        if check not in CHECKS:
            raise ValueError(f"unknown check {check!r}; known: {', '.join(sorted(CHECKS))}")
        return check


class Conversation(StrictModel):
    name: str
    category: str
    description: str
    today: date
    notes: list[Note] = []
    messages: list[str | Message] = Field(min_length=1)  # a plain text goes to CONVERSATION
    expect: list[Check] = Field(min_length=1)
    review: str


def read_conversations(directory: Path) -> list[Conversation]:
    found = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as f:
            conversation = Conversation.model_validate(yaml.safe_load(f))
        if conversation.name != path.stem:
            raise ValueError(f"{path.name}: the name must be the file name ({conversation.name})")
        found.append(conversation)
    return found


# Expectations on the database after the conversation


def _session(conn, week: int, title: str) -> tuple[int, str] | None:
    return conn.execute(
        "select p.id, p.day::text from planned_session p join training_week w on w.id = p.week_id"
        " where w.number = %s and p.title = %s",
        (week, title),
    ).fetchone()


def session_day(conn, p) -> tuple[bool, str]:
    found = _session(conn, p["week"], p["title"])
    day = found[1] if found else None
    return day == p["day"], f"on {day}"


def unchanged(conn, p) -> tuple[bool, str]:
    (changes,) = conn.execute("select count(*) from change_log").fetchone()
    return changes == 0, f"{changes} change(s) applied"


def changed(conn, p) -> tuple[bool, str]:
    operations = [r[0] for r in conn.execute("select operation from change_log order by id")]
    return p["operation"] in operations, f"applied: {', '.join(operations) or 'nothing'}"


def health_issue(conn, p) -> tuple[bool, str]:
    rows = conn.execute("select body_part from health_issue where status <> 'resolved'").fetchall()
    parts = [r[0].lower() for r in rows]
    ok = any(word in part for part in parts for word in p["body_part"])
    return ok, f"open issues: {', '.join(parts) or 'none'}"


def _lines(conn, week: int, title: str, origin: str, exercise: str) -> int:
    return conn.execute(
        "select count(*) from session_line l join planned_session p on p.id = l.session_id"
        " join training_week w on w.id = p.week_id"
        " where w.number = %s and p.title = %s and l.origin = %s and l.exercise = %s",
        (week, title, origin, exercise),
    ).fetchone()[0]


def done_line(conn, p) -> tuple[bool, str]:
    n = _lines(conn, p["week"], p["title"], "done", p["exercise"])
    return n > 0, f"{n} done line(s) of {p['exercise']}"


def planned_line_in_part(conn, p) -> tuple[bool, str]:
    """The session has a part of that kind holding at least one planned line; with `position`
    (1: the start), that part is at that position; with `parts`, the session has exactly that
    many parts of the kind."""
    rows = conn.execute(
        "select sp.id, sp.position, count(l.id) from session_part sp"
        " join planned_session s on s.id = sp.session_id"
        " join training_week w on w.id = s.week_id"
        " left join session_exercise l on l.part_id = sp.id and l.origin = 'planned'"
        " where w.number = %s and s.title = %s and sp.kind = %s group by sp.id",
        (p["week"], p["title"], p["kind"]),
    ).fetchall()
    filled = [position for _, position, n in rows if n > 0]
    ok = bool(filled) and ("position" not in p or p["position"] in filled)
    ok = ok and ("parts" not in p or len(rows) == p["parts"])
    where = f" at position {', '.join(map(str, filled))}" if filled else ""
    return ok, f"{len(rows)} {p['kind']} part(s), {len(filled)} with a planned line{where}"


def called_tool(conn, p) -> tuple[bool, str]:
    """The coach called that tool at least once during the conversation."""
    (n,) = conn.execute(
        "select count(*) from agent_run r, jsonb_array_elements(r.context -> 'calls') c"
        " where r.agent = 'coach' and c ->> 'tool' = %s",
        (p["tool"],),
    ).fetchone()
    return n > 0, f"{p['tool']} called {n} time(s)"


def record(conn, p) -> tuple[bool, str]:
    """A record entry of that value and reps, on a record tied to that exercise."""
    rows = conn.execute(
        "select e.value, e.reps from record_entry e"
        " join record_definition d on d.id = e.definition_id"
        " join exercise x on x.id = d.exercise_id where x.name = %s",
        (p["exercise"],),
    ).fetchall()
    ok = any(float(v or 0) == p["value"] and r == p["reps"] for v, r in rows)
    found = ", ".join(f"{v} kg x {r}" for v, r in rows) or "none"
    return ok, f"records of {p['exercise']}: {found}"


def goals(conn, p) -> tuple[bool, str]:
    (n,) = conn.execute("select count(*) from goal").fetchone()
    return n == p["count"], f"{n} goal(s)"


def no_forbidden_suggestion(conn, p) -> tuple[bool, str]:
    """No pending suggestion names an exercise that a forbid_flag rule excludes."""
    forbidden = {f["exercise"] for f in forbidden_exercises(conn)}
    payloads = [
        json.dumps(r[0], ensure_ascii=False)
        for r in conn.execute("select payload from proposal where status = 'pending'")
    ]
    hits = sorted({name for name in forbidden for text in payloads if f'"{name}"' in text})
    return not hits, f"forbidden in suggestions: {', '.join(hits) or 'none'}"


def week_intent(conn, p) -> tuple[bool, str]:
    """The week's intent holds each word of `contains` (any case) under `key`, or under any
    key without one: a programme writes its intent per part kind or as one note, and the
    coach follows the shape it finds."""
    row = conn.execute(
        "select intent from training_week where number = %s", (p["week"],)
    ).fetchone()
    intent = (row[0] or {}) if row else {}
    texts = [intent.get(p["key"])] if "key" in p else list(intent.values())
    ok = any(
        isinstance(t, str) and all(w.lower() in t.lower() for w in p["contains"]) for t in texts
    )
    return ok, f"week {p['week']} intent: {intent!r}"


def planned_line(conn, p) -> tuple[bool, str]:
    n = _lines(conn, p["week"], p["title"], "planned", p["exercise"])
    return n > 0, f"{n} planned line(s) of {p['exercise']}"


def reply_mentions(conn, p) -> tuple[bool, str]:
    """The coach's last reply holds one of `any` (any case): a rule it must name, say."""
    row = conn.execute(
        "select text from conversation_message where role = 'coach' order by id desc limit 1"
    ).fetchone()
    text = row[0] if row else ""
    found = [w for w in p["any"] if w.lower() in text.lower()]
    return bool(found), f"mentions: {', '.join(found) or 'none of ' + ', '.join(p['any'])}"


CHECKS: dict[str, Callable[[psycopg.Connection, dict], tuple[bool, str]]] = {
    "session_day": session_day,
    "unchanged": unchanged,
    "changed": changed,
    "health_issue": health_issue,
    "done_line": done_line,
    "goals": goals,
    "called_tool": called_tool,
    "record": record,
    "planned_line_in_part": planned_line_in_part,
    "no_forbidden_suggestion": no_forbidden_suggestion,
    "week_intent": week_intent,
    "planned_line": planned_line,
    "reply_mentions": reply_mentions,
}


# Runner


@dataclass
class Outcome:
    check: str
    passed: bool
    detail: str


@dataclass
class ConversationResult:
    scenario: str
    category: str
    run: int
    expectations_met: int
    expectations: int
    outcomes: list[Outcome]
    model_calls: int
    input_tokens: int
    output_tokens: int
    refused_quotes: int  # writes the code refused because the quote was not the athlete's
    stopped: int  # turns stopped by the step limit or the token budget
    replies: list[str] = field(default_factory=list)


class SilentCoach:
    """The floor: a coach that answers and never calls a tool."""

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return AIMessage("Noted.")


def setup(conn: psycopg.Connection, conversation: Conversation) -> None:
    reset(conn)
    load_program(conn, base_program())
    for note in conversation.notes:
        found = _session(conn, note.week, note.title)
        if found is None:
            raise ValueError(f"no session '{note.title}' in week {note.week}")
        conn.execute("update planned_session set notes = %s where id = %s", (note.text, found[0]))


def run_conversation(
    conn: psycopg.Connection,
    conversation: Conversation,
    make_model: Callable[[], Any],
    runs: int,
    *,
    model_name: str | None = None,
    language: str = "English",
    run_token_budget: int | None = None,
) -> list[ConversationResult]:
    results = []
    for run in range(1, runs + 1):
        setup(conn, conversation)
        model = make_model()
        calls = tokens_in = tokens_out = stopped = 0
        replies = []
        for message in conversation.messages:
            text, conversation_id = (
                (message, CONVERSATION)
                if isinstance(message, str)
                else (message.text, message.conversation)
            )
            # idempotent: the first message of each conversation creates it (migration 015)
            start(conn, id=conversation_id, title=text, source="bench")
            message_id = conn.execute(
                "insert into conversation_message (conversation_id, role, text)"
                " values (%s, 'athlete', %s) returning id",
                (conversation_id, text),
            ).fetchone()[0]
            reply = respond(
                conn,
                model,
                conversation_id=conversation_id,
                message_id=message_id,
                model_name=model_name,
                language=language,
                today=conversation.today,
                trigger="bench",
                token_budget=run_token_budget,
            )
            calls += reply.usage.calls
            tokens_in += reply.usage.input_tokens
            tokens_out += reply.usage.output_tokens
            stopped += reply.stopped is not None
            replies.append(reply.text)
        (refused,) = conn.execute(
            "select count(*) from agent_run r, jsonb_array_elements(r.context -> 'calls') c"
            " where r.agent = 'coach' and c ->> 'result' like '%%quote refused%%'"
        ).fetchone()
        outcomes = []
        for expectation in conversation.expect:
            passed, detail = CHECKS[expectation.check](conn, expectation.params)
            outcomes.append(Outcome(_label(expectation), passed, detail))
        results.append(
            ConversationResult(
                scenario=conversation.name,
                category=conversation.category,
                run=run,
                expectations_met=sum(o.passed for o in outcomes),
                expectations=len(outcomes),
                outcomes=outcomes,
                model_calls=calls,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                refused_quotes=refused,
                stopped=stopped,
                replies=replies,
            )
        )
    return results


def _label(expectation: Check) -> str:
    values = " ".join(str(v) for v in expectation.params.values())
    return f"{expectation.check} {values}".strip()


def summary(results: list[ConversationResult]) -> dict:
    expectations = sum(r.expectations for r in results)
    return {
        "runs": len(results),
        "expectations_met_rate": round(sum(r.expectations_met for r in results) / expectations, 3)
        if expectations
        else 0.0,
        "scenarios_fully_met": sum(r.expectations_met == r.expectations for r in results),
        "refused_quotes": sum(r.refused_quotes for r in results),
        "stopped": sum(r.stopped for r in results),
        "model_calls": sum(r.model_calls for r in results),
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
    }


def as_dict(result: ConversationResult) -> dict:
    return asdict(result)
