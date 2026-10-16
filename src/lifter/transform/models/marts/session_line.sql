-- Exercise lines with their exercise, for reading a session or a week.
select
    sp.session_id,
    sp.position as part_position,
    sp.kind as part_kind,
    se.origin,
    se.position,
    e.name as exercise,
    e.category,
    e.pattern,
    se.sets,
    se.quantity,
    se.unit,
    se.load_kg,
    se.load_kg_max,
    se.rir,
    se.rest_seconds,
    se.notes
from {{ source('lifter', 'session_exercise') }} se
join {{ source('lifter', 'session_part') }} sp on sp.id = se.part_id
join {{ source('lifter', 'exercise') }} e on e.id = se.exercise_id
