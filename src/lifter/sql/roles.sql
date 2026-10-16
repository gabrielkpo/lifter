-- Who may do what in the Lifter database (RBAC), as code. Repeatable: `lifter migrate` applies it
-- when this file changes and every time the analytics layer (dbt) is rebuilt, because recreating
-- the analytics views drops the grants on them. Run by the owner, who needs CREATEROLE.
--
-- Group roles (NOLOGIN) carry the privileges; login roles carry none of their own and only
-- inherit them. No password here: login roles are created without one and their password is
-- set outside the repository (Vercel and the Mac's environment). Matrix tested in
-- tests/test_roles.py; any change here changes that test.
--
--   lifter_read     read everything the app and the agents read (public, analytics)
--   lifter_ingest   the Garmin sync: write the raw layer only
--   lifter_propose  the agents: record proposals and their runs, never decide nor apply
--   lifter_write    the coach's write path (lifter.operations): the domain tables, the trace,
--                   the coach's messages; a write without a trace fails at commit (009)
--   lifter_converse the conversation endpoint: store the athlete's messages
--
--   lifter_api      = lifter_read, read-only transactions
--   lifter_sync     = lifter_ingest
--   lifter_agents   = lifter_read + lifter_propose
--   lifter_backup   = lifter_read (pg_dump of the hosted database, read-only transactions)
--   lifter_coach    = lifter_read + lifter_propose + lifter_write (the hosted coach)
--   lifter_chat     = lifter_read + lifter_converse (the conversation endpoint)

do $$
declare
    name text;
begin
    foreach name in array array[
        'lifter_read', 'lifter_ingest', 'lifter_propose', 'lifter_write', 'lifter_converse'
    ] loop
        if not exists (select from pg_roles where rolname = name) then
            execute format('create role %I nologin', name);
        end if;
    end loop;
    foreach name in array array[
        'lifter_api', 'lifter_sync', 'lifter_agents', 'lifter_backup', 'lifter_coach', 'lifter_chat'
    ] loop
        if not exists (select from pg_roles where rolname = name) then
            execute format('create role %I login', name);
        end if;
    end loop;
    -- Nobody connects or creates objects by default: only the owner and the roles below.
    execute format('revoke all on database %I from public', current_database());
    execute format(
        'grant connect on database %I to lifter_read, lifter_ingest, lifter_propose,'
        ' lifter_write, lifter_converse',
        current_database()
    );
end
$$;

revoke all on schema public from public;

-- Login roles inherit, they hold nothing directly (also clears grants made before this file).
revoke all on all tables in schema public, analytics from lifter_api, lifter_sync, lifter_agents, lifter_backup, lifter_coach,
    lifter_chat;
revoke all on all sequences in schema public from lifter_api, lifter_sync, lifter_agents, lifter_backup, lifter_coach,
    lifter_chat;
alter default privileges revoke all on tables from lifter_api, lifter_sync, lifter_agents, lifter_backup, lifter_coach,
    lifter_chat;
alter default privileges revoke all on schemas from lifter_api, lifter_sync, lifter_agents, lifter_backup, lifter_coach,
    lifter_chat;

-- lifter_read: every table and view, now and as the owner creates them later.
grant usage on schema public, analytics to lifter_read;
grant select on all tables in schema public, analytics to lifter_read;
-- Sequence values too, which a dump records (pg_dump reads them).
grant select on all sequences in schema public to lifter_read;
alter default privileges grant select on tables to lifter_read;
alter default privileges grant select on sequences to lifter_read;
alter default privileges grant usage on schemas to lifter_read;

-- lifter_ingest: what lifter.sync reads and writes, nothing else. The staging views run with
-- their owner's rights, so reading them does not open the tables behind them.
grant usage on schema public, analytics to lifter_ingest;
grant select, insert, update on raw_garmin_payload, sync_log to lifter_ingest;
grant select, insert, delete on activity_tombstone to lifter_ingest;
grant usage on sequence raw_garmin_payload_id_seq, sync_log_id_seq to lifter_ingest;
grant select on analytics.latest_garmin_payload, analytics.stg_activity,
    analytics.stg_activity_listed to lifter_ingest;
-- To check, read-only, that the schema is up to date before syncing (lifter.db.ensure_schema).
grant select on schema_migrations, schema_views to lifter_ingest;

-- lifter_propose: append proposals and the audit of the runs that made them.
grant usage on schema public to lifter_propose;
grant insert on proposal, agent_run, agent_step to lifter_propose;
grant usage on sequence proposal_id_seq, agent_run_id_seq, agent_step_id_seq to lifter_propose;

-- lifter_write: what lifter.operations writes, nothing else: the domain tables (insert, update,
-- delete), the trace (append only: change_log is never updated nor deleted), the status and
-- trace columns of a proposal, and the coach's own messages (row-level policy below).
grant usage on schema public to lifter_write;
grant select, insert, update, delete on exercise, cycle, block, training_week, planned_session,
    session_part, session_exercise, goal, goal_milestone, athlete_rule, feedback, athlete,
    health_issue, record_definition, record_entry, activity_annotation to lifter_write;
grant usage on sequence exercise_id_seq, cycle_id_seq, block_id_seq, training_week_id_seq,
    planned_session_id_seq, session_part_id_seq, session_exercise_id_seq, goal_id_seq,
    goal_milestone_id_seq, athlete_rule_id_seq, feedback_id_seq, health_issue_id_seq,
    record_definition_id_seq, record_entry_id_seq, activity_annotation_id_seq to lifter_write;
grant insert on change_log, proposal to lifter_write;
grant update (status, decided_at, applied_at, result, quote, message_id, idempotency_key, undone_by)
    on proposal to lifter_write;
grant usage on sequence change_log_id_seq, proposal_id_seq to lifter_write;
grant insert on conversation_message to lifter_write;
grant usage on sequence conversation_message_id_seq to lifter_write;

-- lifter_converse: the athlete's messages, stored before the model runs (row-level policy).
grant usage on schema public to lifter_converse;
grant insert on conversation_message to lifter_converse;
grant usage on sequence conversation_message_id_seq to lifter_converse;

-- Who may write which messages: the athlete's words come from the conversation endpoint only,
-- so the coach can never write a message the quote check would read as the athlete's.
alter table conversation_message enable row level security;
drop policy if exists read_messages on conversation_message;
drop policy if exists coach_messages on conversation_message;
drop policy if exists athlete_messages on conversation_message;
create policy read_messages on conversation_message for select to lifter_read using (true);
create policy coach_messages on conversation_message for insert to lifter_write
    with check (role = 'coach');
create policy athlete_messages on conversation_message for insert to lifter_converse
    with check (role = 'athlete');

-- Login roles: membership, then per-role guards.
grant lifter_read to lifter_api;
grant lifter_ingest to lifter_sync;
grant lifter_read, lifter_propose to lifter_agents;
grant lifter_read to lifter_backup;
grant lifter_read, lifter_propose, lifter_write to lifter_coach;
grant lifter_read, lifter_converse to lifter_chat;
alter role lifter_api set default_transaction_read_only = on;
alter role lifter_api set statement_timeout = '10s';
alter role lifter_sync set statement_timeout = '60s';
alter role lifter_agents set statement_timeout = '30s';
alter role lifter_backup set default_transaction_read_only = on;
alter role lifter_backup set statement_timeout = '300s';
alter role lifter_api connection limit 20;
alter role lifter_sync connection limit 2;
alter role lifter_agents connection limit 5;
alter role lifter_backup connection limit 1;
alter role lifter_coach set statement_timeout = '30s';
alter role lifter_chat set statement_timeout = '10s';
alter role lifter_coach connection limit 5;
alter role lifter_chat connection limit 5;
