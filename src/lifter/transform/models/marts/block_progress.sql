-- Progress of each block: it ends when its strength-session count is reached.
select
    b.id as block_id,
    b.cycle_id,
    b.position,
    b.kind,
    b.start_date,
    b.end_date,
    b.target_strength_sessions,
    coalesce(sum(ws.strength_sessions_done), 0) as strength_sessions_done
from {{ source('lifter', 'block') }} b
left join {{ ref('week_summary') }} ws on ws.block_id = b.id
group by b.id
