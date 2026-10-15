-- Lifter's own domain, for CrossFit: the training cycle, the sessions (planned and logged),
-- the exercise bank, goals, rules, feedback and proposals. Agents never write here directly:
-- they create proposals; code applies the approved ones (lifter.domain).

-- Exercise bank. `flags` mark what the athlete's rules can forbid (e.g. impact, running).
create table exercise (
    id bigserial primary key,
    name text not null unique,
    category text not null check (category in (
        'weightlifting', 'gymnastics', 'strength', 'monostructural', 'mobility', 'other'
    )),
    pattern text not null default 'other' check (pattern in (
        'olympic', 'push', 'pull', 'legs', 'hinge', 'core', 'carry', 'engine', 'full_body',
        'mobility', 'other'
    )),
    equipment text,
    flags text[] not null default '{}',
    notes text
);

-- A cycle (about 3 months) made of blocks, each block made of weeks.
create table cycle (
    id bigserial primary key,
    name text not null unique,
    start_date date not null,
    end_date date not null,
    notes text,
    status text not null default 'active' check (status in ('active', 'done', 'cancelled')),
    created_at timestamptz not null default now(),
    check (end_date >= start_date)
);

-- A block is counted in strength sessions done, not in weeks: it ends when
-- `target_strength_sessions` is reached (dates are indicative).
create table block (
    id bigserial primary key,
    cycle_id bigint not null references cycle (id) on delete cascade,
    position int not null check (position >= 1),
    kind text not null check (kind in ('accumulation', 'transmutation', 'realisation')),
    start_date date not null,
    end_date date not null,
    intent text,
    target_strength_sessions int check (target_strength_sessions > 0),
    unique (cycle_id, position),
    check (end_date >= start_date)
);

-- A week of the cycle: its phase and the intent for each part of the sessions. A week can sit
-- outside any block (e.g. an entry deload before the first block). `review` is the athlete's
-- review of the week, written when the next week is programmed.
create table training_week (
    id bigserial primary key,
    cycle_id bigint not null references cycle (id) on delete cascade,
    block_id bigint references block (id) on delete cascade,
    number int not null check (number >= 0),
    start_date date not null,
    phase text not null check (phase in (
        'reset', 'reference', 'volume', 'volume_peak', 'deload', 'strength',
        'intensification', 'strength_peak', 'power', 'density', 'peak', 'test'
    )),
    title text,
    intent jsonb not null default '{}',
    review text,
    unique (cycle_id, number)
);

-- A session in the calendar. Its content lives in session_part and session_exercise.
-- "done" and "missed" are derived by the views from the activities and the log; the stored
-- status only records explicit decisions.
create table planned_session (
    id bigserial primary key,
    day date not null,
    title text not null,
    kind text not null default 'training'
        check (kind in ('training', 'cardio', 'mobility', 'rest')),
    week_id bigint references training_week (id) on delete set null,
    notes text,
    deviation text,
    status text not null default 'planned' check (status in ('planned', 'cancelled')),
    matched_activity_id bigint,
    moved_from date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index planned_session_day_idx on planned_session (day);

-- The ordered parts of a session: warm-up, weightlifting / gymnastics, strength, metcon, or a
-- cardio / mobility block. A metcon has a format and a target (a time to beat, or rounds to
-- reach), never a time cap; its result is logged on the same row.
create table session_part (
    id bigserial primary key,
    session_id bigint not null references planned_session (id) on delete cascade,
    position int not null check (position >= 1),
    kind text not null check (kind in (
        'warmup', 'weightlifting', 'gymnastics', 'strength', 'metcon', 'cardio', 'mobility'
    )),
    title text,
    notes text,
    format text check (format in (
        'for_time', 'amrap', 'emom', 'every_n', 'rounds', 'intervals', 'other'
    )),
    duration_minutes numeric check (duration_minutes > 0),
    rounds int check (rounds > 0),
    interval_seconds int check (interval_seconds > 0),
    target_seconds int check (target_seconds > 0),
    target_rounds numeric check (target_rounds > 0),
    result_seconds int check (result_seconds > 0),
    result_rounds numeric check (result_rounds >= 0),
    result_notes text,
    unique (session_id, position)
);

-- One exercise line of a part, as prescribed (`planned`) or as done (`done`). Both share the
-- same shape, so the gap between plan and log is a comparison of rows. `quantity` is counted
-- in `unit` per set (8 reps, 15 cal, 200 m, 30 s). The RIR is the instruction, the load a
-- guide; `load_kg_max` gives a range.
create table session_exercise (
    id bigserial primary key,
    part_id bigint not null references session_part (id) on delete cascade,
    origin text not null check (origin in ('planned', 'done')),
    position int not null check (position >= 1),
    exercise_id bigint not null references exercise (id),
    sets int check (sets > 0),
    quantity numeric check (quantity > 0),
    unit text not null default 'reps' check (unit in ('reps', 'cal', 'm', 's', 'min')),
    load_kg numeric check (load_kg >= 0),
    load_kg_max numeric check (load_kg_max >= load_kg),
    rir int check (rir between 0 and 10),
    rest_seconds int check (rest_seconds >= 0),
    notes text,
    unique (part_id, origin, position)
);

-- Goals: a load or a skill on an exercise, or a benchmark metcon, with dated milestones.
create table goal (
    id bigserial primary key,
    title text not null,
    kind text not null default 'strength' check (kind in ('strength', 'skill', 'benchmark', 'other')),
    exercise_id bigint references exercise (id),
    cycle_id bigint references cycle (id) on delete set null,
    unit text,
    baseline_value numeric,
    baseline_text text,
    baseline_date date,
    target_value numeric,
    target_text text,
    target_date date,
    status text not null default 'active' check (status in ('active', 'achieved', 'abandoned')),
    notes text,
    created_at timestamptz not null default now(),
    check (target_value is not null or target_text is not null)
);

create table goal_milestone (
    id bigserial primary key,
    goal_id bigint not null references goal (id) on delete cascade,
    day date not null,
    label text,
    value numeric,
    value_text text,
    check (value is not null or value_text is not null)
);

-- The athlete's permanent rules. `code` names a rule the guardrail checks in code (step 3);
-- rules without a code are context for the coach. Stored locally, never in the repository.
create table athlete_rule (
    id bigserial primary key,
    code text,
    text text not null,
    params jsonb not null default '{}',
    active boolean not null default true
);

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
        'create_session', 'move_session', 'cancel_session', 'create_goal'
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
