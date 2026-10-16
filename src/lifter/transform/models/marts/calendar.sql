-- Everything on the athlete's calendar, one row per item: Lifter sessions, workouts that only
-- exist in Garmin's calendar, and activities that belong to no session.
select
    s.day, 'session' as kind, 'lifter' as source, s.title, s.kind as detail, s.status,
    s.planned_session_id, null::bigint as activity_id
from {{ ref('planned_session_status') }} s
union all
select
    g.day, 'session', 'garmin', g.name, g.sport,
    case when g.completed then 'done' when g.day < current_date then 'missed' else 'planned' end,
    null, null
from {{ ref('stg_scheduled_workout') }} g
union all
select
    a.activity_date, 'activity', 'garmin', a.name, a.activity_type,
    case when {{ target.schema }}.is_session_activity(a.activity_type) then 'done (unplanned)' else 'other' end,
    null, a.activity_id
from {{ ref('stg_activity') }} a
where not exists (select 1 from {{ ref('session_activity') }} sa where sa.activity_id = a.activity_id)
