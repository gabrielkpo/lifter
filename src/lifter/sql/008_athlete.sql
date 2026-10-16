-- Who the coach plans for: the athlete's profile and the health issues they declared.
-- Real values live in the database only, never in the repository. Lifter makes no diagnosis:
-- it only respects what the athlete declared (`guidance`).

-- One row: the database serves one athlete.
create table athlete (
    id smallint primary key default 1 check (id = 1),
    first_name text,
    birth_date date,
    sex text check (sex in ('male', 'female', 'other')),
    height_cm numeric(4, 1) check (height_cm between 100 and 250),
    weight_kg numeric(4, 1) check (weight_kg between 30 and 250),
    weight_date date,
    handedness text check (handedness in ('right', 'left', 'both')),
    level text check (level in ('beginner', 'intermediate', 'advanced', 'competitor')),
    practice_since date,
    sessions_per_week int check (sessions_per_week between 0 and 14),
    -- Life context the coach must plan around (night shifts, on-call duty, travel).
    context text,
    updated_at timestamptz not null default now()
);

-- A pain, injury or lasting limitation. The coach records one when the athlete reports it
-- (`source` 'agent', with the athlete's own words in `reported_quote`) and plans around the
-- active ones; the athlete marks it resolved.
create table health_issue (
    id bigserial primary key,
    body_part text not null,
    side text check (side in ('left', 'right', 'both')),
    kind text not null check (kind in ('pain', 'injury', 'limitation')),
    description text not null,
    guidance text,
    since date,
    status text not null default 'active' check (status in ('active', 'monitoring', 'resolved')),
    resolved_on date,
    source text not null default 'athlete' check (source in ('athlete', 'agent')),
    reported_quote text,
    created_at timestamptz not null default now(),
    check ((status = 'resolved') = (resolved_on is not null))
);
create index health_issue_status_idx on health_issue (status);
