-- Which Garmin activities belong to which session. An activity matched explicitly
-- (planned_session.matched_activity_id) belongs to that session. Otherwise, on each day, the
-- n-th session activity (by start time) goes to the n-th open session (by id); extra
-- activities go to the day's last session, since one session is often recorded in two parts
-- (strength, then the metcon). Mobility sessions, rarely recorded, take activities only on a
-- day without another open session. An activity never belongs to two sessions; cancelled and
-- rest sessions take none.
with candidates as (
    select
        id,
        day,
        kind,
        bool_or(kind <> 'mobility') over (partition by day) as day_has_other
    from {{ source('lifter', 'planned_session') }}
    where status = 'planned' and kind <> 'rest' and matched_activity_id is null
),
open_sessions as (
    select
        id,
        day,
        row_number() over (partition by day order by id) as rank,
        count(*) over (partition by day) as sessions_that_day
    from candidates
    where kind <> 'mobility' or not day_has_other
),
free_activities as (
    select
        activity_id,
        activity_date as day,
        row_number() over (
            partition by activity_date order by start_time_local, activity_id
        ) as rank
    from {{ ref('stg_activity') }} a
    where {{ target.schema }}.is_session_activity(activity_type)
        and not exists (
            select 1 from {{ source('lifter', 'planned_session') }} p where p.matched_activity_id = a.activity_id
        )
)
select o.id as planned_session_id, f.activity_id
from free_activities f
join open_sessions o
    on o.day = f.day and o.rank = least(f.rank, o.sessions_that_day)
union all
select p.id, p.matched_activity_id
from {{ source('lifter', 'planned_session') }} p
where p.status = 'planned' and p.matched_activity_id is not null
