-- Activities that Garmin Connect confirms deleted (404 on get_activity) after a complete
-- listing stopped returning them. Raw payloads are kept for audit; the views ignore them.
-- A tombstoned activity that is listed or fetched again is restored by the sync.
create table if not exists activity_tombstone (
    activity_id bigint primary key,
    detected_at timestamptz not null default now()
);

-- Views now live in the `analytics` schema (views.sql). Drop the copies that the former
-- migrations 002_staging.sql and 003_metrics.sql created in `public`.
drop view if exists
    public.weekly_training, public.daily_alerts, public.daily_metrics, public.daily_base,
    public.daily_load, public.stg_hrv, public.stg_sleep, public.stg_activity_hr_zone,
    public.stg_activity_listed, public.stg_activity, public.latest_garmin_payload
    cascade;
drop function if exists public.clamp_0_100(numeric);
