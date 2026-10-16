-- The trace of an applied change cannot be rewritten (audit of 16/10, N6). The coach's role
-- updates a proposal once, when it applies a pending suggestion (quote, message, key, result);
-- after that, the quote that authorised the change and what it did are fixed. Only `undone_by`
-- may still be set, by the undo that reverts it.
create function freeze_applied_proposal() returns trigger
language plpgsql as $$
begin
    if (new.kind, new.payload, new.status, new.quote, new.message_id, new.idempotency_key,
        new.result, new.author, new.rationale, new.applied_at)
       is distinct from
       (old.kind, old.payload, old.status, old.quote, old.message_id, old.idempotency_key,
        old.result, old.author, old.rationale, old.applied_at) then
        raise exception 'proposal % was applied: its trace cannot change', old.id;
    end if;
    return new;
end
$$;

create trigger proposal_applied_is_final
    before update on proposal
    for each row when (old.status = 'applied')
    execute function freeze_applied_proposal();

-- The trace a coach's write needs at commit is an applied proposal quoting a message: a pending
-- suggestion given a quote by hand no longer counts.
create or replace function require_trace() returns trigger
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
        where c.txid = txid_current() and p.status = 'applied' and p.quote is not null
            and p.message_id is not null
    ) then
        raise exception 'write without a trace on %: the coach changes data only through lifter.operations',
            tg_table_name;
    end if;
    return null;
end
$$;
