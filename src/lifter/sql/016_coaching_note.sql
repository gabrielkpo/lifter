-- The athlete's method as data (framing of the agents team, validated by the owner on 20/10,
-- brain projets/cadrage-lifter-equipe-agents): what lived in Notion's appendix (weekly frame,
-- block count, rules not coded, load progression, warm-up, what would invalidate the plan) and
-- what the athlete says about how he trains, for good or for a while. The coach and the
-- planners read the notes valid on the day they plan; the coach writes them through
-- lifter.operations (quoted, traced, undone like any change).
create table coaching_note (
    id bigserial primary key,
    title text not null check (length(btrim(title)) between 1 and 120),
    text text not null check (length(btrim(text)) >= 1),
    category text not null default 'method'
        check (category in ('method', 'preference', 'constraint', 'context')),
    -- Open on either side: a permanent note has neither.
    valid_from date,
    valid_until date,
    position int not null default 1 check (position >= 1),
    created_at timestamptz not null default now(),
    version int not null default 1,
    check (valid_from is null or valid_until is null or valid_until >= valid_from)
);
create index coaching_note_order_idx on coaching_note (category, position, id);

create trigger coaching_note_version before update on coaching_note
    for each row execute function bump_version();
create constraint trigger coaching_note_trace after insert or update or delete on coaching_note
    deferrable initially deferred for each row execute function require_trace();
