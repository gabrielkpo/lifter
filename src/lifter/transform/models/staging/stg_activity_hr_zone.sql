select
    natural_key::bigint as activity_id,
    (zone ->> 'zoneNumber')::int as zone_number,
    (zone ->> 'secsInZone')::numeric as seconds_in_zone,
    (zone ->> 'zoneLowBoundary')::int as zone_low_bpm
from {{ ref('latest_garmin_payload') }},
    jsonb_array_elements(payload) as zone
where tool = 'get_activity_hr_in_timezones'
    and jsonb_typeof(payload) = 'array'
