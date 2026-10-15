-- Staging layer: typed columns read from the latest payload of each key.
create view latest_garmin_payload as
select distinct on (tool, natural_key)
    tool, natural_key, payload, last_seen_at
from raw_garmin_payload
order by tool, natural_key, last_seen_at desc, id desc;

create view stg_activity as
select
    (payload ->> 'id')::bigint as activity_id,
    payload ->> 'name' as name,
    payload ->> 'type' as activity_type,
    (payload ->> 'start_time_local')::timestamp as start_time_local,
    (payload ->> 'start_time_local')::timestamp::date as activity_date,
    (payload ->> 'duration_seconds')::numeric as duration_seconds,
    (payload ->> 'distance_meters')::numeric as distance_meters,
    (payload ->> 'avg_hr_bpm')::numeric as avg_hr_bpm,
    (payload ->> 'training_load')::numeric as training_load,
    (payload ->> 'training_effect')::numeric as aerobic_training_effect,
    (payload ->> 'workout_rpe')::numeric as rpe
from latest_garmin_payload
where tool = 'get_activity';

create view stg_activity_hr_zone as
select
    natural_key::bigint as activity_id,
    (zone ->> 'zoneNumber')::int as zone_number,
    (zone ->> 'secsInZone')::numeric as seconds_in_zone,
    (zone ->> 'zoneLowBoundary')::int as zone_low_bpm
from latest_garmin_payload,
    jsonb_array_elements(payload) as zone
where tool = 'get_activity_hr_in_timezones'
    and jsonb_typeof(payload) = 'array';

-- Garmin files a night under the day you wake up.
create view stg_sleep as
select
    natural_key::date as day,
    (payload ->> 'sleep_seconds')::numeric as sleep_seconds,
    (payload ->> 'sleep_score')::numeric as sleep_score,
    (payload ->> 'resting_heart_rate_bpm')::numeric as resting_hr_bpm
from latest_garmin_payload
where tool = 'get_sleep_summary';

create view stg_hrv as
select
    natural_key::date as day,
    (payload ->> 'last_night_avg_hrv_ms')::numeric as hrv_ms,
    payload ->> 'status' as garmin_hrv_status
from latest_garmin_payload
where tool = 'get_hrv_data';
