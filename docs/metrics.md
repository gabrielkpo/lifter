# Metric definitions

These are the only numbers the agents are allowed to cite: an agent reads them, it never
recomputes them. They live in SQL views of the `analytics` schema (`src/lifter/sql/views.sql`, recreated by
`lifter migrate` whenever the file changes); this page and the SQL change together, and `tests/test_metrics.py` pins each definition with hand-computed cases.

Thresholds are **version 1**: reasonable starting points for one athlete, to be tuned with the
evaluation bench. They are training heuristics, **not medical criteria**.

## Data flow

```
Garmin MCP ──► raw_garmin_payload (JSON as received, deduplicated by hash)
                  │
                  ▼
     stg_activity, stg_activity_hr_zone, stg_sleep, stg_hrv,
     stg_daily_stats, stg_training_readiness, stg_training_status   (typed, latest payload per key)
                  │
                  ▼
     activity_tombstone (activities Garmin confirms deleted) filters stg_activity
                  │
     daily_load ─► daily_base (one row per calendar day) ─► daily_metrics ─► daily_alerts
     stg_activity + stg_activity_hr_zone ─► weekly_training
     daily_base + sleep, daily stats, readiness, training status ─► daily_recovery
```

| Source tool | Natural key | Used for |
|---|---|---|
| `get_activity` | activity id | training load, duration, type |
| `get_activity_hr_in_timezones` | activity id | minutes per heart rate zone |
| `get_sleep_summary` | day (wake-up day) | sleep duration, score, phases, awakenings, resting heart rate |
| `get_hrv_data` | day | last night average HRV |
| `get_stats` | day | Body Battery, stress, Garmin resting heart rate, SpO2, respiration, intensity minutes, steps |
| `get_training_readiness` | day | training readiness score and level (morning snapshot) |
| `get_training_status` | day | Garmin training status, Garmin acute and chronic load, VO2max |
| `get_activities_by_date` | range and page | list of activity ids to fetch; activities missing details; deleted activities |

Garmin files a night under the day you wake up, so "sleep of day D" is the night before D.

A day for which Garmin answered "no data" is asked again until that answer comes more than 3
days after the day (a watch offline for a few days uploads them later); then it is final, and
only `lifter sync --refresh` asks again. An activity answered "no data" is final at once.
`get_training_status` costs two Garmin requests per day (the server also reads the device list).

When a complete listing of a date range no longer returns a known activity, the sync asks
Garmin for it (`get_activity`). Only a confirmed "not found" (HTTP 404) records it in
`activity_tombstone`, and every view then ignores it (deleted or merged in Garmin Connect).
An activity found again, or listed again later, is restored. An incomplete listing, a paging
shift or a date boundary never tombstones anything.

## Rules shared by all metrics

- **Calendar**: one row per day from the first to the last day with any data. A day without
  activity has load 0; a day without a measure has `NULL` for that measure.
- **Full windows only**: a rolling value is `NULL` until its window is full (7 days for acute
  load, 28 for chronic load and ACWR, 14 measured nights for baselines). A partial window
  would underestimate the load.
- **Rounded, then compared**: statuses, trends and alerts are computed on the rounded values
  that are displayed, so a cited number always agrees with its status.

## Load

| Column | Definition |
|---|---|
| `load` | Sum of Garmin `training_load` of the activities that start that day (local time). An activity without a load counts as 0 (`daily_load.sessions_without_load` counts them). |
| `sessions_missing_details` | Activities listed by Garmin that day whose details could not be fetched: their load is **unknown**, not zero. A non-zero value means the day's load is underestimated. |
| `acute_load_7d` | Sum of `load` over the day and the 6 days before. Rounded to 0.1. |
| `chronic_load_28d` | Sum of `load` over the day and the 27 days before, divided by 4: a weekly average over 4 weeks, comparable to the acute load. Rounded to 0.1. |
| `acwr` | Acute to chronic workload ratio: `acute_load_7d / chronic_load_28d` (unrounded values), rounded to 0.01. `NULL` with less than 28 days of history or a chronic load of 0. |

These are Lifter's own definitions (simple rolling sums), not Garmin's acute and chronic load,
which use exponentially weighted averages.

## Recovery

| Column | Definition |
|---|---|
| `hrv_baseline_28d` | Mean of the nightly HRV over the 28 previous days, **today excluded**. Needs at least 14 measured nights. |
| `hrv_delta_pct` | `100 × (hrv_ms − baseline) / baseline`, rounded to 0.1. `NULL` if the baseline is 0. |
| `hrv_7d_delta_pct` | Same, with the 7-day mean HRV (today included) instead of today's value. |
| `rhr_baseline_28d` | Mean resting heart rate over the 28 previous days, today excluded, at least 14 days. |
| `rhr_delta_bpm` | `resting_hr_bpm − baseline`, rounded to 0.1. |
| `sleep_hours` | Sleep duration of the night, rounded to 0.01. |

`recovery_score` (0 to 100) is the mean of the available components, each clamped to 0–100:

| Component | Formula | Reads as |
|---|---|---|
| HRV (required) | `50 + 2.5 × hrv_delta_pct` | −20 % → 0, baseline → 50, +20 % → 100 |
| Resting HR | `50 − 10 × rhr_delta_bpm` | +5 bpm → 0, baseline → 50, −5 bpm → 100 |
| Sleep | `100 × (sleep_hours − 5) / 3` | 5 h → 0, 8 h → 100 |

Without HRV there is no score. The score is rounded to an integer.

| `recovery_status` | Rule |
|---|---|
| `low` | score < 40 |
| `normal` | 40 ≤ score < 70 |
| `good` | score ≥ 70 |
| `unknown` | no score |

## Trend

`recovery_7d_avg` is the mean recovery score over the day and the 6 days before, when at least
4 of them have a score. `trend` is evaluated in this order:

| `trend` | Rule |
|---|---|
| `unknown` | no `recovery_7d_avg` or no `acwr` |
| `fatigue` | `recovery_7d_avg < 45`, or `acwr > 1.3` with `hrv_7d_delta_pct ≤ −5` |
| `improving` | chronic load up at least 5 % on 14 days earlier, with `recovery_7d_avg ≥ 55` |
| `stable` | otherwise |

## Alerts (`daily_alerts`)

One row per triggered alert, with the value and the threshold that triggered it.

| Alert | Severity | Rule |
|---|---|---|
| `load_spike` | warning | `acwr > 1.5` |
| `load_drop` | info | `acwr < 0.8` |
| `hrv_drop` | warning | `hrv_delta_pct ≤ −15` |
| `rhr_elevated` | warning | `rhr_delta_bpm ≥ 5` |
| `short_sleep` | info | `sleep_hours < 6` |
| `abnormal_hrv` | critical | `hrv_delta_pct ≤ −30` |
| `abnormal_rhr` | critical | `rhr_delta_bpm ≥ 10` |

A `critical` alert is a signal outside the usual range. The guardrail (next step) will then
block any intense plan and advise seeing a health professional; Lifter gives no diagnosis.

## Weekly training (`weekly_training`)

Per ISO week (Monday start) and activity type: sessions, duration in minutes, total load, and
minutes in each heart rate zone (Garmin zones 1 to 5, from `get_activity_hr_in_timezones`).

## Recovery and form (`daily_recovery`)

Garmin's own values, one row per calendar day, next to the sleep details. Lifter stores and
shows them as Garmin computes them (rounded for display only); they are **not** Lifter's
definitions, and an agent citing one names it as Garmin's (for example "Garmin training
readiness 74"). Lifter's own load and recovery stay in `daily_metrics`.

| Column | Source and meaning |
|---|---|
| `sleep_hours`, `sleep_score` | Sleep of the night before the day (`get_sleep_summary`) |
| `deep_sleep_minutes`, `rem_sleep_minutes`, `awake_minutes`, `awake_count`, `avg_sleep_stress` | Sleep phases and awakenings of that night |
| `body_battery_highest`, `body_battery_lowest`, `body_battery_charged`, `body_battery_drained` | Garmin Body Battery of the day (0 to 100) |
| `avg_stress`, `stress_qualifier` | Garmin all-day stress (0 to 100) and its label |
| `garmin_resting_hr_bpm` | Garmin's resting heart rate for the day (Lifter's baseline uses the sleep value) |
| `avg_spo2_percent`, `avg_waking_respiration` | Blood oxygen and waking respiration rate, when the watch measures them |
| `intensity_minutes` | Moderate minutes + 2 × vigorous minutes, Garmin's convention |
| `readiness_score`, `readiness_level`, `recovery_time_hours` | Garmin training readiness: the **earliest snapshot of the day** (after waking up), the one that matters to plan the day |
| `garmin_training_status`, `garmin_acute_load`, `garmin_chronic_load`, `garmin_load_ratio` | Garmin's training status and its own acute and chronic load (exponentially weighted), to compare with Lifter's rolling sums |
| `vo2_max` | Garmin's running VO2max estimate (precise value) |

`lifter recovery --days 14` prints the main columns.
