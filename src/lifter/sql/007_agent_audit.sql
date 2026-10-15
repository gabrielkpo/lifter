-- Audit log of the agents: what each run read, what the model answered at each attempt, what
-- the guardrail said, what it cost, and which proposals came out of it. Written by code after
-- the run, never by an agent. It holds the context sent to the model, so it stays in the local
-- database like the rest of the athlete's data.

create table agent_run (
    id bigserial primary key,
    agent text not null,
    trigger text not null check (trigger in ('cli', 'app', 'job', 'bench')),
    model text,
    context_mode text,
    target_week_id bigint references training_week (id) on delete set null,
    status text not null check (status in ('accepted', 'refused', 'error')),
    attempts int not null default 0,
    input_tokens int not null default 0,
    output_tokens int not null default 0,
    seconds numeric not null default 0,
    context jsonb,
    plan jsonb,
    warnings jsonb not null default '[]',
    proposal_ids bigint[] not null default '{}',
    error text,
    started_at timestamptz not null,
    finished_at timestamptz not null default now()
);
create index agent_run_started_idx on agent_run (started_at desc);

-- One row per attempt of a run: the model's answer (null when it did not parse) and the
-- guardrail's violations for it.
create table agent_step (
    id bigserial primary key,
    run_id bigint not null references agent_run (id) on delete cascade,
    attempt int not null check (attempt >= 1),
    plan jsonb,
    violations jsonb not null default '[]',
    input_tokens int not null default 0,
    output_tokens int not null default 0,
    seconds numeric not null default 0,
    unique (run_id, attempt)
);
