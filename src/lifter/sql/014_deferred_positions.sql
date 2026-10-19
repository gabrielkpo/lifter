-- Positions are unique within their parent, checked at commit rather than at each statement
-- (19/10: the coach could not undo the parts it had added). Inserting a part moves the ones
-- after it down; undoing that moves them back while the inserted part is still there, so the
-- order of the statements briefly holds two parts at one position. The final state is checked
-- the same: at commit, positions are still unique.
alter table session_part drop constraint session_part_session_id_position_key;
alter table session_part add constraint session_part_session_id_position_key
    unique (session_id, position) deferrable initially deferred;

alter table session_exercise drop constraint session_exercise_part_id_origin_position_key;
alter table session_exercise add constraint session_exercise_part_id_origin_position_key
    unique (part_id, origin, position) deferrable initially deferred;

alter table block drop constraint block_cycle_id_position_key;
alter table block add constraint block_cycle_id_position_key
    unique (cycle_id, position) deferrable initially deferred;
