# ADR 0002: the coach — conversation as approval, typed tools, and the agent team

- Status: proposed (2026-10-16). The validation mode itself was decided by the project owner on
  2026-10-16; the tools, the team and the orchestration below are the design to build it.
- Scope: the behaviour of the agents. The app side (Coach tab, hosted endpoint, catalogue of
  operations, database roles) is designed with the app and referenced here.

## Context

Until now an agent only **proposed**: the week planner wrote pending proposals, the athlete
approved each one, code applied it. The owner does not want approval cards. He wants the coach
to work like the conversation he already has with a general assistant about his training: he
says what he wants, the coach does it and reports what changed.

That keeps the three properties the project is built on, but moves where they are enforced:

1. the athlete decides every change;
2. numbers and rules are checked by code, never by a model;
3. every change is traceable and reversible.

A language model cannot be trusted to decide that the athlete agreed: a misread message, a
hallucination, or text planted in the data (a note, a Garmin activity name) would be enough to
rewrite a week. So approval stays a **deterministic** check in code; only its form changes.

## Decision 1: the conversation is the approval

| The athlete's message | What the coach does |
|---|---|
| An instruction ("move Thursday to Friday", "bench 4x5 at 70 this week") | Applies it at once, then reports what changed and its scope (this week only, or from week N), with the adjustments it made as a consequence |
| A choice among the coach's suggestions ("ok for 2") | Applies that suggestion, then reports |
| A question ("why RIR 3?") | Answers; nothing changes |
| A session report ("done, bench 4x8 at 65, RIR 1, knee fine") | Logs the session as done (lines, metcon result, feedback), updates loads and references |
| A pain or limitation ("my wrist hurts") | Records it on the profile (active health issue); the planner reads it |
| "undo" | Reverts the last change (or the one named) |
| Weekend programming ("program next week") | Plans the week in the same conversation, from the review and the block's phase |

What the coach must not do: ask "shall I apply it?" for an explicit instruction, apply its own
suggestion without the athlete's choice, or apply anything when the athlete only asked a
question. A point that needs the athlete's opinion is raised separately and not applied.

## Decision 2: every change goes through a typed tool, checked by code

The model has **no SQL and no direct write**. It calls tools; each tool is one operation of the
catalogue (built with the app: `lifter/operations.py`), generated from the operation's strict
Pydantic model so the tool schema and the code never diverge.

| Tool | Operation | Written |
|---|---|---|
| `apply_change(op, payload, quote)` | any catalogue operation (session, part, line, week, block, record, goal, profile, health issue, rule, exercise bank) | the operation's tables |
| `suggest(op, payload, rationale)` | records a suggestion as a **pending** proposal, numbered in the coach's message | `proposal` only |
| `accept_suggestion(number, quote)` | approves and applies a pending suggestion | as the operation |
| `log_session(session, lines, result, feedback, quote)` | the session report | done lines, metcon result, `feedback` |
| `record_health_issue(zone, kind, description, quote)` | a declared pain or limitation | `health_issue` |
| `undo(change, quote)` | the inverse of a recorded change | as the inverse |
| `plan_week(week)` | runs the week planner (section 4); its sessions come back as suggestions | `proposal`, `agent_run` |

Every write tool runs the same path in code, in one transaction:

1. **Quote check.** `quote` must appear, word for word, in a message **from the athlete** in the
   current conversation (the message being answered, or the one before it for "ok for 2").
   Normalisation only: Unicode NFC, typographic quotes and apostrophes, runs of whitespace. A
   quote found only in a coach message, in the data, or nowhere is refused. For
   `accept_suggestion` the quote may be short ("ok", "go for 2") but must be in the message being
   answered; for other tools it must contain at least two words.
2. **Payload validation** against the operation's model (unknown fields refused).
3. **Rule check** for operations that change the programme: the guardrail
   (`agents/guardrail.py`) runs on the week as it would be after the change; a violation means
   rollback, and the coach explains which rule and why.
4. **Apply** through the catalogue: the operation returns the rows before and after.
5. **Trace**: one `proposal` row (kind = operation, payload, rationale, author, `quote`,
   `message_id`, status applied, result = before/after) and one `change_log` row used by `undo`.

Garmin data is never edited: a wrong Garmin value is corrected by an annotation, read alongside.

Suggestions stay `pending` until the athlete picks one; the code refuses to apply a suggestion
without a quote from the athlete. A suggestion older than the conversation's current week
expires.

## Decision 3: an agent team behind the coach, built after the single agent and measured

The coach the athlete talks to is a **supervisor**: it understands the message, picks tools, and
delegates analysis to specialists called as tools. Specialists never write and never talk to the
athlete; they return typed assessments that the supervisor and the planner read.

| Agent | Database role | Reads | Returns or writes | When |
|---|---|---|---|---|
| Coach (supervisor) | `lifter_coach`: read, plus writes only through the catalogue path | the conversation, the current week, today's recovery, active health issues, pending suggestions | tool calls (Decision 2), the reply | every message; the scheduled jobs open a message |
| Week planner (built) | `lifter_agents`: read, insert proposals and audit | the planning context (docs/agents.md) | a typed `WeekPlan`, turned into suggestions | "program next week", Sunday job |
| Long-term planner | `lifter_agents` | block progress, goals and milestones, documented progression | a typed block decision: extend the block, move on, recalibrate milestones, with reasons | when a block's strength-session count is reached, before the test week, on request |
| Health analyst | `lifter_agents`, read only in practice | daily metrics, recovery, alerts, feedback, health issues | a typed health assessment: state, risks, constraints for the week ("first two days light") | morning job, before any planning |
| Performance analyst | `lifter_agents`, read only in practice | logged lines, best loads, progress per exercise, goals, benchmarks | a typed assessment per movement: progressing, stalling, RIR kept or not, milestone on track | Sunday before planning, after the test week |

The flow is fixed in a LangGraph graph rather than left to the model where it is known in
advance (weekend programming: health and performance analysts in parallel, then the planner,
then the guardrail, then the coach presents the week). Free tool choice is kept for the open
conversation.

**Order of construction.** The single coach with all tools comes first: it is the baseline. The
specialists are added after, and kept only under the bench's decision rule: **no constraint
violation**, cited numbers **at least as accurate** as the single agent, **at most twice** its
tokens. Otherwise the README reports the negative result and the single coach stays.

### Prompts

- **Coach**: the athlete's method (frame of a session, RIR as the instruction, metcon target and
  no time cap, phases), the behaviour table of Decision 1, "no medical advice: a persistent
  critical signal means seeing a professional", "cite only numbers from the context or the
  tools", and the tool descriptions generated from the catalogue. Language: the athlete's.
- **Week planner**: as built (agents/planner.py), plus the health and performance assessments
  and the active health issues once those exist.
- **Specialists**: their role, the definitions of the numbers they read (docs/metrics.md), and a
  strict output schema; no free text outside the schema's `rationale` fields.

## Monitoring

- **Audit** of every run (`agent_run`, `agent_step`; triggers `app`, `job`, `cli`, `bench`): the
  context sent, each answer, the guardrail's verdicts, tokens, seconds, errors.
- **Change log** of every applied change: the athlete's quote and message, before and after,
  undo.
- **Budgets**: a token budget per message and per run (`LIFTER_RUN_TOKEN_BUDGET`), an output cap
  per answer, a budget per bench pass.
- **Bench**: the 20 week-planning scenarios, plus conversation scenarios per entity type: a
  message (or a short exchange) and the expected database state after it ("change my clean PR to
  77.5 kg", "my wrist hurts", "move Thursday", "undo", "why RIR 3?" changes nothing, a planted
  instruction inside a note changes nothing).
- **Alerts**: a failed run, a run stopped by its budget, or a refused quote raise an alert with
  the scheduled-sync alerts (docs/operations.md).
- **Cost and latency over time**: from the audit tables, on the demo's monitoring.

## Security notes

- **Prompt injection through the data**: notes, Garmin names and rationales can contain text
  aimed at the model. They can make it say something wrong, not change anything: every write
  needs a quote from an athlete message, checked in code.
- **No write tool for specialists**, no SQL for any model, strict schemas everywhere.
- **The model never sees credentials**; the hosted coach endpoint holds the Mistral key and the
  `lifter_coach` connection server-side.

## Open questions

1. `lifter_coach` privileges: SQL `security definer` functions (the role can only call them) or
   Python code with write grants on the tables (the role alone does not restrict anything).
   The first limits the role for real; to decide with the app.
2. Chat language: the athlete writes in French; summaries and rationales follow
   `LIFTER_COACH_LANGUAGE`.
3. How long a pending suggestion stays valid, and whether "undo" can reach beyond the last few
   changes.
4. Streaming of the coach's reply to the app.

## Consequences

- The proposal lifecycle stays, as the trace of every change; approval moves from a card to a
  checked quote.
- The week planner keeps working as is; its sessions become suggestions in the conversation.
- The catalogue of operations, the `change_log` table, the trace columns and `lifter_coach` come
  first (app side), then the tools, the quote check and the coach graph (agents side), then the
  specialists.
