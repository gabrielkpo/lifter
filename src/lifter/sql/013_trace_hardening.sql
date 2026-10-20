-- The trace, hardened (closing audit of 16/10, low findings).
-- 1. The change log is append-only for everyone, the owner included: rows before and after are
--    what `undo` rebuilds from, and the history is kept without limit (owner's decision, N11).
-- 2. The trace check at commit applies to any role that acts with lifter_write's rights, however
--    indirectly (a login role granted lifter_coach, say), not only direct members; the owner,
--    who only administers that role, and a superuser are not the coach.
-- 3. Its tables are named with their schema and the functions pin their search_path.
-- 4. pg_current_xact_id() replaces the deprecated txid_current().

create function refuse_change_log_rewrite() returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    raise exception 'the change log is append-only: % refused', tg_op;
end
$$;

create trigger change_log_append_only
    before update or delete on public.change_log
    for each row execute function refuse_change_log_rewrite();

alter table public.change_log alter column txid set default (pg_current_xact_id()::text::bigint);

create or replace function require_trace() returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    if exists (
        select from pg_catalog.pg_roles u
        where u.rolname in (current_user, session_user)
        and not u.rolsuper
        and pg_catalog.pg_has_role(u.oid, 'lifter_write', 'USAGE')
    ) and not exists (
        select from public.change_log c join public.proposal p on p.id = c.proposal_id
        where c.txid = pg_current_xact_id()::text::bigint and p.status = 'applied'
            and p.quote is not null and p.message_id is not null
    ) then
        raise exception 'write without a trace on %: the coach changes data only through lifter.operations',
            tg_table_name;
    end if;
    return null;
end
$$;

alter function freeze_applied_proposal() set search_path = public, pg_temp;
