-- The sync's own "today" when it logged a call: a "no data" answer for a day is final only if
-- it came more than the refetch window after that day (see lifter.sync.is_known).
alter table sync_log add column if not exists as_of date;
