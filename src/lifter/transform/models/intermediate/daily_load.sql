with detailed as (
    select
        activity_date as day,
        count(*) as sessions,
        round(coalesce(sum(training_load), 0), 1) as load,
        count(*) filter (where training_load is null) as sessions_without_load,
        sum(duration_seconds) / 60.0 as duration_minutes
    from {{ ref('stg_activity') }}
    group by activity_date
),
-- Listed activities whose details are missing: their load is unknown, not zero.
missing as (
    select l.activity_date as day, count(*) as sessions_missing_details
    from {{ ref('stg_activity_listed') }} l
    left join {{ ref('stg_activity') }} a using (activity_id)
    where a.activity_id is null
    group by l.activity_date
)
select
    day,
    coalesce(d.sessions, 0) as sessions,
    coalesce(d.load, 0) as load,
    coalesce(d.sessions_without_load, 0) as sessions_without_load,
    coalesce(m.sessions_missing_details, 0) as sessions_missing_details,
    d.duration_minutes
from detailed d
full join missing m using (day)
