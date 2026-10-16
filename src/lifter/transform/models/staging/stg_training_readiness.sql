-- Garmin training readiness: one or more snapshots a day; the earliest one is the morning
-- value (after waking up), the one that matters to plan the day.
select distinct on (day)
    day, score, level, feedback, recovery_time_hours, acute_load, hrv_weekly_avg_ms,
    snapshot_time
from (
    select
        natural_key::date as day,
        (snap ->> 'score')::numeric as score,
        snap ->> 'level' as level,
        snap ->> 'feedback' as feedback,
        (snap ->> 'recovery_time_hours')::numeric as recovery_time_hours,
        (snap ->> 'acute_load')::numeric as acute_load,
        (snap ->> 'hrv_weekly_avg')::numeric as hrv_weekly_avg_ms,
        (snap ->> 'timestamp')::timestamp as snapshot_time
    from {{ ref('latest_garmin_payload') }},
        jsonb_array_elements(payload) as snap
    where tool = 'get_training_readiness'
        and jsonb_typeof(payload) = 'array'
) snapshots
order by day, snapshot_time nulls last
