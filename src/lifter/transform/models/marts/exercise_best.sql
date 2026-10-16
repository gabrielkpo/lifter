-- Best logged load per exercise and repetition count (sets done in reps with a load).
select distinct on (l.exercise, l.quantity)
    l.exercise,
    l.quantity as reps,
    l.load_kg as best_load_kg,
    p.day
from {{ ref('session_line') }} l
join {{ source('lifter', 'planned_session') }} p on p.id = l.session_id
where l.origin = 'done' and l.unit = 'reps' and l.load_kg is not null and l.quantity is not null
order by l.exercise, l.quantity, l.load_kg desc, p.day
