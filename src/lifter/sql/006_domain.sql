-- Lifter's own domain: what the athlete plans, aims for and reports. Agents never write here
-- directly: they create proposals; code applies the approved ones (lifter.domain).

create table goal (
    id bigserial primary key,
    title text not null,
    kind text not null default 'event'
        check (kind in ('event', 'performance', 'volume', 'health', 'other')),
    sport text,
    target_date date,
    target_value numeric,
    target_unit text,
    status text not null default 'active' check (status in ('active', 'achieved', 'abandoned')),
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- A training cycle toward a goal (macro or meso level).
create table training_plan (
    id bigserial primary key,
    goal_id bigint references goal (id) on delete set null,
    name text not null,
    phase text not null default 'base'
        check (phase in ('base', 'build', 'peak', 'taper', 'recovery', 'transition')),
    start_date date not null,
    end_date date not null,
    notes text,
    status text not null default 'active' check (status in ('active', 'done', 'cancelled')),
    created_at timestamptz not null default now(),
    check (end_date >= start_date)
);

-- A session in the athlete's calendar. "done" and "missed" are derived by the calendar view
-- from the activities; the stored status only records explicit decisions.
create table planned_session (
    id bigserial primary key,
    day date not null,
    sport text not null,
    title text not null,
    description text,
    intensity text not null default 'moderate'
        check (intensity in ('rest', 'easy', 'moderate', 'hard', 'race')),
    target_duration_minutes numeric check (target_duration_minutes > 0),
    target_load numeric check (target_load >= 0),
    structure jsonb,
    status text not null default 'planned' check (status in ('planned', 'cancelled')),
    goal_id bigint references goal (id) on delete set null,
    plan_id bigint references training_plan (id) on delete set null,
    garmin_workout_id bigint,
    garmin_schedule_id bigint,
    matched_activity_id bigint,
    moved_from date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index planned_session_day_idx on planned_session (day);

-- What the athlete reports: after a session, or the morning check-in.
create table feedback (
    id bigserial primary key,
    day date not null,
    kind text not null default 'session' check (kind in ('session', 'morning')),
    planned_session_id bigint references planned_session (id) on delete set null,
    activity_id bigint,
    rpe int check (rpe between 1 and 10),
    fatigue int check (fatigue between 1 and 5),
    pain int check (pain between 0 and 10),
    pain_location text,
    notes text,
    created_at timestamptz not null default now()
);
create index feedback_day_idx on feedback (day);

-- An action an agent proposes; nothing changes until the athlete approves it and code
-- applies it. Payload shape depends on kind and is validated in lifter.domain.
create table proposal (
    id bigserial primary key,
    kind text not null check (kind in (
        'create_session', 'move_session', 'cancel_session', 'create_goal', 'create_plan'
    )),
    payload jsonb not null,
    rationale text not null,
    author text not null,
    status text not null default 'pending'
        check (status in ('pending', 'approved', 'rejected', 'applied', 'failed')),
    result jsonb,
    created_at timestamptz not null default now(),
    decided_at timestamptz,
    applied_at timestamptz
);
create index proposal_status_idx on proposal (status, created_at);
