-- Raw layer: every Garmin MCP response, stored as received.
-- One row per distinct payload; a payload seen again only moves last_seen_at,
-- so the latest version of a key is always the one with the newest last_seen_at.
create table raw_garmin_payload (
    id bigserial primary key,
    tool text not null,
    natural_key text not null,           -- day (YYYY-MM-DD), activity id or list page
    params jsonb not null,
    payload jsonb not null,
    payload_sha256 text not null,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    unique (tool, natural_key, payload_sha256)
);

create index raw_garmin_payload_latest_idx
    on raw_garmin_payload (tool, natural_key, last_seen_at desc);

-- One row per call, including empty answers and errors, so a sync can be audited.
create table sync_log (
    id bigserial primary key,
    tool text not null,
    natural_key text not null,
    status text not null check (status in ('stored', 'unchanged', 'empty', 'error')),
    message text,
    at timestamptz not null default now()
);
