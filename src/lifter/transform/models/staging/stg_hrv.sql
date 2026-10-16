select
    natural_key::date as day,
    (payload ->> 'last_night_avg_hrv_ms')::numeric as hrv_ms,
    payload ->> 'status' as garmin_hrv_status
from {{ ref('latest_garmin_payload') }}
where tool = 'get_hrv_data'
