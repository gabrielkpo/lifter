-- Every activity seen in a listing, even when its details could not be fetched.
select distinct on (activity_id) activity_id, activity_date
from (
    select
        (item ->> 'id')::bigint as activity_id,
        (item ->> 'start_time')::timestamp::date as activity_date,
        last_seen_at
    from {{ ref('latest_garmin_payload') }},
        jsonb_array_elements(payload -> 'activities') as item
    where tool = 'get_activities_by_date'
        and jsonb_typeof(payload -> 'activities') = 'array'
) listed
where not exists (select 1 from {{ source('lifter', 'activity_tombstone') }} t where t.activity_id = listed.activity_id)
order by activity_id, last_seen_at desc
