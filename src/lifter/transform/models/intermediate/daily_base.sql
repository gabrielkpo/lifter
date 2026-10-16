-- One row per calendar day between the first and last day with any data,
-- so rolling windows count days, not rows.
with bounds as (
    select
        least((select min(day) from {{ ref('stg_hrv') }}), (select min(day) from {{ ref('stg_sleep') }}),
              (select min(day) from {{ ref('daily_load') }}), (select min(day) from {{ ref('stg_daily_stats') }}))
            as first_day,
        greatest((select max(day) from {{ ref('stg_hrv') }}), (select max(day) from {{ ref('stg_sleep') }}),
                 (select max(day) from {{ ref('daily_load') }}), (select max(day) from {{ ref('stg_daily_stats') }}))
            as last_day
),
calendar as (
    select d::date as day
    from bounds, generate_series(first_day, last_day, interval '1 day') as d
)
select
    c.day,
    coalesce(l.sessions, 0) as sessions,
    round(coalesce(l.load, 0), 1) as load,
    coalesce(l.sessions_missing_details, 0) as sessions_missing_details,
    h.hrv_ms,
    -- Garmin's daily resting HR (get_stats); the sleep summary value is only a fallback, some
    -- watches never fill it.
    coalesce(d.garmin_resting_hr_bpm, s.resting_hr_bpm) as resting_hr_bpm,
    s.sleep_seconds,
    s.sleep_score
from calendar c
left join {{ ref('daily_load') }} l using (day)
left join {{ ref('stg_hrv') }} h using (day)
left join {{ ref('stg_sleep') }} s using (day)
left join {{ ref('stg_daily_stats') }} d using (day)
