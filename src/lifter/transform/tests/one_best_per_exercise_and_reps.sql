-- A record is unique per exercise and repetition count.
select exercise, reps, count(*) as rows
from {{ ref('exercise_best') }}
group by exercise, reps
having count(*) > 1
