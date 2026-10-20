"""Response models of the API: one per screen of the app, read from the analytics views.

Numbers come from Postgres as Decimal; they are declared as float so the JSON carries numbers,
not strings. No value is computed here: the views hold every definition (docs/metrics.md).
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

SessionStatus = Literal["done", "missed", "planned", "cancelled", "rest"]
ProposalStatus = Literal["pending", "approved", "rejected", "applied", "failed", "expired"]


class Block(BaseModel):
    id: int
    position: int
    kind: str
    start_date: date
    end_date: date
    intent: str | None
    target_strength_sessions: int | None
    strength_sessions_done: int


class Cycle(BaseModel):
    id: int
    name: str
    start_date: date
    end_date: date
    status: str
    notes: str | None
    blocks: list[Block]


class Program(BaseModel):
    cycles: list[Cycle]


class Week(BaseModel):
    """A week's review (analytics.week_summary) with its title and intent."""

    id: int
    cycle_id: int
    block_id: int | None
    block: str | None
    number: int
    start_date: date
    phase: str
    title: str | None
    intent: dict[str, Any]
    review: str | None
    sessions: int
    done: int
    missed: int
    cancelled: int
    strength_sessions_done: int
    patterns_done: list[str]


class WeekExercise(BaseModel):
    """One exercise in one week, planned or done (analytics.week_exercise_progress)."""

    week_id: int
    week_number: int
    phase: str
    exercise: str
    category: str
    pattern: str
    origin: Literal["planned", "done"]
    sets: int
    reps: float | None
    top_load_kg: float | None
    avg_rir: float | None


class BlockDetail(BaseModel):
    """A block of the cycle: its progress, its weeks and how each exercise evolved."""

    block: Block
    weeks: list[Week]
    progress: list[WeekExercise]


class GarminLine(BaseModel):
    """A session's Garmin line (analytics.session_garmin), summed over its activities."""

    activities: int
    duration_minutes: float | None
    avg_hr_bpm: float | None
    max_hr_bpm: float | None
    calories: float | None
    training_load: float | None
    z4_z5_minutes: float | None


class SessionSummary(BaseModel):
    id: int
    day: date
    title: str
    kind: str
    status: SessionStatus
    moved_from: date | None
    logged: bool
    garmin: GarminLine | None


class WeekDetail(BaseModel):
    week: Week
    block_intent: str | None
    sessions: list[SessionSummary]


class CalendarItem(BaseModel):
    day: date
    kind: Literal["session", "activity"]
    source: Literal["lifter", "garmin"]
    title: str | None
    detail: str | None
    status: str
    session_id: int | None
    activity_id: int | None


class Line(BaseModel):
    """One exercise line, as prescribed or as done."""

    position: int
    exercise: str
    category: str
    pattern: str
    sets: int | None
    quantity: float | None
    unit: str
    load_kg: float | None
    load_kg_max: float | None
    rir: int | None
    rest_seconds: int | None
    notes: str | None


class Part(BaseModel):
    position: int
    kind: str
    title: str | None
    notes: str | None
    format: str | None
    duration_minutes: float | None
    rounds: int | None
    interval_seconds: int | None
    target_seconds: int | None
    target_rounds: float | None
    result_seconds: int | None
    result_rounds: float | None
    result_notes: str | None
    planned: list[Line]
    done: list[Line]


class SessionDetail(BaseModel):
    id: int
    day: date
    title: str
    kind: str
    status: SessionStatus
    week_id: int | None
    moved_from: date | None
    notes: str | None
    deviation: str | None
    garmin: GarminLine | None
    parts: list[Part]


class DailyMetrics(BaseModel):
    """Lifter's own daily metrics (analytics.daily_metrics)."""

    day: date
    load: float
    acute_load_7d: float | None
    chronic_load_28d: float | None
    acwr: float | None
    hrv_ms: float | None
    hrv_baseline_28d: float | None
    hrv_delta_pct: float | None
    resting_hr_bpm: float | None
    rhr_baseline_28d: float | None
    rhr_delta_bpm: float | None
    sleep_hours: float | None
    sleep_score: float | None
    recovery_score: float | None
    recovery_status: Literal["unknown", "low", "normal", "good"]
    recovery_7d_avg: float | None
    trend: Literal["unknown", "fatigue", "improving", "stable"]


class DailyRecovery(BaseModel):
    """Garmin's own recovery and form values (analytics.daily_recovery)."""

    day: date
    sleep_hours: float | None
    sleep_score: float | None
    deep_sleep_minutes: float | None
    rem_sleep_minutes: float | None
    awake_minutes: float | None
    body_battery_highest: float | None
    body_battery_lowest: float | None
    avg_stress: float | None
    stress_qualifier: str | None
    garmin_resting_hr_bpm: float | None
    avg_spo2_percent: float | None
    readiness_score: float | None
    readiness_level: str | None
    recovery_time_hours: float | None
    garmin_training_status: str | None
    garmin_acute_load: float | None
    garmin_chronic_load: float | None
    vo2_max: float | None


class Alert(BaseModel):
    day: date
    alert: str
    severity: Literal["info", "warning", "critical"]
    value: float | None
    threshold: float


class Health(BaseModel):
    """The last days of metrics, recovery and alerts, oldest first."""

    metrics: list[DailyMetrics]
    recovery: list[DailyRecovery]
    alerts: list[Alert]


class Status(BaseModel):
    """How fresh the Garmin data is: when the sync last stored or confirmed a payload."""

    garmin_last_seen_at: datetime | None


class Milestone(BaseModel):
    day: date
    label: str | None
    value: float | None
    value_text: str | None


class Goal(BaseModel):
    id: int
    title: str
    kind: str
    exercise: str | None
    unit: str | None
    baseline_value: float | None
    baseline_text: str | None
    baseline_date: date | None
    target_value: float | None
    target_text: str | None
    target_date: date | None
    status: str
    notes: str | None
    milestones: list[Milestone]


class Athlete(BaseModel):
    """The athlete as the app shows them: the age only, never the birth date (data minimisation)."""

    first_name: str | None
    age: int | None
    sex: str | None
    height_cm: float | None
    weight_kg: float | None
    weight_date: date | None
    handedness: str | None
    level: str | None
    practice_since: date | None
    sessions_per_week: int | None
    training_places: list[str]
    context: str | None


class HealthIssue(BaseModel):
    id: int
    body_part: str
    side: str | None
    kind: str
    description: str
    guidance: str | None
    since: date | None
    status: str
    resolved_on: date | None
    source: str
    reported_quote: str | None


class Rule(BaseModel):
    code: str | None
    text: str


class Profile(BaseModel):
    """Everything about the athlete: identity, declared health issues, permanent rules."""

    athlete: Athlete | None
    health_issues: list[HealthIssue]
    rules: list[Rule]


class Best(BaseModel):
    exercise: str
    category: str
    pattern: str
    reps: float
    best_load_kg: float
    day: date


class HistoryPoint(BaseModel):
    """The heaviest set of an exercise on a day, logged or declared as a record
    (analytics.exercise_history); a record has no session."""

    exercise: str
    day: date
    session_id: int | None
    top_load_kg: float
    reps: float | None
    sets: int | None


class Proposal(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    rationale: str
    author: str
    status: ProposalStatus
    result: dict[str, Any] | None
    created_at: datetime
    decided_at: datetime | None
    applied_at: datetime | None
