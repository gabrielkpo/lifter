-- The staging layer reads one payload per Garmin tool and key: the latest one.
select tool, natural_key, count(*) as rows
from {{ ref('latest_garmin_payload') }}
group by tool, natural_key
having count(*) > 1
