// Response shapes of the Lifter API (src/lifter/api/models.py). Keep both in step.

export type SessionStatus = "done" | "missed" | "planned" | "cancelled" | "rest";

export interface Block {
  id: number;
  position: number;
  kind: string;
  start_date: string;
  end_date: string;
  intent: string | null;
  target_strength_sessions: number | null;
  strength_sessions_done: number;
}

export interface Cycle {
  id: number;
  name: string;
  start_date: string;
  end_date: string;
  status: string;
  notes: string | null;
  blocks: Block[];
}

export interface Program {
  cycles: Cycle[];
}

export interface Week {
  id: number;
  cycle_id: number;
  block_id: number | null;
  block: string | null;
  number: number;
  start_date: string;
  phase: string;
  title: string | null;
  intent: Record<string, string>;
  review: string | null;
  sessions: number;
  done: number;
  missed: number;
  cancelled: number;
  strength_sessions_done: number;
  patterns_done: string[];
}

export interface GarminLine {
  activities: number;
  duration_minutes: number | null;
  avg_hr_bpm: number | null;
  max_hr_bpm: number | null;
  calories: number | null;
  training_load: number | null;
  z4_z5_minutes: number | null;
}

export interface SessionSummary {
  id: number;
  day: string;
  title: string;
  kind: string;
  status: SessionStatus;
  moved_from: string | null;
  logged: boolean;
  garmin: GarminLine | null;
}

export interface WeekDetail {
  week: Week;
  block_intent: string | null;
  sessions: SessionSummary[];
}

export interface CalendarItem {
  day: string;
  kind: "session" | "activity";
  source: "lifter" | "garmin";
  title: string | null;
  detail: string | null;
  status: string;
  session_id: number | null;
  activity_id: number | null;
}

export interface Line {
  position: number;
  exercise: string;
  category: string;
  pattern: string;
  sets: number | null;
  quantity: number | null;
  unit: string;
  load_kg: number | null;
  load_kg_max: number | null;
  rir: number | null;
  rest_seconds: number | null;
  notes: string | null;
}

export interface Part {
  position: number;
  kind: string;
  title: string | null;
  notes: string | null;
  format: string | null;
  duration_minutes: number | null;
  rounds: number | null;
  interval_seconds: number | null;
  target_seconds: number | null;
  target_rounds: number | null;
  result_seconds: number | null;
  result_rounds: number | null;
  result_notes: string | null;
  planned: Line[];
  done: Line[];
}

export interface SessionDetail {
  id: number;
  day: string;
  title: string;
  kind: string;
  status: SessionStatus;
  week_id: number | null;
  moved_from: string | null;
  notes: string | null;
  deviation: string | null;
  garmin: GarminLine | null;
  parts: Part[];
}

export interface DailyMetrics {
  day: string;
  load: number;
  acute_load_7d: number | null;
  chronic_load_28d: number | null;
  acwr: number | null;
  hrv_ms: number | null;
  hrv_baseline_28d: number | null;
  hrv_delta_pct: number | null;
  resting_hr_bpm: number | null;
  rhr_baseline_28d: number | null;
  rhr_delta_bpm: number | null;
  sleep_hours: number | null;
  sleep_score: number | null;
  recovery_score: number | null;
  recovery_status: "unknown" | "low" | "normal" | "good";
  recovery_7d_avg: number | null;
  trend: "unknown" | "fatigue" | "improving" | "stable";
}

export interface DailyRecovery {
  day: string;
  sleep_hours: number | null;
  sleep_score: number | null;
  deep_sleep_minutes: number | null;
  rem_sleep_minutes: number | null;
  awake_minutes: number | null;
  body_battery_highest: number | null;
  body_battery_lowest: number | null;
  avg_stress: number | null;
  stress_qualifier: string | null;
  garmin_resting_hr_bpm: number | null;
  avg_spo2_percent: number | null;
  readiness_score: number | null;
  readiness_level: string | null;
  recovery_time_hours: number | null;
  garmin_training_status: string | null;
  garmin_acute_load: number | null;
  garmin_chronic_load: number | null;
  vo2_max: number | null;
}

export interface Alert {
  day: string;
  alert: string;
  severity: "info" | "warning" | "critical";
  value: number | null;
  threshold: number;
}

export interface Health {
  metrics: DailyMetrics[];
  recovery: DailyRecovery[];
  alerts: Alert[];
}

export interface Milestone {
  day: string;
  label: string | null;
  value: number | null;
  value_text: string | null;
}

export interface Goal {
  id: number;
  title: string;
  kind: string;
  exercise: string | null;
  unit: string | null;
  baseline_value: number | null;
  baseline_text: string | null;
  baseline_date: string | null;
  target_value: number | null;
  target_text: string | null;
  target_date: string | null;
  status: string;
  notes: string | null;
  milestones: Milestone[];
}

export interface Best {
  exercise: string;
  category: string;
  pattern: string;
  reps: number;
  best_load_kg: number;
  day: string;
}

export interface WeekExercise {
  week_id: number;
  week_number: number;
  phase: string;
  exercise: string;
  category: string;
  pattern: string;
  origin: "planned" | "done";
  sets: number;
  reps: number | null;
  top_load_kg: number | null;
  avg_rir: number | null;
}

export interface BlockDetail {
  block: Block;
  weeks: Week[];
  progress: WeekExercise[];
}

export interface HistoryPoint {
  exercise: string;
  day: string;
  session_id: number;
  top_load_kg: number;
  reps: number | null;
  sets: number | null;
}

export interface Athlete {
  first_name: string | null;
  age: number | null;
  sex: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  weight_date: string | null;
  handedness: string | null;
  level: string | null;
  practice_since: string | null;
  sessions_per_week: number | null;
  training_places: string[];
  context: string | null;
}

export interface HealthIssue {
  id: number;
  body_part: string;
  side: string | null;
  kind: string;
  description: string;
  guidance: string | null;
  since: string | null;
  status: "active" | "monitoring" | "resolved";
  resolved_on: string | null;
  source: string;
  reported_quote: string | null;
}

export interface Profile {
  athlete: Athlete | null;
  health_issues: HealthIssue[];
  rules: { code: string | null; text: string }[];
}

/** The conversation with the coach (GET and POST /conversation). */
export interface ConversationChange {
  change_id: number;
  operation: string;
  entity: string;
  entity_id: number | null;
  undone: boolean;
}

export interface ConversationSuggestion {
  id: number;
  operation: string;
  rationale: string;
  status: string;
}

export interface ConversationMessage {
  id: number;
  role: "athlete" | "coach";
  text: string;
  created_at: string;
  /** On an athlete's message: the changes it authorised. */
  changes: ConversationChange[];
  /** On a coach's reply: the suggestions it presented. */
  suggestions: ConversationSuggestion[];
}

export interface ConversationReply {
  athlete: ConversationMessage;
  coach: ConversationMessage;
  stopped: string | null;
  run_id: number | null;
}

