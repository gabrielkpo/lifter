-- The coach's write path (docs/adr/0002-coach-write-path-and-agent-team.md, Decision 3).
-- Every change the coach makes goes through lifter.operations: a typed operation, the
-- athlete's quote checked against their stored message, the rules, then a trace (proposal +
-- change_log) from which `undo` rebuilds the previous state. This file adds the tables of that
-- trace, the conversation, the records and Garmin annotations, a row version on every table
-- the coach may change, and the database's own guarantee: no write by the coach without a trace.

-- The conversation. The endpoint stores the athlete's message before the model runs; the quote
-- check (lifter.quote) reads it back by id, never a copy that came through the model.
create table conversation_message (
    id bigserial primary key,
    conversation_id text not null,
    role text not null check (role in ('athlete', 'coach')),
    text text not null,
    created_at timestamptz not null default now()
);
create index conversation_message_conversation_idx on conversation_message (conversation_id, id);

-- Proposals become the trace of every change: any catalogue operation, the athlete's quote and
-- message, a key against retries, and the undo that reverted it.
alter table proposal drop constraint proposal_kind_check;
alter table proposal add constraint proposal_kind_check check (kind ~ '^[a-z][a-z_]*$');
alter table proposal drop constraint proposal_status_check;
alter table proposal add constraint proposal_status_check
    check (status in ('pending', 'approved', 'rejected', 'applied', 'failed', 'expired'));
alter table proposal
    add column quote text,
    add column message_id bigint references conversation_message (id),
    add column idempotency_key text unique,
    add column undone_by bigint references proposal (id);

-- One row per applied change: the rows before and after, which `undo` restores. Written in the
-- same transaction as the change; never updated nor deleted by the coach (roles.sql).
create table change_log (
    id bigserial primary key,
    proposal_id bigint not null references proposal (id),
    txid bigint not null default txid_current(),
    operation text not null,
    entity text not null,
    entity_id bigint,
    before jsonb not null,
    after jsonb not null,
    created_at timestamptz not null default now()
);
create index change_log_txid_idx on change_log (txid);

-- Records the athlete holds, by kind and family (the PR tab): a definition per movement or
-- benchmark, and dated entries. Lifts also come from logged sets (analytics.exercise_best).
create table record_definition (
    id bigserial primary key,
    name text not null unique,
    kind text not null check (kind in ('lift', 'gym', 'cardio', 'benchmark')),
    family text,
    record_type text not null check (record_type in (
        'rep_max', 'max_reps', 'max_load', 'max_distance', 'max_time', 'time', 'rounds'
    )),
    unit text,
    description text,
    exercise_id bigint references exercise (id) on delete set null
);

create table record_entry (
    id bigserial primary key,
    definition_id bigint not null references record_definition (id) on delete cascade,
    day date not null,
    reps int check (reps > 0),
    value numeric,
    value_text text,
    notes text,
    source text not null default 'athlete' check (source in ('athlete', 'agent')),
    created_at timestamptz not null default now(),
    check (value is not null or value_text is not null)
);
create index record_entry_definition_idx on record_entry (definition_id, day);

-- Garmin data is never edited: a wrong value is corrected by an annotation read next to it.
create table activity_annotation (
    id bigserial primary key,
    activity_id bigint not null,
    field text not null,
    value text,
    note text,
    source text not null default 'athlete' check (source in ('athlete', 'agent')),
    created_at timestamptz not null default now(),
    check (value is not null or note is not null)
);
create index activity_annotation_activity_idx on activity_annotation (activity_id);

-- A version on every row the coach may change: an operation names the version it read, and a
-- change based on a stale state is refused instead of overwriting a newer one.
create function bump_version() returns trigger
language plpgsql as $$
begin
    new.version := old.version + 1;
    return new;
end
$$;

-- No write by the coach without a trace: checked at commit, whatever the code did. When the
-- connected role or the current one is lifter_write or one of its members (roles.sql), the
-- transaction must hold a change_log row tied to a proposal that quotes the athlete. Both
-- roles are checked, so `set role lifter_write` from the coach's login does not escape it.
-- Direct membership only: a superuser (the local test server's owner) is not the coach.
create function require_trace() returns trigger
language plpgsql as $$
begin
    if exists (
        select from pg_roles u
        where u.rolname in (current_user, session_user)
        and (
            u.rolname = 'lifter_write'
            or exists (
                select from pg_auth_members m join pg_roles g on g.oid = m.roleid
                where g.rolname = 'lifter_write' and m.member = u.oid
            )
        )
    ) and not exists (
        select from change_log c join proposal p on p.id = c.proposal_id
        where c.txid = txid_current() and p.quote is not null
    ) then
        raise exception 'write without a trace on %: the coach changes data only through lifter.operations',
            tg_table_name;
    end if;
    return null;
end
$$;

do $$
declare
    t text;
begin
    foreach t in array array[
        'exercise', 'cycle', 'block', 'training_week', 'planned_session', 'session_part',
        'session_exercise', 'goal', 'goal_milestone', 'athlete_rule', 'feedback', 'athlete',
        'health_issue', 'record_definition', 'record_entry', 'activity_annotation'
    ] loop
        execute format('alter table %I add column version int not null default 1', t);
        execute format(
            'create trigger %I before update on %I for each row execute function bump_version()',
            t || '_version', t
        );
        execute format(
            'create constraint trigger %I after insert or update or delete on %I'
            ' deferrable initially deferred for each row execute function require_trace()',
            t || '_trace', t
        );
    end loop;
end
$$;
