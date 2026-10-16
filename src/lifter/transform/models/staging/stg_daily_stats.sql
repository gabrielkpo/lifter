-- Garmin's own daily values (get_stats): Body Battery, stress, resting HR, SpO2, respiration.
select
    natural_key::date as day,
    (payload ->> 'total_steps')::numeric as steps,
    (payload ->> 'active_calories')::numeric as active_calories,
    (payload ->> 'moderate_intensity_minutes')::numeric as moderate_intensity_minutes,
    (payload ->> 'vigorous_intensity_minutes')::numeric as vigorous_intensity_minutes,
    (payload ->> 'resting_heart_rate_bpm')::numeric as garmin_resting_hr_bpm,
    (payload ->> 'avg_stress_level')::numeric as avg_stress,
    (payload ->> 'max_stress_level')::numeric as max_stress,
    payload ->> 'stress_qualifier' as stress_qualifier,
    (payload ->> 'body_battery_charged')::numeric as body_battery_charged,
    (payload ->> 'body_battery_drained')::numeric as body_battery_drained,
    (payload ->> 'body_battery_highest')::numeric as body_battery_highest,
    (payload ->> 'body_battery_lowest')::numeric as body_battery_lowest,
    (payload ->> 'avg_spo2_percent')::numeric as avg_spo2_percent,
    (payload ->> 'lowest_spo2_percent')::numeric as lowest_spo2_percent,
    (payload ->> 'avg_waking_respiration')::numeric as avg_waking_respiration
from {{ ref('latest_garmin_payload') }}
where tool = 'get_stats'
    and jsonb_typeof(payload) = 'object'
