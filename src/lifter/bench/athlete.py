"""The bench's synthetic athlete: a 12-week CrossFit cycle, built by code, not a real person.

Weeks 1 to 5 have their sessions planned (week 4 is a deload); weeks 6 to 12 only carry the
phase and intent of the macro. Scenarios then log, skip or change what they need. Dates sit in
the past (January to March 2026), so a session's status never depends on the day the bench runs.
"""

from datetime import date, timedelta

from lifter.domain import ExerciseIn, GoalIn, LineIn, MilestoneIn, PartIn, RuleIn
from lifter.program import BlockIn, ProgramIn, WeekIn, WeekSessionIn

CYCLE_START = date(2026, 1, 5)  # a Monday
DETAILED_WEEKS = 5

PHASES = {
    1: "reference",
    2: "volume",
    3: "volume_peak",
    4: "deload",
    5: "strength",
    6: "intensification",
    7: "strength_peak",
    8: "deload",
    9: "power",
    10: "density",
    11: "peak",
    12: "test",
}
INTENTS = {
    "reference": "Bottom of the ranges, RIR 3, every load is noted.",
    "volume": "One more set, not more load. RIR 3.",
    "volume_peak": "Highest volume of the block, RIR 2. Never to failure on the legs.",
    "deload": "Volume halved, RIR 4, frequency kept, one light metcon.",
    "strength": "Short sets, heavy loads, RIR 2, long rests.",
    "intensification": "Loads up, RIR 2, mid-cycle benchmark at the end of the week.",
    "strength_peak": "Heaviest loads of the block, RIR 1; legs capped at sets of 5.",
    "power": "Heavy and explosive, very short sets, short intense metcons.",
    "density": "Highest power clean and snatch loads, sprint metcons.",
    "peak": "Max single on the upper body, no max on the legs.",
    "test": "Test week: max bench, strict pull-ups, benchmark metcon repeated.",
}

EXERCISES = [
    ExerciseIn(name="Row", category="monostructural", pattern="engine", equipment="rower"),
    ExerciseIn(name="Ski erg", category="monostructural", pattern="engine", equipment="ski erg"),
    ExerciseIn(
        name="Assault bike", category="monostructural", pattern="engine", equipment="air bike"
    ),
    ExerciseIn(
        name="Run", category="monostructural", pattern="engine", flags=["running", "impact"]
    ),
    ExerciseIn(
        name="Power clean", category="weightlifting", pattern="olympic", equipment="barbell"
    ),
    ExerciseIn(
        name="Power snatch", category="weightlifting", pattern="olympic", equipment="barbell"
    ),
    ExerciseIn(
        name="Snatch pull", category="weightlifting", pattern="olympic", equipment="barbell"
    ),
    ExerciseIn(name="Push jerk", category="weightlifting", pattern="olympic", equipment="barbell"),
    ExerciseIn(name="Bench press", category="strength", pattern="push", equipment="barbell"),
    ExerciseIn(name="Strict press", category="strength", pattern="push", equipment="barbell"),
    ExerciseIn(name="Dips", category="gymnastics", pattern="push"),
    ExerciseIn(name="Push-up", category="gymnastics", pattern="push"),
    ExerciseIn(name="Strict pull-up", category="gymnastics", pattern="pull", equipment="rig"),
    ExerciseIn(name="Barbell row", category="strength", pattern="pull", equipment="barbell"),
    ExerciseIn(name="Leg press", category="strength", pattern="legs", equipment="machine"),
    ExerciseIn(name="Leg curl", category="strength", pattern="legs", equipment="machine"),
    ExerciseIn(name="Leg extension", category="strength", pattern="legs", equipment="machine"),
    ExerciseIn(
        name="Back squat",
        category="strength",
        pattern="legs",
        equipment="barbell",
        flags=["free_barbell_legs"],
    ),
    ExerciseIn(name="Romanian deadlift", category="strength", pattern="hinge", equipment="barbell"),
    ExerciseIn(name="Farmer carry", category="strength", pattern="carry", equipment="kettlebells"),
    ExerciseIn(name="Kettlebell swing", category="weightlifting", pattern="hinge"),
    ExerciseIn(name="Wall ball", category="weightlifting", pattern="full_body"),
    ExerciseIn(name="Burpee", category="gymnastics", pattern="full_body"),
    ExerciseIn(name="Toes to bar", category="gymnastics", pattern="core", equipment="rig"),
    ExerciseIn(name="Box jump", category="gymnastics", pattern="legs", flags=["impact"]),
    ExerciseIn(name="Hip mobility", category="mobility", pattern="mobility"),
]

RULES = [
    RuleIn(
        code="forbid_flag",
        text="No running, no repeated jumps.",
        params={"flags": ["running", "impact"]},
    ),
    RuleIn(
        code="forbid_flag",
        text="No free barbell on the legs.",
        params={"flags": ["free_barbell_legs"]},
    ),
    RuleIn(code="no_failure_on_legs", text="Never train the legs to failure, never test a max."),
    RuleIn(
        code="weekly_pattern", text="Legs every week, deload included.", params={"pattern": "legs"}
    ),
    RuleIn(code="no_max_before_test", text="No 1RM before the test week."),
    RuleIn(code="fresh_first", text="Weightlifting and skills while fresh, never after a metcon."),
    RuleIn(code="metcon_no_row", text="No rower in metcons.", params={"exercises": ["Row"]}),
    RuleIn(
        code="metcon_light_barbell",
        text="Light barbell in metcons, 40 kg at most.",
        params={"max_kg": 40},
    ),
    RuleIn(
        code="progression",
        text="RIR met on every set: +2.5 kg upper body, +5 kg lower body.",
        params={"upper_kg": 2.5, "lower_kg": 5},
    ),
    RuleIn(
        code="stop_rule",
        text="Pain above 3/10, or swelling within 24 h: two steps back on that pattern.",
        params={"pain_max": 3, "steps": 2},
    ),
    RuleIn(text="A skipped session is not made up, except legs."),
]


def week_start(number: int) -> date:
    return CYCLE_START + timedelta(weeks=number - 1)


def _round(kg: float) -> float:
    return round(kg / 2.5) * 2.5


def _line(exercise, sets=None, quantity=None, unit="reps", load=None, rir=None, rest=None):
    return LineIn(
        exercise=exercise,
        sets=sets,
        quantity=quantity,
        unit=unit,
        load_kg=load,
        rir=rir,
        rest_seconds=rest,
    )


def training_week(number: int) -> list[WeekSessionIn]:
    """A normal week: push, cardio, pull, legs, benchmark WOD; loads up one step a week."""
    step = number - 1
    monday = week_start(number)
    rir = 3 if number <= 2 else 2
    return [
        WeekSessionIn(
            day=monday,
            title="Weightlifting + Push + Metcon",
            parts=[
                PartIn(
                    kind="weightlifting",
                    planned=[_line("Power clean", 5, 3, load=40 + 2.5 * step, rir=3)],
                ),
                PartIn(
                    kind="strength",
                    planned=[
                        _line("Bench press", 4, 8, load=60 + 2.5 * step, rir=rir, rest=150),
                        _line("Strict press", 3, 8, load=35, rir=rir),
                        _line("Dips", 3, 6, rir=rir),
                    ],
                ),
                PartIn(
                    kind="metcon",
                    format="for_time",
                    rounds=3,
                    target_seconds=600,
                    planned=[
                        _line("Ski erg", quantity=15, unit="cal"),
                        _line("Wall ball", quantity=15, load=6),
                        _line("Burpee", quantity=10),
                    ],
                ),
            ],
        ),
        WeekSessionIn(
            day=monday + timedelta(days=1),
            title="Cardio",
            kind="cardio",
            parts=[PartIn(kind="cardio", planned=[_line("Row", quantity=30, unit="min")])],
        ),
        WeekSessionIn(
            day=monday + timedelta(days=3),
            title="Weightlifting + Pull + Metcon",
            parts=[
                PartIn(
                    kind="weightlifting",
                    planned=[_line("Power snatch", 5, 2, load=35 + 2.5 * step, rir=3)],
                ),
                PartIn(
                    kind="strength",
                    planned=[
                        _line("Strict pull-up", 4, 5, rir=rir),
                        _line("Barbell row", 4, 10, load=40 + 2.5 * step, rir=rir),
                        _line("Farmer carry", 4, 40, unit="m", load=24),
                    ],
                ),
                PartIn(
                    kind="metcon",
                    format="amrap",
                    duration_minutes=12,
                    target_rounds=5,
                    planned=[
                        _line("Assault bike", quantity=12, unit="cal"),
                        _line("Kettlebell swing", quantity=15, load=20),
                        _line("Toes to bar", quantity=10),
                    ],
                ),
            ],
        ),
        WeekSessionIn(
            day=monday + timedelta(days=4),
            title="Legs + Metcon",
            parts=[
                PartIn(
                    kind="strength",
                    planned=[
                        _line("Leg press", 4, 12, load=110 + 5 * step, rir=rir),
                        _line("Romanian deadlift", 3, 10, load=50 + 5 * step, rir=rir),
                        _line("Leg curl", 3, 12, rir=rir),
                    ],
                ),
                PartIn(
                    kind="metcon",
                    format="emom",
                    duration_minutes=12,
                    planned=[
                        _line("Ski erg", quantity=12, unit="cal"),
                        _line("Kettlebell swing", quantity=12, load=20),
                    ],
                ),
            ],
        ),
        WeekSessionIn(
            day=monday + timedelta(days=5),
            title="Benchmark WOD",
            parts=[
                PartIn(kind="weightlifting", planned=[_line("Snatch pull", 4, 3, load=50, rir=3)]),
                PartIn(
                    kind="metcon",
                    format="amrap",
                    duration_minutes=25,
                    target_rounds=5,
                    planned=[
                        _line("Assault bike", quantity=15, unit="cal"),
                        _line("Wall ball", quantity=15, load=6),
                        _line("Farmer carry", quantity=40, unit="m", load=24),
                        _line("Burpee", quantity=10),
                        _line("Ski erg", quantity=200, unit="m"),
                    ],
                ),
            ],
        ),
    ]


def deload_week(number: int) -> list[WeekSessionIn]:
    """Volume halved, RIR 4, frequency kept, one light metcon."""
    monday = week_start(number)
    return [
        WeekSessionIn(
            day=monday,
            title="Push (deload)",
            parts=[
                PartIn(
                    kind="strength",
                    planned=[
                        _line("Bench press", 2, 8, load=_round((60 + 2.5 * 2) * 0.8), rir=4),
                        _line("Dips", 2, 5, rir=4),
                    ],
                ),
            ],
        ),
        WeekSessionIn(
            day=monday + timedelta(days=1),
            title="Cardio",
            kind="cardio",
            parts=[
                PartIn(kind="cardio", planned=[_line("Row", quantity=20, unit="min")]),
            ],
        ),
        WeekSessionIn(
            day=monday + timedelta(days=3),
            title="Pull (deload)",
            parts=[
                PartIn(
                    kind="strength",
                    planned=[
                        _line("Strict pull-up", 2, 4, rir=4),
                        _line("Barbell row", 2, 10, load=40, rir=4),
                    ],
                ),
            ],
        ),
        WeekSessionIn(
            day=monday + timedelta(days=4),
            title="Legs + light metcon",
            parts=[
                PartIn(
                    kind="strength",
                    planned=[
                        _line("Leg press", 2, 10, load=_round((110 + 5 * 2) * 0.8), rir=4),
                        _line("Leg curl", 2, 10, rir=4),
                    ],
                ),
                PartIn(
                    kind="metcon",
                    format="amrap",
                    duration_minutes=10,
                    target_rounds=4,
                    planned=[
                        _line("Assault bike", quantity=10, unit="cal"),
                        _line("Wall ball", quantity=8, load=6),
                        _line("Push-up", quantity=6),
                    ],
                ),
            ],
        ),
    ]


def base_program() -> ProgramIn:
    blocks = [
        BlockIn(
            position=1,
            kind="accumulation",
            start_date=week_start(1),
            end_date=week_start(4) + timedelta(days=6),
            target_strength_sessions=12,
            intent="Volume: 8-12 reps, RIR 3 then 2, long metcons.",
        ),
        BlockIn(
            position=2,
            kind="transmutation",
            start_date=week_start(5),
            end_date=week_start(8) + timedelta(days=6),
            target_strength_sessions=11,
            intent="Maximal strength: volume down, short sets, long rests.",
        ),
        BlockIn(
            position=3,
            kind="realisation",
            start_date=week_start(9),
            end_date=week_start(12) + timedelta(days=6),
            target_strength_sessions=9,
            intent="Express strength, then test.",
        ),
    ]
    weeks = []
    for number in range(1, 13):
        phase = PHASES[number]
        if number > DETAILED_WEEKS:
            sessions = []
        else:
            sessions = deload_week(number) if phase == "deload" else training_week(number)
        weeks.append(
            WeekIn(
                number=number,
                block=(number - 1) // 4 + 1,
                start_date=week_start(number),
                phase=phase,
                title=phase.replace("_", " ").capitalize(),
                intent={"notes": INTENTS[phase]},
                sessions=sessions,
            )
        )
    goals = [
        GoalIn(
            title="Bench press 80 kg",
            exercise="Bench press",
            unit="kg",
            baseline_value=72.5,
            target_value=80,
            target_date=week_start(12) + timedelta(days=6),
            milestones=[MilestoneIn(day=week_start(4) + timedelta(days=6), value=75)],
        ),
        GoalIn(
            title="First strict pull-up set of 8",
            kind="skill",
            exercise="Strict pull-up",
            unit="reps",
            baseline_value=5,
            target_value=8,
            target_date=week_start(12) + timedelta(days=6),
        ),
    ]
    return ProgramIn(
        name="Synthetic bench cycle",
        start_date=week_start(1),
        end_date=week_start(12) + timedelta(days=6),
        notes="Synthetic athlete of the evaluation bench. Not a real person.",
        exercises=EXERCISES,
        blocks=blocks,
        weeks=weeks,
        goals=goals,
        rules=RULES,
    )
