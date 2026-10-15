-- Business metrics. Every definition and threshold here is documented in docs/metrics.md;
-- change both together. Statuses are computed on the rounded values that agents will cite.

-- least()/greatest() ignore NULL, so greatest(0, NULL) would be 0: guard explicitly.
create function clamp_0_100(x numeric) returns numeric
language sql immutable
as $$ select case when x is null then null else least(100, greatest(0, x)) end $$;

create view daily_load as
select
    activity_date as day,
    count(*) as sessions,
    coalesce(sum(training_load), 0) as load,
    count(*) filter (where training_load is null) as sessions_without_load,
    sum(duration_seconds) / 60.0 as duration_minutes
from stg_activity
group by activity_date;

-- One row per calendar day between the first and last day with any data,
-- so rolling windows count days, not rows.
create view daily_base as
with bounds as (
    select
        least((select min(day) from stg_hrv), (select min(day) from stg_sleep),
              (select min(day) from daily_load)) as first_day,
        greatest((select max(day) from stg_hrv), (select max(day) from stg_sleep),
                 (select max(day) from daily_load)) as last_day
),
calendar as (
    select d::date as day
    from bounds, generate_series(first_day, last_day, interval '1 day') as d
)
select
    c.day,
    coalesce(l.sessions, 0) as sessions,
    coalesce(l.load, 0) as load,
    h.hrv_ms,
    s.resting_hr_bpm,
    s.sleep_seconds,
    s.sleep_score
from calendar c
left join daily_load l using (day)
left join stg_hrv h using (day)
left join stg_sleep s using (day);

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
        day, sessions, load, hrv_ms, resting_hr_bpm, sleep_score, history_days,
        -- A window is only reported once it is full: a partial one underestimates the load.
        case when history_days >= 7 then round(acute_load_7d_raw, 1) end as acute_load_7d,
        case when history_days >= 28 then round(chronic_load_28d_raw, 1) end as chronic_load_28d,
        case when history_days >= 28 and chronic_load_28d_raw > 0
            then round(acute_load_7d_raw / chronic_load_28d_raw, 2) end as acwr,
        case when hrv_baseline_nights >= 14 then round(hrv_baseline_raw, 1) end as hrv_baseline_28d,
        case when hrv_baseline_nights >= 14
            then round(100 * (hrv_ms - hrv_baseline_raw) / hrv_baseline_raw, 1) end as hrv_delta_pct,
        case when hrv_baseline_nights >= 14
            then round(100 * (hrv_7d_avg_raw - hrv_baseline_raw) / hrv_baseline_raw, 1)
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
