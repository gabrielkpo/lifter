-- Garmin training status: its own acute / chronic load (exponentially weighted), status, VO2max.
select
    natural_key::date as day,
    -- training_status is a numeric code; the label is the feedback phrase without its suffix
    -- (PRODUCTIVE_1 -> PRODUCTIVE, NO_STATUS_2 -> NO_STATUS).
    nullif(regexp_replace(payload ->> 'training_status_feedback', '_[0-9]+$', ''), '')
        as garmin_training_status,
    case when payload ->> 'training_status' ~ '^-?[0-9]+$'
        then (payload ->> 'training_status')::int end as garmin_training_status_code,
    payload ->> 'training_status_feedback' as garmin_training_status_feedback,
    (payload ->> 'vo2_max_precise')::numeric as vo2_max,
    (payload ->> 'cycling_vo2_max_precise')::numeric as cycling_vo2_max,
    (payload ->> 'acute_load')::numeric as garmin_acute_load,
    (payload ->> 'chronic_load')::numeric as garmin_chronic_load,
    (payload ->> 'load_ratio')::numeric as garmin_load_ratio,
    payload ->> 'acwr_status' as garmin_acwr_status
from {{ ref('latest_garmin_payload') }}
where tool = 'get_training_status'
    and jsonb_typeof(payload) = 'object'
