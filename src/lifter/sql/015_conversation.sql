-- Several conversations with the coach (framing validated by the owner on 19/10, brain
-- projets/cadrage-lifter-discussions): each has its own row, the app lists them and resumes any.
-- A message belongs to a conversation that exists: a mistyped id is refused instead of starting
-- a conversation nobody listed. Nothing is ever deleted: the trace of every change points to the
-- message that authorised it.

create table conversation (
    -- Drawn by the server (lifter.conversation.start); "main", "bench" and the ids given to
    -- `lifter chat --conversation` stay valid.
    id text primary key default gen_random_uuid()::text
        check (id ~ '^[A-Za-z0-9_-]{1,64}$'),
    -- The start of the athlete's first message, as the conversation's name in the list.
    title text not null check (length(title) between 1 and 80),
    source text not null check (source in ('app', 'cli', 'bench')),
    created_at timestamptz not null default now(),
    last_message_at timestamptz not null default now()
);
create index conversation_recent_idx on conversation (last_message_at desc, id desc);

-- The conversations so far: named after their first athlete message, dated by their messages.
insert into conversation (id, title, source, created_at, last_message_at)
select
    m.conversation_id,
    coalesce(
        (
            select nullif(left(regexp_replace(btrim(f.text), '\s+', ' ', 'g'), 80), '')
            from conversation_message f
            where f.conversation_id = m.conversation_id and f.role = 'athlete'
            order by f.id limit 1
        ),
        m.conversation_id
    ),
    case m.conversation_id when 'main' then 'app' when 'bench' then 'bench' else 'cli' end,
    min(m.created_at),
    max(m.created_at)
from conversation_message m
group by m.conversation_id;

alter table conversation_message
    add constraint conversation_message_conversation_fk
    foreign key (conversation_id) references conversation (id);

-- Its last activity follows its messages, whoever writes them (the endpoint, the coach, the
-- terminal, the bench): none of them has to think of it, nor holds the right to change it.
create function touch_conversation() returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.conversation set last_message_at = greatest(last_message_at, new.created_at)
    where id = new.conversation_id;
    return null;
end
$$;

create trigger conversation_message_touch
    after insert on public.conversation_message
    for each row execute function touch_conversation();
