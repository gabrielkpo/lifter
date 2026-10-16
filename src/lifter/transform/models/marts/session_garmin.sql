-- The Garmin line of a session, summed over its activities: duration, heart rate, calories,
-- load and minutes in zones 4-5. Average heart rate is weighted by duration.
select
    sa.planned_session_id,
    count(*) as activities,
    round(sum(a.duration_seconds) / 60.0) as duration_minutes,
    round(
        sum(a.avg_hr_bpm * a.duration_seconds)
        / nullif(sum(a.duration_seconds) filter (where a.avg_hr_bpm is not null), 0)
    ) as avg_hr_bpm,
    round(max(a.max_hr_bpm)) as max_hr_bpm,
    round(sum(a.calories)) as calories,
    round(sum(a.training_load), 1) as training_load,
    round(coalesce(sum(z.z45_seconds), 0) / 60.0) as z4_z5_minutes
from {{ ref('session_activity') }} sa
join {{ ref('stg_activity') }} a using (activity_id)
left join (
    select activity_id, sum(seconds_in_zone) as z45_seconds
    from {{ ref('stg_activity_hr_zone') }}
    where zone_number >= 4
    group by activity_id
) z using (activity_id)
group by sa.planned_session_id
