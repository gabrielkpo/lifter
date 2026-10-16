-- Sessions per ISO week (Monday start) and activity type, with minutes per heart rate zone.
with zones as (
    select
        activity_id,
        sum(seconds_in_zone) filter (where zone_number = 1) as z1,
        sum(seconds_in_zone) filter (where zone_number = 2) as z2,
        sum(seconds_in_zone) filter (where zone_number = 3) as z3,
        sum(seconds_in_zone) filter (where zone_number = 4) as z4,
        sum(seconds_in_zone) filter (where zone_number = 5) as z5
    from {{ ref('stg_activity_hr_zone') }}
    group by activity_id
)
select
    date_trunc('week', a.activity_date::timestamp)::date as week_start,
    a.activity_type,
    count(*) as sessions,
    round(sum(a.duration_seconds) / 60.0, 1) as duration_minutes,
    round(coalesce(sum(a.training_load), 0), 1) as load,
    round(coalesce(sum(z.z1), 0) / 60.0, 1) as zone1_minutes,
    round(coalesce(sum(z.z2), 0) / 60.0, 1) as zone2_minutes,
    round(coalesce(sum(z.z3), 0) / 60.0, 1) as zone3_minutes,
    round(coalesce(sum(z.z4), 0) / 60.0, 1) as zone4_minutes,
    round(coalesce(sum(z.z5), 0) / 60.0, 1) as zone5_minutes
from {{ ref('stg_activity') }} a
left join zones z using (activity_id)
group by 1, 2
