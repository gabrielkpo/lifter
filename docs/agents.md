# Agents

Lifter's coach is a set of agents built with LangGraph on Mistral models. They read the
analytics views and **propose**; they never write the domain. The athlete approves or rejects
each proposal, and code applies it ([domain.md](domain.md)).

## Week planner (step 3)

The week planner programs one week of the cycle, the way the athlete does every weekend: from
the review of the past week and from the phase of the coming one.

```
START → plan (LLM) → guard (code) ─ accepted ──────────────► END
                          └─ refused, attempts left ─► plan (with the reasons)
```

- **Context** (`agents/context.py`), built by code: the target week (phase, intent per part,
  block and its strength-session count), the review of the previous week (sessions with their
  status, parts, planned and done lines, metcon targets and results, Garmin minutes), sessions
  already planned in the target week, 7 days of recovery (`daily_metrics`, readiness and Body
  Battery from `daily_recovery`), alerts of the last 3 days, the athlete's rules, the exercise
  bank, the heaviest logged load of each exercise per repetition count (28 days, so a deload
  week does not become the reference), the athlete's feedback of the last 14 days (RPE,
  fatigue, pain and where), active goals with their next milestone.
- **Plan** (`agents/plan.py`): a typed `WeekPlan` (summary, sessions with parts and prescribed
  lines, a rationale per session, sessions of the week it replaces). Unknown fields are
  refused; a metcon has a target, never a time cap; results and done lines cannot be
  expressed.
- **Planner** (`agents/planner.py`): one call to a Mistral chat model through LangChain's
  structured output. Token usage is counted for the evaluation bench.
- **Guardrail** (`agents/guardrail.py`): deterministic checks, listed below. A refused plan goes
  back to the planner with the reasons, at most 3 attempts in all; a plan still refused
  proposes nothing.
- **Proposals** (`agents/week.py`): with `--propose`, an accepted plan becomes one
  `create_session` proposal per session (its rationale attached) and one `cancel_session` per
  replaced session, all pending until the athlete decides.

```bash
uv run lifter plan-week                 # next week of the active cycle, dry run
uv run lifter plan-week --week 5 --propose
uv run lifter proposals                 # then: lifter proposal approve|reject ID
```

### Guardrail checks

| Check | Refuses |
|---|---|
| `days` | A session outside the target week |
| `exercise_bank` | An exercise that is not in the bank |
| `cancellations` | Cancelling a session that is not an open session of the target week |
| `sources` | A number in the summary or a rationale that appears nowhere in the context or in the plan's own values (agents read numbers, they never compute them) |
| `critical_alert` | While a critical health alert is on: any metcon, any line under RIR 3, in the plan or in a session of the week it keeps |
| `forbid_flag` (rule) | An exercise carrying a forbidden flag (`running`, `impact`, `free_barbell_legs`…) |
| `no_failure_on_legs` (rule) | A legs or hinge line at RIR 0 or marked as a max |
| `weekly_pattern` (rule) | A week without strength work on the given pattern (legs every week), counting the sessions the plan keeps |
| `no_max_before_test` (rule) | A single to failure, or a line marked as a max, outside the peak and test weeks |
| `fresh_first` (rule) | Weightlifting or gymnastics placed after the metcon |
| `metcon_no_row` (rule) | A listed exercise (the rower) inside a metcon |
| `metcon_light_barbell` (rule) | A weightlifting line above the given load inside a metcon |
| `progression` (rule) | A load more than one step (2.5 kg upper body, 5 kg lower body) above the heaviest set logged in 28 days at as many reps or more |

Rules without a code, or with a code the guardrail does not know, are context for the planner
only; the CLI reports how many were not checked. A low recovery score on the last day is a
warning, not a refusal.

Known limit: `sources` accepts any number found in the context, which holds many numbers (ids,
dates, loads); it stops invented figures and computed differences, not a misattributed one.

## Audit log

Every run started from the CLI (`trigger` cli), the app, a scheduled job or the bench is
recorded by code after it ends (migration `007_agent_audit.sql`, `agents/audit.py`):

| Table | One row per | Holds |
|---|---|---|
| `agent_run` | Run | agent, trigger, model, context mode, target week, status (accepted, refused, error), attempts, tokens, seconds, the **context sent to the model**, the final plan, guardrail warnings, the proposals it created, the error of a crashed run |
| `agent_step` | Attempt | the model's answer (null when it did not parse), the guardrail's violations, tokens and seconds of that attempt |

A proposal leads back to its run through `agent_run.proposal_ids`, so the app can show why a
session was proposed. A crashed run keeps only the error's type and message, never the request.
The log holds the context sent to the model, so it stays in the local database with the rest
of the athlete's data.

```bash
uv run lifter runs              # the last runs
uv run lifter run 12            # each attempt, its violations, tokens and seconds
```

## Settings

| Variable | Default | |
|---|---|---|
| `MISTRAL_API_KEY` | none | Required by `plan-week`; stays in `.env`, never logged |
| `LIFTER_MODEL` | `mistral-small-latest` | Mistral API model name |
| `LIFTER_COACH_LANGUAGE` | `English` | Language of the summary and rationales |
| `LIFTER_LLM_CONTEXT` | `indicators` | What is sent to the model, below |

## What is sent to Mistral

- `indicators` (default): the structured context above, without any free text written by the
  athlete; feedback scales and pain location are included (the stop rule needs them).
- `full`: adds session notes, deviations, week reviews, goal and feedback notes, which may
  describe pain or injuries.
- Never: Garmin activity names (they can contain a place), raw Garmin series, the Garmin token.

The public demo only ever sends synthetic athletes.
