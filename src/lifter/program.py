"""Load a training program from a YAML file: the cycle, its blocks and weeks, the sessions
(planned and logged), the exercise bank, goals and rules.

Until the app exists, the program file is how the athlete's training gets into Lifter. The
repository ships a synthetic example (`examples/program.yaml`); a real program stays in
`data/`, which Git ignores.

Loading is all or nothing. Without `replace`, it refuses a database that already holds a
program; with `replace`, what the previous program file created is deleted first: its cycle,
weeks, sessions, goals and the rules (the exercise bank is updated in place). Sessions and
goals added by the athlete or by approved proposals are kept, without their week; feedback on a
deleted session loses its link to it.
"""

from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
import yaml
from pydantic import Field, model_validator

from lifter.domain import (
    DomainError,
    ExerciseIn,
    GoalIn,
    RuleIn,
    SessionIn,
    StrictModel,
    WeekIntent,
    add_rule,
    create_goal,
    create_session,
    insert_row,
    upsert_exercise,
)

Phase = Literal[
    "reset",
    "reference",
    "volume",
    "volume_peak",
    "deload",
    "strength",
    "intensification",
    "strength_peak",
    "power",
    "density",
    "peak",
    "test",
]


class WeekSessionIn(SessionIn):
    """A session inside a week: the week is given by its place in the file."""

    week_id: None = None


class BlockIn(StrictModel):
    position: int = Field(ge=1)
    kind: Literal["accumulation", "transmutation", "realisation"]
    start_date: date
    end_date: date
    intent: str | None = None
    target_strength_sessions: int | None = Field(default=None, gt=0)


class WeekIn(StrictModel):
    number: int = Field(ge=0)
    block: int | None = None
    start_date: date
    phase: Phase
    title: str | None = None
    intent: WeekIntent = {}
    review: str | None = None
    sessions: list[WeekSessionIn] = []


class ProgramIn(StrictModel):
    name: str = Field(min_length=1)
    start_date: date
    end_date: date
    notes: str | None = None
    exercises: list[ExerciseIn] = []
    blocks: list[BlockIn] = []
    weeks: list[WeekIn] = []
    history: list[WeekSessionIn] = []
    goals: list[GoalIn] = []
    rules: list[RuleIn] = []

    @model_validator(mode="after")
    def _consistent(self):
        if self.end_date < self.start_date:
            raise ValueError("the cycle cannot end before it starts")
        positions = [b.position for b in self.blocks]
        if len(set(positions)) != len(positions):
            raise ValueError("block positions must be unique")
        numbers = [w.number for w in self.weeks]
        if len(set(numbers)) != len(numbers):
            raise ValueError("week numbers must be unique")
        unknown_blocks = {w.block for w in self.weeks if w.block is not None} - set(positions)
        if unknown_blocks:
            raise ValueError(f"weeks refer to unknown blocks: {sorted(unknown_blocks)}")
        bank = {e.name for e in self.exercises}
        if len(bank) != len(self.exercises):
            raise ValueError("exercise names must be unique")
        used = {
            line.exercise
            for session in self.sessions()
            for part in session.parts
            for line in part.planned + part.done
        } | {g.exercise for g in self.goals if g.exercise is not None}
        missing = sorted(used - bank)
        if missing:
            raise ValueError(f"exercises missing from the bank: {', '.join(missing)}")
        return self

    def sessions(self) -> list[WeekSessionIn]:
        return [s for w in self.weeks for s in w.sessions] + list(self.history)


def read_program(path: Path) -> ProgramIn:
    """Parse and validate a program file (YAML, safe loader only)."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ProgramIn.model_validate(data)


def what_replace_deletes(conn: psycopg.Connection, program: ProgramIn) -> dict[str, int]:
    """What `replace` would delete or detach that the new program file does not write back:
    the rules it does not hold as they are now (added, changed or switched off since), the
    athlete's feedback on the program's sessions, and the coach's traced changes since the
    current program was loaded, whose undo would then be refused."""
    kept = [(r.code, r.text, r.params, True) for r in program.rules]
    rules = sum(
        1
        for row in conn.execute("select code, text, params, active from athlete_rule").fetchall()
        if tuple(row) not in kept
    )
    (feedback,) = conn.execute(
        "select count(*) from feedback f join planned_session s on s.id = f.planned_session_id"
        " where s.source = 'program'"
    ).fetchone()
    (changes,) = conn.execute(
        "select count(*) from change_log"
        " where created_at > (select coalesce(max(created_at), '-infinity') from cycle)"
    ).fetchone()
    lost = {
        "rules not in the file as they are now": rules,
        "feedback on the program's sessions": feedback,
        "changes made through the coach since the program was loaded": changes,
    }
    return {name: n for name, n in lost.items() if n}


def load_program(
    conn: psycopg.Connection, program: ProgramIn, *, replace: bool = False, force: bool = False
) -> dict[str, int]:
    """Write the program to the database in one transaction; returns what was created.
    `replace` refuses, unless `force`, when it would delete what was written since the file
    (feedback, rules, the coach's traced changes, logs included, whose undo would then be
    refused)."""
    with conn.transaction():
        existing = conn.execute("select count(*) from cycle").fetchone()[0]
        if existing and not replace:
            raise DomainError("a program is already loaded; load with replace to overwrite it")
        if replace and existing and not force:
            lost = what_replace_deletes(conn, program)
            if lost:
                listed = ", ".join(f"{n} {name}" for name, n in lost.items())
                raise DomainError(
                    f"replace would delete what was written since the program file: {listed}."
                    " Take a backup first, then load with --force to go ahead"
                )
        if replace:
            # Parts, lines, weeks and milestones follow by cascade; sessions of other sources
            # stay in the calendar and lose their week.
            conn.execute("delete from planned_session where source = 'program'")
            conn.execute("delete from goal where source = 'program'")
            conn.execute("delete from athlete_rule")
            conn.execute("delete from cycle")
        for exercise in program.exercises:
            upsert_exercise(conn, exercise)
        cycle_id = insert_row(
            conn,
            "cycle",
            {
                "name": program.name,
                "start_date": program.start_date,
                "end_date": program.end_date,
                "notes": program.notes,
            },
        )
        block_ids = {
            block.position: insert_row(conn, "block", {"cycle_id": cycle_id} | block.model_dump())
            for block in program.blocks
        }
        sessions = 0
        for week in program.weeks:
            week_id = insert_row(
                conn,
                "training_week",
                {
                    "cycle_id": cycle_id,
                    "block_id": block_ids.get(week.block),
                    "number": week.number,
                    "start_date": week.start_date,
                    "phase": week.phase,
                    "title": week.title,
                    "intent": week.intent,
                    "review": week.review,
                },
            )
            for session in week.sessions:
                create_session(
                    conn, SessionIn(**session.model_dump() | {"week_id": week_id}), "program"
                )
                sessions += 1
        for session in program.history:
            create_session(conn, SessionIn(**session.model_dump()), "program")
            sessions += 1
        for goal in program.goals:
            create_goal(conn, goal.model_copy(update={"cycle_id": cycle_id}), "program")
        for rule in program.rules:
            add_rule(conn, rule)
    return {
        "exercises": len(program.exercises),
        "blocks": len(program.blocks),
        "weeks": len(program.weeks),
        "sessions": sessions,
        "goals": len(program.goals),
        "rules": len(program.rules),
    }
