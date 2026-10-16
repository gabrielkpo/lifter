-- The heaviest logged set of each exercise on each day (sets done in reps with a load), with
-- its reps: the progression curve of a movement in the app's PR tab.
select distinct on (l.exercise, p.day)
    l.exercise,
    p.day,
    l.session_id,
    l.load_kg as top_load_kg,
    l.quantity as reps,
    l.sets
from {{ ref('session_line') }} l
join {{ source('lifter', 'planned_session') }} p on p.id = l.session_id
where l.origin = 'done' and l.unit = 'reps' and l.load_kg is not null
order by l.exercise, p.day, l.load_kg desc, l.quantity desc
