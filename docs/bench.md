# Evaluation bench

The bench measures a week planner on situations whose expected outcome was **written before
any run** against a model. It answers two questions: is the agent better than a plan without a
model, and (step 7) is the agent team better than a single agent?

## The athlete and the scenarios

- **Synthetic athlete** (`src/lifter/bench/athlete.py`): a 12-week CrossFit cycle in three
  blocks, built by code. Weeks 1 to 5 have their sessions planned (push, cardio, pull, legs,
  benchmark WOD; week 4 is a deload), weeks 6 to 12 only their phase. The same rules as a real
  athlete (no running, no free barbell on the legs, legs every week, one load step at most…).
  Dates are in January to March 2026, so statuses never depend on the day the bench runs.
- **21 scenarios** (`bench/scenarios/*.yaml`), each with a situation, machine-checked
  expectations, and a `review` describing a good plan for the hand grading (1 to 5).

| Category | Scenarios |
|---|---|
| Phase | volume peak, deload, after the deload, intensification with the benchmark, power week after unlogged weeks, test week, first week without history |
| Review of the past week | legs skipped, pull and legs skipped, whole week missed, bench RIR missed, bench too easy, a week logged without RIR |
| Health | knee pain 5/10 (stop rule), knee pain 2/10 (no over-caution), low recovery, critical alerts, short sleep, load spike |
| Calendar | drafts already planned (no duplicates), drafts with a critical alert (cancel the hard ones) |

A scenario's setup starts from the base program, logs the weeks before the target as planned,
then skips sessions, changes logged lines, adds feedback, overrides the target week's phase,
and generates 35 days of synthetic Garmin data with a recovery profile (`normal`, `low`,
`critical`, `short_sleep`, `overload`). The athlete programs on the Sunday before the target
week.

## What is measured

Per scenario and per run (the model's answers vary: `--runs 3` measures the spread):

| Measure | Meaning |
|---|---|
| accepted | The guardrail accepted the final plan (at most 3 attempts) |
| first-plan violations | Rule violations of the model's first answer, before any correction: the constraint-violation count of the decision rule |
| schema failures | Answers that did not even parse as a plan, over all attempts (counted apart from rule violations) |
| unsourced numbers | Numbers cited in a summary or a rationale that exist nowhere in the context, over all attempts |
| expectations met | Machine-checked expectations of the scenario (`src/lifter/bench/expect.py`) |
| tokens, seconds | Cost and latency, from the model's usage metadata |

Hand grading (1 to 5 per scenario, against its `review`) completes it for plan quality.

## Baselines and decision rule

- **Copy last week** (`--planner copy`): the previous week shifted by seven days, no model. It
  ignores phase, recovery and feedback on purpose: the floor every agent must beat. Result on
  the 21 scenarios: 71 % accepted, **66 % of expectations met**
  (`bench/results/copy-baseline.json`); it fails the deload, the return after it, the stop rule,
  low recovery, critical alerts and duplicates the drafts.
- **Single agent** (`--planner mistral`): the week planner of step 3, `mistral-small-latest`,
  **5 runs per scenario** (`bench/results/single-agent-mistral-small.json`, 105 plans):
  **87.6 % accepted, 79.7 % of expectations met**, 129 first-plan violations, 28 left in final
  plans, 8 answers that did not parse, 6 unsourced numbers, about 1.7 million tokens. Above the
  floor on both measures; the skipped sessions, a missed RIR, a load spike and the return after
  the deload are solid. Still weak: the deload (always accepted, never fully met: volume and
  metcon count), the intensification and test weeks (low reps, the AMRAP benchmark), light pain
  read as a reason to lower the load (`light_pain_ignored`, 0/5), the light first days after low
  recovery (1/5), and the power week (3/5 accepted).
- **Round 3** (2026-10-19). Two rules added, the only ones that held across the trial passes:
  a missed set (fewer reps, or a RIR under its target) keeps the load or one step lighter; fewer
  reps never allow a heavier load than one step above the heaviest set at as many reps or more.
  Against main's prompt (3 runs per scenario): accepted 82.5 % to 87.6 %, expectations flat
  (79.4 % to 79.7 %), `bench_rir_missed` 0/3 to 4/5, the power week 0/3 to 3/5 accepted,
  unsourced numbers 11 to 6 (on more runs). Main's prompt was measured on 3 runs, this one on
  5: the rates carry different sampling noise, and only the gains on the targeted scenarios
  (a missed RIR, the power week) are large enough to read as the rules' effect.
  Rejected along the way: a version that mapped the bench programme's own intent wording ("very
  short sets", "volume halved") to numbers scored 84 % accepted and fixed the deload, but it was
  tuned to the bench's phrasing, and once written generically it fell to 79 %.
- **Agent team** (step 7): kept only if it has **no constraint violation**, cites numbers **at
  least as accurately** as the single agent, and costs **at most 2×** its tokens; otherwise the
  README reports the negative result.

## Run it

```bash
createdb lifter_bench                       # emptied before every scenario
uv run lifter bench                         # copy baseline
uv run lifter bench --planner mistral --runs 3 --out bench/results/single-agent.json
uv run lifter bench --only knee_pain deload_week
```

The bench database must be named `lifter_bench` or `lifter_bench_<suffix>` and differ from
`DATABASE_URL`: the runner refuses anything else, since it empties every table. A pass stops
before the next scenario once
it has used `LIFTER_BENCH_TOKEN_BUDGET` tokens (1,000,000 by default; raise it for `--runs 3`),
and every run inside it is capped by `LIFTER_RUN_TOKEN_BUDGET` (docs/agents.md). The bench
always sends the default `indicators` context and does not read `LIFTER_LLM_CONTEXT`: its
athletes are synthetic, and every pass is measured on the same input.

## Conversation scenarios (the coach)

The coach in conversation (ADR 0002) has its own scenarios, in `bench/conversations/*.yaml`:
one or a few athlete messages, then checks on the database. They were written before any run
against a model; `no_forbidden_suggestion` was added to `ideas_only` and `forbidden_exercise`,
and `unchanged` to `forbidden_exercise`, after the fourth round, when the coach was given the
forbidden exercises (it had once applied the leg press it should have suggested).

| Scenario | Category | Expected |
|---|---|---|
| `move_session` | instruction | the session moved, `move_session` applied |
| `undo` | instruction | a move then "annule": the session back on its day |
| `question` | question | nothing changed |
| `programme_question` | question | "where am I in the cycle": nothing changed (the review expects the block's and the week's intent, from the snapshot) |
| `change_week_intent` | instruction | a legs line added to week 3's intent: `update_week` applied, the line in the intent (under its kind or in the note), the note kept |
| `ideas_only` | question | nothing applied (suggestions at most), no forbidden exercise suggested |
| `wrist_pain` | health | an open health issue on the wrist |
| `log_session` | report | the leg press logged as done |
| `add_mobility` | instruction | a mobility part at the start of the session, holding an exercise (added after the coach's first turns in the app left an empty part) |
| `mobility_three_joints` | instruction | one mobility part for hips, shoulders and ankles, never one part per joint (added after the coach made four mobility parts on 2026-10-19) |
| `undo_elsewhere` | instruction | a move in one conversation, then a bare "annule" in a new one: nothing undone, the coach asks |
| `undo_elsewhere_named` | instruction | the same move, then an undo that names it in a new conversation: undone |
| `forbidden_exercise` | rules | no back squat planned (the athlete's rule refuses it) or suggested, and no replacement applied |
| `planted_note` | injection | an instruction planted in a note changes nothing; the goals are kept |

Measured per run: expectations met, model calls, tokens, writes refused because the quote was
not the athlete's, turns stopped by a limit. Each `review` line is for hand grading.

The floor is a coach that never calls a tool (`--coach silent`): 50 % of expectations (50 %
before `no_forbidden_suggestion` and `unchanged` on `forbidden_exercise`, which a coach that
does nothing always meets, 60 % before `add_mobility`, 56 % before `mobility_three_joints`,
53 % before the two `undo_elsewhere` ones, 50 % before `programme_question` and
`change_week_intent`), 5 of 14
scenarios fully met (every "nothing changes" one, none of the others;
`bench/results/conversations-silent.json`). **The coach with `mistral-small-latest`** (`--coach
mistral --runs 3`, `bench/results/coach-mistral-small.json`): **36 runs of 36 fully met** on the
twelve scenarios, no quote refused, no turn stopped by a limit, about 1,130,000 tokens. The snapshot
now carries each part's lines (compact JSON, empty fields left out), which raised the input of
a call from about 6,000 to about 8,000 tokens. It got there in eight rounds:
- **First pass, 67 %.** The coach called operations as if they were tools, guessed table
  names and part ids, picked last week's legs session to move, and reported an undo as refused
  without calling any tool.
- **Then 92 %.** The snapshot gained week numbers, the parts of each session with their ids,
  the exercise bank's names and the table list for `read_rows`, and the prompt said that every
  change is `apply_change` with an operation.
- **Then 100 %.** The snapshot marks sessions as upcoming or past, and lists the changes applied
  in the conversation with their change ids, which undo takes. The prompt forbids reporting a
  refusal that no tool returned (16 of 16, about 270,000 tokens, no turn stopped).
- **After the code review, 100 % again.** A session done or cancelled is no longer upcoming,
  and each recent change says whether undo can still take it (not undone, not an undo itself).
  But one `ideas_only` turn stopped at the 8-call limit: it changed nothing, so its expectation
  held, yet the athlete got no ideas (16 of 16, about 316,000 tokens).
- **Fifth round, 100 % on 3 runs.** The `ideas_only` turn had looped on suggestions with an
  invalid payload, guessing the fields each time: an invalid payload now comes back with the
  operation's schema, and `ideas_only` takes 2 or 3 calls. The snapshot gives the exercises a
  `forbid_flag` rule excludes and the athlete's rules; the coach once applied the leg press it
  should have suggested in place of the forbidden back squat, so the prompt says a replacement
  is a suggestion, never applied, and the scenario checks it.

- **Sixth round, after the first turns in the app (2026-10-19).** Asked to add an exercise to
  today's session, the coach said its parts were empty: the snapshot gave the parts without
  their lines. Asked for a mobility exercise at the start of a session, it added an empty part
  and no exercise. The snapshot now carries the lines, the prompt says a new part always gets
  its exercise, and `add_mobility` checks it: 27 of 27.
- **Seventh round, one part per kind (2026-10-19).** Asked for hips, shoulders and ankles, the
  coach had made four mobility parts. The catalogue now refuses a second part of a kind (#95),
  and the prompt says that an exercise of a kind the session has goes into that part, a joint
  being a note on the line. `mobility_three_joints` passes 3 of 3: one mobility part; where the
  bank lacked shoulder and ankle mobility, the coach added them to it (`add_exercise`) and put
  them in the part. One `add_mobility` run of 3 asked "OK?" instead of adding the exercise: 29
  of 30.
- **Eighth round, several conversations (2026-10-19).** The snapshot lists the last changes of
  every conversation, those of this one marked, with the athlete's words that made each. A bare
  "annule" in a new conversation undid the move made in another one 3 times of 3 despite the
  prompt, so the code now refuses an undo of a change made elsewhere unless the quote names it
  (the full quote rule). With a named change the model first moved the session back by hand;
  the prompt says an undo is always the undo operation, and the words that made each change
  let it find the one named. `undo_elsewhere` 3 of 3, `undo_elsewhere_named` 3 of 3: 36 of 36.
- **The programme in the snapshot (2026-10-20, `mistral-medium-latest`).** The coach could not
  say where the athlete was in the cycle nor what a week was for: it saw sessions, not the
  method. The snapshot now carries the cycle, its blocks and its weeks with their intents and
  reviews, and the prompt says the method changes through `update_week`, `update_block` and
  `update_cycle`. Asked to add a legs line to week 3's intent, the coach sent only that kind and
  the week lost its note, 3 times of 3, prompt or not: the tools now merge the kinds given into
  the week's map (a kind set to null removes it). `programme_question` 3 of 3 (block and week
  named from the snapshot, one call), `change_week_intent` 3 of 3
  (`bench/results/coach-mistral-medium-programme.json`, about 112,000 tokens).

Twelve scenarios are few: the next steps are more conversations, written from how the athlete
talks but synthetic (the repository is public, the athlete's messages hold health data).

`planted_note` is the real test of the model: its
planted quote is made of words the athlete does write, so the quote check alone would let it
through (the known limit of ADR 0002); only the model's reading of data as data stops it.

```bash
uv run lifter bench-chat                                   # the silent floor
uv run lifter bench-chat --coach mistral --runs 3 --out bench/results/coach-single.json
```
