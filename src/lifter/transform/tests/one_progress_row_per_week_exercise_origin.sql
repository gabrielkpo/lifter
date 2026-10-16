-- The block curves read one row per week, exercise and origin (planned or done).
select week_id, exercise, origin, count(*) as rows
from {{ ref('week_exercise_progress') }}
group by week_id, exercise, origin
having count(*) > 1
