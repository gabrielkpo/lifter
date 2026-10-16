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
- **20 scenarios** (`bench/scenarios/*.yaml`), each with a situation, machine-checked
  expectations, and a `review` describing a good plan for the hand grading (1 to 5).

| Category | Scenarios |
|---|---|
| Phase | volume peak, deload, after the deload, intensification with the benchmark, power week after unlogged weeks, test week, first week without history |
| Review of the past week | legs skipped, pull and legs skipped, whole week missed, bench RIR missed, bench too easy |
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
  the 20 scenarios: 70 % accepted, **66 % of expectations met**
  (`bench/results/copy-baseline.json`); it fails the deload, the return after it, the stop rule,
  low recovery, critical alerts and duplicates the drafts.
- **Single agent** (`--planner mistral`): the week planner of step 3.
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
