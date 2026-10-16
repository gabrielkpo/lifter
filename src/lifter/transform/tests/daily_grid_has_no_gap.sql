-- Rolling windows count rows as days: the daily grid must have one row per calendar day.
select min(day) as first_day, max(day) as last_day, count(*) as days
from {{ ref('daily_base') }}
having count(*) > 0 and count(*) <> max(day) - min(day) + 1
