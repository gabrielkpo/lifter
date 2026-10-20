-- Best load per exercise and repetition count: the sets logged (done in reps with a load) and
-- the lift records the athlete declared.
select distinct on (b.exercise, b.reps)
    b.exercise,
    b.reps,
    b.load_kg as best_load_kg,
    b.day
from (
    select l.exercise, l.quantity as reps, l.load_kg, p.day
    from {{ ref('session_line') }} l
    join {{ source('lifter', 'planned_session') }} p on p.id = l.session_id
    where l.origin = 'done' and l.unit = 'reps' and l.load_kg is not null and l.quantity is not null
    union all
    select exercise, reps, load_kg, day from {{ ref('lift_record') }}
) b
order by b.exercise, b.reps, b.load_kg desc, b.day
