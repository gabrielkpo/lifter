-- A week never counts more sessions done than it has, nor more strength sessions than done.
select week_id, sessions, done, strength_sessions_done
from {{ ref('week_summary') }}
where done > sessions or strength_sessions_done > done
