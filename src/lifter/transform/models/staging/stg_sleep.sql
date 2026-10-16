-- Garmin files a night under the day you wake up.
select
    natural_key::date as day,
    (payload ->> 'sleep_seconds')::numeric as sleep_seconds,
    (payload ->> 'sleep_score')::numeric as sleep_score,
    (payload ->> 'resting_heart_rate_bpm')::numeric as resting_hr_bpm,
    (payload ->> 'deep_sleep_seconds')::numeric as deep_sleep_seconds,
    (payload ->> 'light_sleep_seconds')::numeric as light_sleep_seconds,
    (payload ->> 'rem_sleep_seconds')::numeric as rem_sleep_seconds,
    (payload ->> 'awake_seconds')::numeric as awake_seconds,
    (payload ->> 'awake_count')::numeric as awake_count,
    (payload ->> 'avg_sleep_stress')::numeric as avg_sleep_stress,
    (payload ->> 'avg_overnight_hrv')::numeric as avg_overnight_hrv_ms,
    (payload ->> 'avg_spo2_percent')::numeric as sleep_avg_spo2_percent
from {{ ref('latest_garmin_payload') }}
where tool = 'get_sleep_summary'
