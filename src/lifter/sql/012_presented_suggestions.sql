-- A suggestion is accepted only from the coach message that showed it (audit N7, owner's
-- decision of 17/10): no lifetime; an "ok" picks what the coach's latest message presented, and
-- a suggestion shown earlier and not shown again expires (lifter.operations.present).
alter table proposal add column presented_in bigint references conversation_message (id);

comment on column proposal.presented_in is
    'The coach message that last presented this suggestion; only the athlete''s next message can accept it.';
