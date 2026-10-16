-- Planned sessions with their outcome: "done" when a Garmin activity belongs to the session or
-- when it was logged (exercises done, a metcon result, or a session feedback), since the
-- watch is not always worn; "missed" once the day is past without either; "cancelled" when the
-- athlete or an approved proposal cancelled it.
with logged as (
    select sp.session_id as id
    from {{ source('lifter', 'session_part') }} sp
    where sp.result_seconds is not null or sp.result_rounds is not null
        or exists (
            select 1 from {{ source('lifter', 'session_exercise') }} se where se.part_id = sp.id and se.origin = 'done'
        )
    union
    select planned_session_id from {{ source('lifter', 'feedback') }} where planned_session_id is not null
)
select
    p.id as planned_session_id,
    p.day,
    p.title,
    p.kind,
    p.week_id,
    p.moved_from,
    g.activities,
    p.id in (select id from logged) as logged,
    case
        when p.status = 'cancelled' then 'cancelled'
        when p.kind = 'rest' then 'rest'
        when g.activities is not null or p.id in (select id from logged) then 'done'
        when p.day < current_date then 'missed'
        else 'planned'
    end as status
from {{ source('lifter', 'planned_session') }} p
left join {{ ref('session_garmin') }} g on g.planned_session_id = p.id
