-- The heaviest set of each exercise on each day, with its reps: the sets logged (done in reps
-- with a load) and the lift records the athlete declared (no session: a record stands alone).
-- The progression curve of a movement in the app's PR tab.
select distinct on (h.exercise, h.day)
    h.exercise,
    h.day,
    h.session_id,
    h.top_load_kg,
    h.reps,
    h.sets
from (
    select l.exercise, p.day, l.session_id, l.load_kg as top_load_kg, l.quantity as reps, l.sets
    from {{ ref('session_line') }} l
    join {{ source('lifter', 'planned_session') }} p on p.id = l.session_id
    where l.origin = 'done' and l.unit = 'reps' and l.load_kg is not null
    union all
    select exercise, day, null::bigint, load_kg, reps, 1 from {{ ref('lift_record') }}
) h
order by h.exercise, h.day, h.top_load_kg desc, h.reps desc
