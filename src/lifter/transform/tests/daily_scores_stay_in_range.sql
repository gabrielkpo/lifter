-- Recovery scores and their components are bounded (docs/metrics.md); the ratio is never negative.
select day, recovery_score, recovery_7d_avg, acwr
from {{ ref('daily_metrics') }}
where recovery_score not between 0 and 100
    or recovery_7d_avg not between 0 and 100
    or acwr < 0
