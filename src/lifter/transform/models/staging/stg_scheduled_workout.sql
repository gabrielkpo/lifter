-- Garmin calendar snapshot (latest sync only).
select
    (item ->> 'date')::date as day,
    (item ->> 'scheduled_workout_id')::bigint as garmin_schedule_id,
    (item ->> 'workout_id')::bigint as garmin_workout_id,
    item ->> 'name' as name,
    lower(item ->> 'sport') as sport,
    (item ->> 'completed')::boolean as completed
from {{ ref('latest_garmin_payload') }},
    jsonb_array_elements(payload -> 'scheduled_workouts') as item
where tool = 'get_scheduled_workouts'
    and jsonb_typeof(payload -> 'scheduled_workouts') = 'array'
