select
    (payload ->> 'id')::bigint as activity_id,
    payload ->> 'name' as name,
    payload ->> 'type' as activity_type,
    (payload ->> 'start_time_local')::timestamp as start_time_local,
    (payload ->> 'start_time_local')::timestamp::date as activity_date,
    (payload ->> 'duration_seconds')::numeric as duration_seconds,
    (payload ->> 'distance_meters')::numeric as distance_meters,
    (payload ->> 'avg_hr_bpm')::numeric as avg_hr_bpm,
    (payload ->> 'max_hr_bpm')::numeric as max_hr_bpm,
    (payload ->> 'calories')::numeric as calories,
    (payload ->> 'training_load')::numeric as training_load,
    (payload ->> 'training_effect')::numeric as aerobic_training_effect,
    (payload ->> 'workout_rpe')::numeric as rpe
from {{ ref('latest_garmin_payload') }}
where tool = 'get_activity'
    and not exists (
        select 1 from {{ source('lifter', 'activity_tombstone') }} t where t.activity_id = (payload ->> 'id')::bigint
    )
