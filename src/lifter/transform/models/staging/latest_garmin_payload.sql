-- Staging layer: typed columns read from the latest payload of each key.
select distinct on (tool, natural_key)
    tool, natural_key, payload, last_seen_at
from {{ source('lifter', 'raw_garmin_payload') }}
order by tool, natural_key, last_seen_at desc, id desc
