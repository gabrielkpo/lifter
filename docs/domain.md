# Domain: calendar, goals, plans, feedback, proposals

What the athlete plans, aims for and reports. Garmin data (see [metrics.md](metrics.md)) says
what happened; this layer says what was intended and how it felt. Tables live in `public`
(migration `006_domain.sql`), views in `analytics` (`views.sql`), code in `src/lifter/domain.py`.

## Tables

| Table | One row per | Key columns |
|---|---|---|
| `goal` | Goal of the athlete | `title`, `kind` (event, performance, volume, health, other), `sport`, `target_date`, `target_value` + `target_unit`, `status` (active, achieved, abandoned) |
| `training_plan` | Training cycle toward a goal | `goal_id`, `phase` (base, build, peak, taper, recovery, transition), `start_date`, `end_date` |
| `planned_session` | Session in the calendar | `day`, `sport` (Garmin type key, e.g. `cycling`), `title`, `intensity` (rest, easy, moderate, hard, race), `target_duration_minutes`, `target_load`, `structure` (steps, JSON), `goal_id`, `plan_id`, `moved_from`, `status` (planned, cancelled), Garmin ids once pushed (step 5) |
| `feedback` | Report after a session, or morning check-in | `day`, `kind` (session, morning), `planned_session_id`, `rpe` (1–10), `fatigue` (1–5), `pain` (0–10) + `pain_location`, `notes` |
| `proposal` | Change proposed by an agent | `kind`, `payload`, `rationale`, `author`, `status`, `result` |

## Who can change what

- **The athlete** acts directly: plan, move or cancel a session, add a goal, a plan or a
  feedback (`lifter session-add`, `session-move`, `session-cancel`, `goal-add`, `feedback`;
  the app later).
- **An agent never writes.** It calls `propose(kind, payload, rationale, author)`. The payload
  is validated against a strict schema (unknown fields refused) before being stored; a
  proposal without a rationale is refused.
- **The athlete decides** (`lifter proposal approve|reject ID`); only an approved proposal is
  applied, by code, once, in one transaction. A proposal that cannot be applied (for example,
  moving a session that no longer exists) is recorded as `failed` with the reason.

```
pending ──approve──► approved ──apply──► applied
   │                     └──apply fails──► failed
   └──reject──► rejected
```

Proposal kinds: `create_session`, `move_session`, `cancel_session`, `create_goal`,
`create_plan`. Writing to Garmin (scheduling the approved sessions) comes with step 5.

## Calendar (`calendar` view)

Everything on the athlete's calendar, one row per item:

| `kind` | `source` | `status` |
|---|---|---|
| `session` | `lifter` | `planned` (today or later), `done` (an activity of the same sport family that day, or matched explicitly), `missed` (day past, no activity), `cancelled` |
| `session` | `garmin` | Workouts scheduled in Garmin Connect but not by Lifter: `planned`, `done` (Garmin marks it completed), `missed` |
| `activity` | `garmin` | `done (unplanned)`: an activity that no planned session claims |
| `event` | `garmin` | `race` or `event` from the Garmin calendar |

Sport families (`sport_family`) let a planned `cycling` session be done by a `road_biking` or
`indoor_cycling` activity: cycling, running, swimming, strength, walking; other types match
only themselves (a `stop_watch` activity has no known sport). Matching pairs the n-th planned
session of a day and family with the n-th activity of that day and family, so one activity
never completes two sessions; cancelled sessions do not claim activities.

## Garmin snapshots

On every sync, Lifter takes a snapshot of Garmin's calendar: scheduled workouts from 4 weeks
before to 4 weeks after today, events and races from 30 days before to a year after, personal
records, and active goals. Only the latest snapshot counts, and an empty answer is stored as
an empty snapshot, so an item removed in Garmin disappears from Lifter too.

| View | From | Columns |
|---|---|---|
| `stg_scheduled_workout` | `get_scheduled_workouts` | `day`, `garmin_schedule_id`, `garmin_workout_id`, `name`, `sport`, `completed`, `training_plan`, `workout_type` |
| `stg_calendar_event` | `get_calendar_events` | `day`, `title`, `is_race`, `primary_event`, `distance_meters`, `goal_time_seconds` |
| `stg_personal_record` | `get_personal_record` | `record_type`, `value`, `raw_value`, `day`, `activity_id` |

Garmin goals are stored raw (their shape varies by goal type) for the agents to read.

Cost: the events snapshot reads Garmin's calendar month by month (13 months, plus one request
per event for its goal time), so each sync makes about 15 to 20 Garmin requests more than the
daily data. Fine for one sync a day; to revisit if syncs become more frequent.

## Privacy note

Activity names from Garmin can contain a place (the default name of a timed activity is the
town where it started). They stay in the local database; the agents' context must not include
them (step 3).
