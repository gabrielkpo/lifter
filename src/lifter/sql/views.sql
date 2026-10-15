-- Views and functions of the `analytics` schema: repeatable, recreated by `lifter migrate`
-- whenever this file changes (tables live in the numbered migrations, in `public`).
-- Change a view here, never in a migration.
-- Every metric definition and threshold is documented in docs/metrics.md; change both together.

drop schema if exists analytics cascade;
create schema analytics;
set local search_path = analytics, public;

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
    (payload ->> 'max_hr_bpm')::numeric as max_hr_bpm,
    (payload ->> 'calories')::numeric as calories,
    (payload ->> 'training_load')::numeric as training_load,
    (payload ->> 'training_effect')::numeric as aerobic_training_effect,
    (payload ->> 'workout_rpe')::numeric as rpe
from latest_garmin_payload
where tool = 'get_activity'
    and not exists (
        select 1 from activity_tombstone t where t.activity_id = (payload ->> 'id')::bigint
    );

-- Every activity seen in a listing, even when its details could not be fetched.
create view stg_activity_listed as
select distinct on (activity_id) activity_id, activity_date
from (
    select
        (item ->> 'id')::bigint as activity_id,
        (item ->> 'start_time')::timestamp::date as activity_date,
        last_seen_at
    from latest_garmin_payload,
        jsonb_array_elements(payload -> 'activities') as item
    where tool = 'get_activities_by_date'
        and jsonb_typeof(payload -> 'activities') = 'array'
) listed
where not exists (select 1 from activity_tombstone t where t.activity_id = listed.activity_id)
order by activity_id, last_seen_at desc;

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
    (payload ->> 'resting_heart_rate_bpm')::numeric as resting_hr_bpm,
    (payload ->> 'deep_sleep_seconds')::numeric as deep_sleep_seconds,
    (payload ->> 'light_sleep_seconds')::numeric as light_sleep_seconds,
    (payload ->> 'rem_sleep_seconds')::numeric as rem_sleep_seconds,
    (payload ->> 'awake_seconds')::numeric as awake_seconds,
    (payload ->> 'awake_count')::numeric as awake_count,
    (payload ->> 'avg_sleep_stress')::numeric as avg_sleep_stress,
    (payload ->> 'avg_overnight_hrv')::numeric as avg_overnight_hrv_ms,
    (payload ->> 'avg_spo2_percent')::numeric as sleep_avg_spo2_percent
from latest_garmin_payload
where tool = 'get_sleep_summary';

create view stg_hrv as
select
    natural_key::date as day,
    (payload ->> 'last_night_avg_hrv_ms')::numeric as hrv_ms,
    payload ->> 'status' as garmin_hrv_status
from latest_garmin_payload
where tool = 'get_hrv_data';

-- Garmin's own daily values (get_stats): Body Battery, stress, resting HR, SpO2, respiration.
create view stg_daily_stats as
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
from latest_garmin_payload
where tool = 'get_stats'
    and jsonb_typeof(payload) = 'object';

-- Garmin training readiness: one or more snapshots a day; the earliest one is the morning
-- value (after waking up), the one that matters to plan the day.
create view stg_training_readiness as
select distinct on (day)
    day, score, level, feedback, recovery_time_hours, acute_load, hrv_weekly_avg_ms,
    snapshot_time
from (
    select
        natural_key::date as day,
        (snap ->> 'score')::numeric as score,
        snap ->> 'level' as level,
        snap ->> 'feedback' as feedback,
        (snap ->> 'recovery_time_hours')::numeric as recovery_time_hours,
        (snap ->> 'acute_load')::numeric as acute_load,
        (snap ->> 'hrv_weekly_avg')::numeric as hrv_weekly_avg_ms,
        (snap ->> 'timestamp')::timestamp as snapshot_time
    from latest_garmin_payload,
        jsonb_array_elements(payload) as snap
    where tool = 'get_training_readiness'
        and jsonb_typeof(payload) = 'array'
) snapshots
order by day, snapshot_time nulls last;

-- Garmin training status: its own acute / chronic load (exponentially weighted), status, VO2max.
create view stg_training_status as
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
from latest_garmin_payload
where tool = 'get_training_status'
    and jsonb_typeof(payload) = 'object';

-- Business metrics. Statuses are computed on the rounded values that agents will cite.

-- least()/greatest() ignore NULL, so greatest(0, NULL) would be 0: guard explicitly.
create or replace function clamp_0_100(x numeric) returns numeric
language sql immutable
as $$ select case when x is null then null else least(100, greatest(0, x)) end $$;

create view daily_load as
with detailed as (
    select
        activity_date as day,
        count(*) as sessions,
        round(coalesce(sum(training_load), 0), 1) as load,
        count(*) filter (where training_load is null) as sessions_without_load,
        sum(duration_seconds) / 60.0 as duration_minutes
    from stg_activity
    group by activity_date
),
-- Listed activities whose details are missing: their load is unknown, not zero.
missing as (
    select l.activity_date as day, count(*) as sessions_missing_details
    from stg_activity_listed l
    left join stg_activity a using (activity_id)
    where a.activity_id is null
    group by l.activity_date
)
select
    day,
    coalesce(d.sessions, 0) as sessions,
    coalesce(d.load, 0) as load,
    coalesce(d.sessions_without_load, 0) as sessions_without_load,
    coalesce(m.sessions_missing_details, 0) as sessions_missing_details,
    d.duration_minutes
from detailed d
full join missing m using (day);

-- One row per calendar day between the first and last day with any data,
-- so rolling windows count days, not rows.
create view daily_base as
with bounds as (
    select
        least((select min(day) from stg_hrv), (select min(day) from stg_sleep),
              (select min(day) from daily_load), (select min(day) from stg_daily_stats))
            as first_day,
        greatest((select max(day) from stg_hrv), (select max(day) from stg_sleep),
                 (select max(day) from daily_load), (select max(day) from stg_daily_stats))
            as last_day
),
calendar as (
    select d::date as day
    from bounds, generate_series(first_day, last_day, interval '1 day') as d
)
select
    c.day,
    coalesce(l.sessions, 0) as sessions,
    round(coalesce(l.load, 0), 1) as load,
    coalesce(l.sessions_missing_details, 0) as sessions_missing_details,
    h.hrv_ms,
    -- Garmin's daily resting HR (get_stats); the sleep summary value is only a fallback, some
    -- watches never fill it.
    coalesce(d.garmin_resting_hr_bpm, s.resting_hr_bpm) as resting_hr_bpm,
    s.sleep_seconds,
    s.sleep_score
from calendar c
left join daily_load l using (day)
left join stg_hrv h using (day)
left join stg_sleep s using (day)
left join stg_daily_stats d using (day);

create view daily_metrics as
with windows as (
    select
        b.*,
        row_number() over (order by day) as history_days,
        sum(load) over w7 as acute_load_7d_raw,
        sum(load) over w28 / 4.0 as chronic_load_28d_raw,
        avg(hrv_ms) over prev28 as hrv_baseline_raw,
        count(hrv_ms) over prev28 as hrv_baseline_nights,
        avg(resting_hr_bpm) over prev28 as rhr_baseline_raw,
        count(resting_hr_bpm) over prev28 as rhr_baseline_days,
        avg(hrv_ms) over w7 as hrv_7d_avg_raw
    from daily_base b
    window
        w7 as (order by day rows between 6 preceding and current row),
        w28 as (order by day rows between 27 preceding and current row),
        prev28 as (order by day rows between 28 preceding and 1 preceding)
),
rounded as (
    select
        day, sessions, sessions_missing_details, load, hrv_ms, resting_hr_bpm, sleep_score,
        history_days,
        -- A window is only reported once it is full: a partial one underestimates the load.
        case when history_days >= 7 then round(acute_load_7d_raw, 1) end as acute_load_7d,
        case when history_days >= 28 then round(chronic_load_28d_raw, 1) end as chronic_load_28d,
        case when history_days >= 28 and chronic_load_28d_raw > 0
            then round(acute_load_7d_raw / chronic_load_28d_raw, 2) end as acwr,
        case when hrv_baseline_nights >= 14 then round(hrv_baseline_raw, 1) end as hrv_baseline_28d,
        case when hrv_baseline_nights >= 14
            then round(100 * (hrv_ms - hrv_baseline_raw) / nullif(hrv_baseline_raw, 0), 1)
            end as hrv_delta_pct,
        case when hrv_baseline_nights >= 14
            then round(100 * (hrv_7d_avg_raw - hrv_baseline_raw) / nullif(hrv_baseline_raw, 0), 1)
            end as hrv_7d_delta_pct,
        case when rhr_baseline_days >= 14 then round(rhr_baseline_raw, 1) end as rhr_baseline_28d,
        case when rhr_baseline_days >= 14
            then round(resting_hr_bpm - rhr_baseline_raw, 1) end as rhr_delta_bpm,
        round(sleep_seconds / 3600.0, 2) as sleep_hours
    from windows
),
components as (
    select
        r.*,
        clamp_0_100(50 + 2.5 * hrv_delta_pct) as hrv_component,
        clamp_0_100(50 - 10 * rhr_delta_bpm) as rhr_component,
        clamp_0_100(100 * (sleep_hours - 5) / 3) as sleep_component
    from rounded r
),
scored as (
    select
        c.*,
        -- HRV is required; resting HR and sleep are averaged in when present.
        case when hrv_component is not null then round(
            (hrv_component + coalesce(rhr_component, 0) + coalesce(sleep_component, 0))
            / (1 + (rhr_component is not null)::int + (sleep_component is not null)::int)
        ) end as recovery_score
    from components c
),
trended as (
    select
        s.*,
        case when count(recovery_score) over w7 >= 4
            then round(avg(recovery_score) over w7, 1) end as recovery_7d_avg,
        lag(chronic_load_28d, 14) over (order by day) as chronic_load_28d_14d_ago
    from scored s
    window w7 as (order by day rows between 6 preceding and current row)
)
select
    day,
    history_days,
    sessions,
    sessions_missing_details,
    load,
    acute_load_7d,
    chronic_load_28d,
    acwr,
    hrv_ms,
    hrv_baseline_28d,
    hrv_delta_pct,
    hrv_7d_delta_pct,
    resting_hr_bpm,
    rhr_baseline_28d,
    rhr_delta_bpm,
    sleep_hours,
    sleep_score,
    recovery_score,
    case
        when recovery_score is null then 'unknown'
        when recovery_score < 40 then 'low'
        when recovery_score < 70 then 'normal'
        else 'good'
    end as recovery_status,
    recovery_7d_avg,
    case
        when recovery_7d_avg is null or acwr is null then 'unknown'
        when recovery_7d_avg < 45 or (acwr > 1.3 and hrv_7d_delta_pct <= -5) then 'fatigue'
        when chronic_load_28d_14d_ago > 0
            and chronic_load_28d >= 1.05 * chronic_load_28d_14d_ago
            and recovery_7d_avg >= 55 then 'improving'
        else 'stable'
    end as trend
from trended;

create view daily_alerts as
select m.day, a.alert, a.severity, a.value, a.threshold
from daily_metrics m,
    lateral (values
        ('load_spike', 'warning', m.acwr, 1.5, m.acwr > 1.5),
        ('load_drop', 'info', m.acwr, 0.8, m.acwr < 0.8),
        ('hrv_drop', 'warning', m.hrv_delta_pct, -15, m.hrv_delta_pct <= -15),
        ('rhr_elevated', 'warning', m.rhr_delta_bpm, 5, m.rhr_delta_bpm >= 5),
        ('short_sleep', 'info', m.sleep_hours, 6, m.sleep_hours < 6),
        ('abnormal_hrv', 'critical', m.hrv_delta_pct, -30, m.hrv_delta_pct <= -30),
        ('abnormal_rhr', 'critical', m.rhr_delta_bpm, 10, m.rhr_delta_bpm >= 10)
    ) as a (alert, severity, value, threshold, triggered)
where a.triggered;

-- Sessions per ISO week (Monday start) and activity type, with minutes per heart rate zone.
create view weekly_training as
with zones as (
    select
        activity_id,
        sum(seconds_in_zone) filter (where zone_number = 1) as z1,
        sum(seconds_in_zone) filter (where zone_number = 2) as z2,
        sum(seconds_in_zone) filter (where zone_number = 3) as z3,
        sum(seconds_in_zone) filter (where zone_number = 4) as z4,
        sum(seconds_in_zone) filter (where zone_number = 5) as z5
    from stg_activity_hr_zone
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
from stg_activity a
left join zones z using (activity_id)
group by 1, 2;

-- Recovery and form, one row per calendar day: Garmin's own values next to the sleep details.
-- These are Garmin's figures, stored as received and rounded only for display; Lifter's own
-- definitions stay in daily_metrics.
create view daily_recovery as
select
    b.day,
    round(s.sleep_seconds / 3600.0, 2) as sleep_hours,
    s.sleep_score,
    round(s.deep_sleep_seconds / 60.0) as deep_sleep_minutes,
    round(s.rem_sleep_seconds / 60.0) as rem_sleep_minutes,
    round(s.awake_seconds / 60.0) as awake_minutes,
    s.awake_count,
    s.avg_sleep_stress,
    d.body_battery_highest,
    d.body_battery_lowest,
    d.body_battery_charged,
    d.body_battery_drained,
    d.avg_stress,
    d.stress_qualifier,
    d.garmin_resting_hr_bpm,
    d.avg_spo2_percent,
    d.avg_waking_respiration,
    case when d.moderate_intensity_minutes is not null or d.vigorous_intensity_minutes is not null
        then coalesce(d.moderate_intensity_minutes, 0) + 2 * coalesce(d.vigorous_intensity_minutes, 0)
    end as intensity_minutes,
    r.score as readiness_score,
    r.level as readiness_level,
    r.recovery_time_hours,
    t.garmin_training_status,
    t.garmin_acute_load,
    t.garmin_chronic_load,
    t.garmin_load_ratio,
    t.vo2_max
from daily_base b
left join stg_sleep s using (day)
left join stg_daily_stats d using (day)
left join stg_training_readiness r using (day)
left join stg_training_status t using (day);


-- CrossFit domain (docs/domain.md).

-- Activity types that can be a CrossFit session (training, cardio on ergs, mobility). Other
-- activities (a bike commute, a walk) count in the load but never complete a session.
create or replace function is_session_activity(activity_type text) returns boolean
language sql immutable
as $$
    select coalesce(
        activity_type ~ '^(hiit|strength_training|stop_watch|indoor_cardio|indoor_rowing|indoor_cycling|fitness_equipment|cardio_training|training|crossfit|yoga|pilates|mobility|breathwork)$',
        false
    )
$$;

-- Garmin calendar snapshot (latest sync only).
create view stg_scheduled_workout as
select
    (item ->> 'date')::date as day,
    (item ->> 'scheduled_workout_id')::bigint as garmin_schedule_id,
    (item ->> 'workout_id')::bigint as garmin_workout_id,
    item ->> 'name' as name,
    lower(item ->> 'sport') as sport,
    (item ->> 'completed')::boolean as completed
from latest_garmin_payload,
    jsonb_array_elements(payload -> 'scheduled_workouts') as item
where tool = 'get_scheduled_workouts'
    and jsonb_typeof(payload -> 'scheduled_workouts') = 'array';

-- Which Garmin activities belong to which session. An activity matched explicitly
-- (planned_session.matched_activity_id) belongs to that session. Otherwise, on each day, the
-- n-th session activity (by start time) goes to the n-th open session (by id); extra
-- activities go to the day's last session, since one session is often recorded in two parts
-- (strength, then the metcon). Mobility sessions, rarely recorded, take activities only on a
-- day without another open session. An activity never belongs to two sessions; cancelled and
-- rest sessions take none.
create view session_activity as
with candidates as (
    select
        id,
        day,
        kind,
        bool_or(kind <> 'mobility') over (partition by day) as day_has_other
    from planned_session
    where status = 'planned' and kind <> 'rest' and matched_activity_id is null
),
open_sessions as (
    select
        id,
        day,
        row_number() over (partition by day order by id) as rank,
        count(*) over (partition by day) as sessions_that_day
    from candidates
    where kind <> 'mobility' or not day_has_other
),
free_activities as (
    select
        activity_id,
        activity_date as day,
        row_number() over (
            partition by activity_date order by start_time_local, activity_id
        ) as rank
    from stg_activity a
    where is_session_activity(activity_type)
        and not exists (
            select 1 from planned_session p where p.matched_activity_id = a.activity_id
        )
)
select o.id as planned_session_id, f.activity_id
from free_activities f
join open_sessions o
    on o.day = f.day and o.rank = least(f.rank, o.sessions_that_day)
union all
select p.id, p.matched_activity_id
from planned_session p
where p.status = 'planned' and p.matched_activity_id is not null;

-- The Garmin line of a session, summed over its activities: duration, heart rate, calories,
-- load and minutes in zones 4-5. Average heart rate is weighted by duration.
create view session_garmin as
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
from session_activity sa
join stg_activity a using (activity_id)
left join (
    select activity_id, sum(seconds_in_zone) as z45_seconds
    from stg_activity_hr_zone
    where zone_number >= 4
    group by activity_id
) z using (activity_id)
group by sa.planned_session_id;

-- Planned sessions with their outcome: "done" when a Garmin activity belongs to the session or
-- when it was logged (exercises done, a metcon result, or a session feedback), since the
-- watch is not always worn; "missed" once the day is past without either; "cancelled" when the
-- athlete or an approved proposal cancelled it.
create view planned_session_status as
with logged as (
    select sp.session_id as id
    from session_part sp
    where sp.result_seconds is not null or sp.result_rounds is not null
        or exists (
            select 1 from session_exercise se where se.part_id = sp.id and se.origin = 'done'
        )
    union
    select planned_session_id from feedback where planned_session_id is not null
)
select
    p.id as planned_session_id,
    p.day,
    p.title,
    p.kind,
    p.week_id,
    p.moved_from,
    g.activities,
    p.id in (select id from logged) as logged,
    case
        when p.status = 'cancelled' then 'cancelled'
        when p.kind = 'rest' then 'rest'
        when g.activities is not null or p.id in (select id from logged) then 'done'
        when p.day < current_date then 'missed'
        else 'planned'
    end as status
from planned_session p
left join session_garmin g on g.planned_session_id = p.id;

-- Everything on the athlete's calendar, one row per item: Lifter sessions, workouts that only
-- exist in Garmin's calendar, and activities that belong to no session.
create view calendar as
select
    s.day, 'session' as kind, 'lifter' as source, s.title, s.kind as detail, s.status,
    s.planned_session_id, null::bigint as activity_id
from planned_session_status s
union all
select
    g.day, 'session', 'garmin', g.name, g.sport,
    case when g.completed then 'done' when g.day < current_date then 'missed' else 'planned' end,
    null, null
from stg_scheduled_workout g
union all
select
    a.activity_date, 'activity', 'garmin', a.name, a.activity_type,
    case when is_session_activity(a.activity_type) then 'done (unplanned)' else 'other' end,
    null, a.activity_id
from stg_activity a
where not exists (select 1 from session_activity sa where sa.activity_id = a.activity_id);

-- Exercise lines with their exercise, for reading a session or a week.
create view session_line as
select
    sp.session_id,
    sp.position as part_position,
    sp.kind as part_kind,
    se.origin,
    se.position,
    e.name as exercise,
    e.category,
    e.pattern,
    se.sets,
    se.quantity,
    se.unit,
    se.load_kg,
    se.load_kg_max,
    se.rir,
    se.rest_seconds,
    se.notes
from session_exercise se
join session_part sp on sp.id = se.part_id
join exercise e on e.id = se.exercise_id;

-- The review of each week, what the weekly programming starts from: sessions planned, done,
-- missed and cancelled, strength sessions done (done sessions with a strength part: they count
-- toward the block), and the movement patterns actually trained.
create view week_summary as
select
    w.id as week_id,
    w.block_id,
    w.number,
    w.start_date,
    w.phase,
    b.kind as block,
    count(s.planned_session_id) filter (where s.status <> 'rest') as sessions,
    count(*) filter (where s.status = 'done') as done,
    count(*) filter (where s.status = 'missed') as missed,
    count(*) filter (where s.status = 'cancelled') as cancelled,
    count(*) filter (
        where s.status = 'done' and exists (
            select 1 from session_part sp
            where sp.session_id = s.planned_session_id and sp.kind = 'strength'
        )
    ) as strength_sessions_done,
    (
        select array_agg(distinct l.pattern order by l.pattern)
        from session_line l
        join planned_session p on p.id = l.session_id
        where p.week_id = w.id and l.origin = 'done' and l.part_kind <> 'warmup'
    ) as patterns_done
from training_week w
left join block b on b.id = w.block_id
left join planned_session_status s on s.week_id = w.id
group by w.id, b.kind;

-- Progress of each block: it ends when its strength-session count is reached.
create view block_progress as
select
    b.id as block_id,
    b.cycle_id,
    b.position,
    b.kind,
    b.start_date,
    b.end_date,
    b.target_strength_sessions,
    coalesce(sum(ws.strength_sessions_done), 0) as strength_sessions_done
from block b
left join week_summary ws on ws.block_id = b.id
group by b.id;

-- Best logged load per exercise and repetition count (sets done in reps with a load).
create view exercise_best as
select distinct on (l.exercise, l.quantity)
    l.exercise,
    l.quantity as reps,
    l.load_kg as best_load_kg,
    p.day
from session_line l
join planned_session p on p.id = l.session_id
where l.origin = 'done' and l.unit = 'reps' and l.load_kg is not null and l.quantity is not null
order by l.exercise, l.quantity, l.load_kg desc, p.day;
