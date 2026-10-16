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
    from {{ ref('daily_base') }} b
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
        {{ target.schema }}.clamp_0_100(50 + 2.5 * hrv_delta_pct) as hrv_component,
        {{ target.schema }}.clamp_0_100(50 - 10 * rhr_delta_bpm) as rhr_component,
        {{ target.schema }}.clamp_0_100(100 * (sleep_hours - 5) / 3) as sleep_component
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
from trended
