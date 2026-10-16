-- How long the agents' audit keeps what the model saw and said (ADR 0002, Security notes): the
-- full context 90 days, then the metrics only. The context and the plans hold the athlete's
-- training and health details; warnings and violation messages can name a pain ("pain 5/10
-- (knee)"). After 90 days a run keeps who ran, when, how (model, tokens, seconds, attempts),
-- how it ended (status, error type and message, proposals) and which rules it broke, by name.

alter table agent_run add column purged_at timestamptz;

-- Runs whose context is purged, so a reader says "purged" rather than "did not parse".
comment on column agent_run.purged_at is
    'When the context, plans and messages of this run were purged (90 days, ADR 0002).';

-- Fixed rule, run with the owner's rights: the scheduled sync calls it (roles.sql grants it to
-- lifter_ingest), which may neither read nor change the audit itself. Returns the runs purged.
create function purge_agent_audit() returns int
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    purged int;
begin
    with old as (
        select id from agent_run
        where purged_at is null and started_at < now() - interval '90 days'
        for update
    ), steps as (
        update agent_step s
        set plan = null,
            violations = coalesce(
                (select jsonb_agg(jsonb_build_object('check', v -> 'check'))
                 from jsonb_array_elements(s.violations) v),
                '[]'
            )
        where s.run_id in (select id from old)
    )
    update agent_run r
    set context = null, plan = null, warnings = '[]', purged_at = now()
    where r.id in (select id from old);
    get diagnostics purged = row_count;
    return purged;
end
$$;

revoke all on function purge_agent_audit() from public;
