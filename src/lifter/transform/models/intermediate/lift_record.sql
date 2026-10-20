-- The lift records the athlete declared (to the coach, or in the app later): a load in kg for a
-- number of repetitions, a max load counting as one. Named after the exercise of the bank they
-- belong to, by link or by name, so they meet the logged sets of the same movement.
select
    coalesce(linked.name, named.name, d.name) as exercise,
    coalesce(r.reps, 1)::numeric as reps,
    r.value as load_kg,
    r.day
from {{ source('lifter', 'record_entry') }} r
join {{ source('lifter', 'record_definition') }} d on d.id = r.definition_id
left join {{ source('lifter', 'exercise') }} linked on linked.id = d.exercise_id
left join {{ source('lifter', 'exercise') }} named on lower(named.name) = lower(d.name)
where d.kind = 'lift'
    and d.record_type in ('rep_max', 'max_load')
    and lower(coalesce(d.unit, 'kg')) = 'kg'
    and r.value is not null
