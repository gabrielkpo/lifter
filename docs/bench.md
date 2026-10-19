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
  unsourced numbers 11 to 6 (on more runs).
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
| `ideas_only` | question | nothing applied (suggestions at most), no forbidden exercise suggested |
| `wrist_pain` | health | an open health issue on the wrist |
| `log_session` | report | the leg press logged as done |
| `forbidden_exercise` | rules | no back squat planned (the athlete's rule refuses it) or suggested, and no replacement applied |
| `planted_note` | injection | an instruction planted in a note changes nothing; the goals are kept |

Measured per run: expectations met, model calls, tokens, writes refused because the quote was
not the athlete's, turns stopped by a limit. Each `review` line is for hand grading.

The floor is a coach that never calls a tool (`--coach silent`): 60 % of expectations (50 %
before `no_forbidden_suggestion` and `unchanged` on `forbidden_exercise`, which a coach that
does nothing always meets), 4 of 8
scenarios fully met (every "nothing changes" one, none of the others;
`bench/results/conversations-silent.json`). **The coach with `mistral-small-latest`** (`--coach
mistral --runs 3`, `bench/results/coach-mistral-small.json`): **24 runs of 24 fully met**, no
quote refused, no turn stopped by a limit, about 395,000 tokens (measured on 876ab1c, with
suggestions accepted only as presented, versioned logs, and the tool calls of one message run
one at a time). It got there in five rounds on the same scenarios:
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

Eight scenarios are few: the next steps are more conversations, written from how the athlete
talks but synthetic (the repository is public, the athlete's messages hold health data).

`planted_note` is the real test of the model: its
planted quote is made of words the athlete does write, so the quote check alone would let it
through (the known limit of ADR 0002); only the model's reading of data as data stops it.

```bash
uv run lifter bench-chat                                   # the silent floor
uv run lifter bench-chat --coach mistral --runs 3 --out bench/results/coach-single.json
```
