-- Recovery and form, one row per calendar day: Garmin's own values next to the sleep details.
-- These are Garmin's figures, stored as received and rounded only for display; Lifter's own
-- definitions stay in daily_metrics.
select
    b.day,
    round(s.sleep_seconds / 3600.0, 2) as sleep_hours,
    s.sleep_score,
    round(s.deep_sleep_seconds / 60.0) as deep_sleep_minutes,
    round(s.rem_sleep_seconds / 60.0) as rem_sleep_minutes,
    round(s.awake_seconds / 60.0) as awake_minutes,
    s.awake_count,
    s.avg_sleep_stress,
    d.body_battery_highest,
    d.body_battery_lowest,
    d.body_battery_charged,
    d.body_battery_drained,
    d.avg_stress,
    d.stress_qualifier,
    d.garmin_resting_hr_bpm,
    d.avg_spo2_percent,
    d.avg_waking_respiration,
    case when d.moderate_intensity_minutes is not null or d.vigorous_intensity_minutes is not null
        then coalesce(d.moderate_intensity_minutes, 0) + 2 * coalesce(d.vigorous_intensity_minutes, 0)
    end as intensity_minutes,
    r.score as readiness_score,
    r.level as readiness_level,
    r.recovery_time_hours,
    t.garmin_training_status,
    t.garmin_acute_load,
    t.garmin_chronic_load,
    t.garmin_load_ratio,
    t.vo2_max
from {{ ref('daily_base') }} b
left join {{ ref('stg_sleep') }} s using (day)
left join {{ ref('stg_daily_stats') }} d using (day)
left join {{ ref('stg_training_readiness') }} r using (day)
left join {{ ref('stg_training_status') }} t using (day)
