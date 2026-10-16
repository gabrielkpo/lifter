-- The review of each week, what the weekly programming starts from: sessions planned, done,
-- missed and cancelled, strength sessions done (done sessions with a strength part: they count
-- toward the block), and the movement patterns actually trained.
select
    w.id as week_id,
    w.block_id,
    w.number,
    w.start_date,
    w.phase,
    b.kind as block,
    count(s.planned_session_id) filter (where s.status <> 'rest') as sessions,
    count(*) filter (where s.status = 'done') as done,
    count(*) filter (where s.status = 'missed') as missed,
    count(*) filter (where s.status = 'cancelled') as cancelled,
    count(*) filter (
        where s.status = 'done' and exists (
            select 1 from {{ source('lifter', 'session_part') }} sp
            where sp.session_id = s.planned_session_id and sp.kind = 'strength'
        )
    ) as strength_sessions_done,
    (
        select array_agg(distinct l.pattern order by l.pattern)
        from {{ ref('session_line') }} l
        join {{ source('lifter', 'planned_session') }} p on p.id = l.session_id
        where p.week_id = w.id and l.origin = 'done' and l.part_kind <> 'warmup'
    ) as patterns_done
from {{ source('lifter', 'training_week') }} w
left join {{ source('lifter', 'block') }} b on b.id = w.block_id
left join {{ ref('planned_session_status') }} s on s.week_id = w.id
group by w.id, b.kind
