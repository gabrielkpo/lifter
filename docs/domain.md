# Domain: the CrossFit cycle, sessions, exercises, goals, proposals

What the athlete plans, does and aims for. Garmin data (see [metrics.md](metrics.md)) says how
the body responded; this layer says what was prescribed, what was done and how it felt.
Tables live in `public` (migration `006_domain.sql`), views in `analytics` (dbt models in
`src/lifter/transform/models/`),
code in `src/lifter/domain.py` and `src/lifter/program.py`.

Lifter coaches CrossFit only, with one method:

- **A cycle of about three months, in three blocks**: accumulation (volume), transmutation
  (maximal strength), realisation (express it, then test). Each week has a phase (reference,
  volume, deload, strength peak, test…) and an intent for each part of the sessions.
- **A block is counted in strength sessions done, not in weeks.** It moves on when the count
  is reached, the loads progressed and nothing (pain, swelling) is unresolved.
- **Every session has the same frame**: warm-up, weightlifting or gymnastics while fresh,
  strength, then the metcon. Cardio and mobility days have their own parts.
- **Every movement is prescribed** as sets x quantity at a load, with a target RIR
  (repetitions in reserve) and a rest. The RIR is the instruction, the load a guide.
- **A metcon has a target, never a time cap**: a time to beat (For Time) or rounds to reach
  (AMRAP).
- **The week is programmed every weekend** from the review of the past week (sessions done or
  skipped, real loads and RIR, notes, pain, patterns not trained) and from the week's phase.
  That review is what the week planner agent will start from (step 3).

## Tables

| Table | One row per | Key columns |
|---|---|---|
| `exercise` | Movement of the bank | `name`, `category` (weightlifting, gymnastics, strength, monostructural, mobility), `pattern` (olympic, push, pull, legs, hinge, core, carry, engine, full_body, mobility), `equipment`, `flags` (e.g. `running`, `impact`, `free_barbell_legs`, for the athlete's rules) |
| `cycle` | Training cycle | `name`, `start_date`, `end_date`, `notes`, `status` |
| `block` | Block of a cycle | `position`, `kind` (accumulation, transmutation, realisation), dates, `intent`, `target_strength_sessions` |
| `training_week` | Week of a cycle | `number` (0 for an entry week outside any block), `block_id`, `start_date`, `phase`, `intent` (JSON: weightlifting, push, pull, legs, metcon, notes), `review` |
| `planned_session` | Session in the calendar | `day`, `title`, `kind` (training, cardio, mobility, rest), `week_id`, `notes`, `deviation` (gap with the plan, in words), `status` (planned, cancelled), `source` (program, athlete, agent), `moved_from`, `matched_activity_id` |
| `session_part` | Part of a session, in order | `position`, `kind` (warmup, weightlifting, gymnastics, strength, metcon, cardio, mobility); for a metcon: `format` (for_time, amrap, emom, every_n, rounds, intervals), `duration_minutes`, `rounds`, `interval_seconds`, `target_seconds` or `target_rounds`, and once done `result_seconds`, `result_rounds`, `result_notes` |
| `session_exercise` | Exercise line of a part | `origin` (`planned` or `done`), `exercise_id`, `sets`, `quantity` + `unit` (reps, cal, m, s, min), `load_kg` (+ `load_kg_max` for a range), `rir`, `rest_seconds`, `notes` |
| `goal` | Goal | `kind` (strength, skill, benchmark), `exercise_id`, `unit`, baseline and target (a value or a text, e.g. "first rep without a band"), `target_date`, `source` |
| `goal_milestone` | Dated step toward a goal | `day`, `label` (e.g. end of block 1), `value` or `value_text` |
| `athlete_rule` | Permanent rule of the athlete | `code` (a rule the guardrail will check in code, step 3), `text`, `params` |
| `feedback` | Report after a session, or morning check-in | `rpe` (1–10), `fatigue` (1–5), `pain` (0–10) + `pain_location`, `notes` |
| `proposal` | Change proposed by an agent | `kind`, `payload`, `rationale`, `author`, `status`, `result` |

Planned and done lines share one shape, so the gap between plan and log is a comparison of
rows: the session of the 2nd may prescribe `Bench press 4x8 @ 60 kg RIR 2` and log
`Bench press 4x8 @ 62.5 kg RIR 1`.

## The program file

Until the app exists, a YAML file is how a program gets in: `lifter program load FILE`.
[`examples/program.yaml`](../examples/program.yaml) is a synthetic program with every field;
a real one stays in `data/`, which Git ignores. The file is validated before anything is
written: unknown fields are refused (a metcon has no `time_cap`), every exercise must be in
the bank, every week in a declared block. Loading is all or nothing, and refuses a database
that already holds a program unless `--replace` is given, which first deletes what the previous
program file created (its cycle, sessions and goals, and the rules); sessions and goals added by
the athlete or by approved proposals are kept, without their week, and the exercise bank is
updated in place. `history` holds sessions
done before the cycle, outside any week.

## Who can change what

- **The athlete** acts directly: load a program, add, move or cancel a session, add a goal or
  a feedback (`lifter program load`, `session-add`, `session-move`, `session-cancel`,
  `goal-add`, `feedback`; the app later).
- **An agent never writes.** It calls `propose(kind, payload, rationale, author)`. The payload
  is validated against a strict schema (unknown fields refused) before being stored; a
  proposal without a rationale is refused.
- **The athlete decides** (`lifter proposal approve|reject ID`); only an approved proposal is
  applied, by code, once, in one transaction. A proposal that cannot be applied (an exercise
  not in the bank, a session that no longer exists) is recorded as `failed` with the reason.

```
pending ──approve──► approved ──apply──► applied
   │                     └──apply fails──► failed
   └──reject──► rejected
```

Proposal kinds: `create_session` (a whole session, with its parts and lines),
`move_session`, `cancel_session`, `create_goal`.

## Views

| View | What it gives |
|---|---|
| `session_activity` | Which Garmin activities belong to which session (rule below) |
| `session_garmin` | The Garmin line of a session: activities, minutes, average and max heart rate, calories, load, minutes in zones 4-5 |
| `planned_session_status` | Status of each session: `done`, `missed`, `planned`, `cancelled`, `rest` |
| `calendar` | Lifter sessions, workouts scheduled in Garmin Connect, and activities that belong to no session |
| `session_line` | Exercise lines with their exercise, category and pattern |
| `week_summary` | The review of a week: sessions, done, missed, cancelled, strength sessions done (done sessions with a strength part), patterns trained |
| `block_progress` | Strength sessions done in each block against its target |
| `exercise_best` | Best logged load per exercise and repetition count |
| `week_exercise_progress` | Per week and exercise, planned and done (warm-ups left out): lines, sets, repetitions (sets × reps, lines in reps only; no sets counts as one), heaviest load, average RIR of the lines that state one. Feeds the block page of the app |
| `exercise_history` | The heaviest logged set of each exercise on each day (sets in reps with a load), with its reps and sets: the progression curve of a movement |

**Done or missed.** A session is `done` when a Garmin activity belongs to it, or when it was
logged (a done line, a metcon result, or a feedback), since the watch is not always worn.
Past without either, it is `missed`.

**Matching activities.** Only training activities can complete a session (`hiit`,
`strength_training`, `stop_watch`, `indoor_cardio`, ergs, `yoga`…); a bike commute or a walk
counts in the training load but never completes a session. On each day, the n-th training
activity goes to the n-th open session; extra activities go to the day's last session, since
one session is often recorded in two parts (strength, then the metcon). Mobility sessions,
rarely recorded, take an activity only on a day without another open session. An activity
never belongs to two sessions, and cancelled or rest sessions take none.

## Garmin calendar

On every sync, Lifter takes a snapshot of the workouts scheduled in Garmin Connect, from 4
weeks before to 4 weeks after today (`stg_scheduled_workout`: `day`, `garmin_schedule_id`,
`garmin_workout_id`, `name`, `sport`, `completed`). Only the latest snapshot counts, and an
empty answer is stored as an empty snapshot, so a workout removed in Garmin disappears from
Lifter too.

## Privacy note

The athlete's program, rules, notes and pain reports are health data: they stay in the local
database and in `data/`. Activity names from Garmin can contain a place (the default name of an
activity is the town where it started); the agents' context must not include them (step 3).

## Roles (who may do what)

Defined in `src/lifter/sql/roles.sql`, applied by `lifter migrate` (and again whenever the views
are recreated, since that drops their grants). Group roles carry the privileges; login roles only
inherit them and hold nothing of their own. Passwords never live in the repository.

| Login role | Inherits | Can | Cannot |
|---|---|---|---|
| `lifter_api` | `lifter_read` | read every table and view (read-only transactions, 10 s per statement) | write anything |
| `lifter_sync` | `lifter_ingest` | read and write the raw Garmin layer (`raw_garmin_payload`, `sync_log`, `activity_tombstone`), read the staging views it reconciles with | read or write the program, the log, goals, proposals or metrics |
| `lifter_agents` | `lifter_read`, `lifter_propose` | read everything, insert proposals and the audit of their runs | decide or apply a proposal, change the program |
| `lifter_backup` | `lifter_read` | read everything, sequences included (`pg_dump`), read-only transactions, one connection | write anything |

No role may create objects; only the owner runs migrations. `tests/test_roles.py` checks the
whole matrix and runs a sync as `lifter_sync` and a proposal as `lifter_agents`.

