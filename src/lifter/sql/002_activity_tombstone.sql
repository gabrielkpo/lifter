-- Activities that a complete listing no longer returns (deleted or merged in Garmin Connect).
-- Their raw payloads are kept for audit; the staging views ignore them.
-- A tombstoned activity that is listed again is restored by the sync.
create table activity_tombstone (
    activity_id bigint primary key,
    detected_at timestamptz not null default now()
);
