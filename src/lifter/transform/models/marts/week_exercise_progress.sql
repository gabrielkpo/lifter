-- Week-by-week progression of each exercise in the program (the block page of the app):
-- planned and done side by side, warm-ups left out. Repetitions are counted in sets done in
-- reps (sets x reps per set; a line without sets counts as one set); the load is the heaviest
-- of the week; the RIR is averaged over the lines that state one.
select
    w.id as week_id,
    w.block_id,
    w.number as week_number,
    w.start_date as week_start,
    w.phase,
    l.exercise,
    l.category,
    l.pattern,
    l.origin,
    count(*) as lines,
    sum(coalesce(l.sets, 1)) as sets,
    sum(coalesce(l.sets, 1) * l.quantity) filter (where l.unit = 'reps') as reps,
    max(l.load_kg) as top_load_kg,
    round(avg(l.rir), 1) as avg_rir
from {{ ref('session_line') }} l
join {{ source('lifter', 'planned_session') }} p on p.id = l.session_id
join {{ source('lifter', 'training_week') }} w on w.id = p.week_id
where l.part_kind <> 'warmup'
group by w.id, l.exercise, l.category, l.pattern, l.origin
