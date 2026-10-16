# ADR 0002: the coach — conversation as approval, the write path, and the agent team

- Status: proposed (2026-10-16), to be validated by the project owner before any code. The
  validation mode itself (Decision 1) was decided by the owner on 2026-10-16.
- Scope: one document for the agents' behaviour and for the write path they use, written by the
  agents session and the app session together.

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
catalogue (Decision 3), generated from the operation's strict Pydantic model so the tool schema
and the code never diverge.

| Tool | Operation | Written |
|---|---|---|
| `apply_change(op, payload, quote)` | any catalogue operation (session, part, line, week, block, record, goal, profile, health issue, rule, exercise bank) | the operation's tables |
| `suggest(op, payload, rationale)` | records a suggestion as a **pending** proposal, numbered in the coach's message | `proposal` only |
| `accept_suggestion(number, quote)` | approves and applies a pending suggestion | as the operation |
| `log_session(session, lines, result, feedback, quote)` | the session report | done lines, metcon result, `feedback` |
| `record_health_issue(zone, kind, description, quote)` | a declared pain or limitation | `health_issue` |
| `undo(change, quote)` | the inverse of a recorded change | as the inverse |
| `plan_week(week)` | runs the week planner (Decision 4); its sessions come back as suggestions | `proposal`, `agent_run` |

Every write tool runs the same path in code, in one transaction:

1. **Quote check.** `quote` must appear, word for word, in a message **from the athlete** in the
   current conversation (the message being answered, or the one before it for "ok for 2").
   The check reads that message **from the database**, by its `message_id`, server side: the
   conversation endpoint stores every athlete message in `conversation_message` (id, role, text,
   time) **before** the model runs. It never reads a copy supplied by the model or held in the
   graph's state, so a model that invents "the athlete said …" cannot pass it.
   Normalisation only: Unicode NFC, typographic quotes and apostrophes, runs of whitespace. A
   quote found only in a coach message, in the data, or nowhere is refused. For
   `accept_suggestion` and `undo` the quote may be short ("ok", "go for 2", "undo", "annule") but
   must be in the message being answered; for other tools it must contain at least two words.
2. **Payload validation** against the operation's model (unknown fields refused).
3. **Rule check** for operations that change the programme: the guardrail
   (`agents/guardrail.py`) runs on the week as it would be after the change; a violation means
   rollback, and the coach explains which rule and why.
4. **Apply** through the catalogue: the operation returns the rows before and after.
5. **Trace**: one `proposal` row (kind = operation, payload, rationale, author, `quote`,
   `message_id`, status applied, result = before/after) and one `change_log` row used by `undo`.

Garmin data is never edited: a wrong Garmin value is corrected by an annotation, read alongside.

Suggestions stay `pending` until the athlete picks one; the code refuses to apply a suggestion
without a quote from the athlete. By default a suggestion expires when the week it concerns has
started (open question 2 tunes it).

## Decision 3: the write path — a catalogue of typed operations covering everything

The owner wants the coach able to change **everything**: the programme (cycle, block, week,
session, parts, exercise lines), what was done (loads, RIR, metcon results, notes), records,
goals and milestones, the profile (`athlete`), health (`health_issue`), the rules and the
exercise bank. The four proposal kinds of today are not enough.

**Catalogue** (`lifter/operations.py`): one operation per entity and verb (create, update,
delete, or resolve for a health issue), each with:

1. a stable `name` (`move_session`, `update_line`, `set_record`, `add_health_issue`…) and a
   strict Pydantic payload (`extra="forbid"`);
2. `apply(conn, payload) -> Change`: the entity, its id, the rows **before and after** (JSON),
   in one transaction, nothing written if invalid;
3. a deterministic **inverse** computed from before and after, used by `undo` (restore before,
   delete what was created, recreate what was deleted); `undo` is itself a traced operation and
   sets `undone_by` on the original; "redo" is a new instruction;
4. for operations that change the programme, `check(conn, change) -> list[Violation]` before
   commit: the guardrail on the week as it would be; records, profile and health are validated
   by type only;
5. the trace: one `proposal` row (kind = operation, payload, rationale, author, `quote`,
   `message_id`, `idempotency_key`, status, result = the change) and one `change_log` row.

**Coverage at 100 %**: a CI test fails when a writable table has no operation; the raw Garmin,
audit and schema tables are excluded explicitly. The proposal kinds of today become operations
of the catalogue without breaking `propose`, `decide`, `apply` or the week planner. Records
(definitions and entries for lifts, gymnastics, cardio and benchmarks, today hard-coded in the
app) get their table and a `set_record` operation.

**Robustness**:

- an **idempotency key** per application, so a network retry never applies a change twice;
- a **row version** (`updated_at` or `version`) checked on update: a change based on a stale
  state is refused instead of overwriting;
- `undo` is refused when the row changed since the change it reverts;
- **database constraints** (CHECK, foreign keys, NOT NULL) for every new column, on top of the
  Pydantic models.

**Database role `lifter_coach`** (in `roles.sql`, tested in the privilege matrix), applied by
Python code rather than `security definer` functions, so the domain and the guardrail keep one
source of truth:

- insert, update and delete on the domain tables only, with column grants where useful; insert
  only on `change_log`, `agent_run` and `agent_step`; on `proposal`, insert and update of the
  status and trace columns only; nothing on the raw Garmin layer, `sync_log`, the schema or the
  roles;
- **no write without a trace**, enforced by the database: a deferred constraint trigger on
  every domain table makes the commit fail when the writer is `lifter_coach` and the
  transaction has no `change_log` row linked to a proposal with a non-null quote;
- **the log is immutable**: no update or delete on `change_log`, even for `lifter_coach`.

Accepted limit: if the agent's process itself were compromised (arbitrary code execution), it
would hold these grants. The realistic threats, injection and hallucination of the model, are
covered: the model has no SQL and every write goes through the quote check. Possible hardening
later: a separate applier deployment, the agent keeping only `lifter_agents`, the applier reading
the quote from the athlete's messages stored by the conversation endpoint.

## Decision 4: an agent team behind the coach, built after the single agent and measured

The coach the athlete talks to is a **supervisor**: it understands the message, picks tools, and
delegates analysis to specialists called as tools. Specialists never write and never talk to the
athlete; they return typed assessments that the supervisor and the planner read.

| Agent | Database role | Reads | Returns or writes | When |
|---|---|---|---|---|
| Coach (supervisor) | `lifter_coach` (Decision 3) | the conversation, the current week, today's recovery, active health issues, pending suggestions | tool calls (Decision 2), the reply | every message; the scheduled jobs open a message |
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
- **Week planner**: as built (`agents/planner.py`), plus the health and performance assessments
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
- **Data quality**: `lifter data-test` after every sync and every night, with an alert; every new
  table of the catalogue comes with its dbt tests (keys, accepted values, relationships) and its
  entry in the data dictionary; CI checks the coverage (catalogue and tools) and the privilege
  matrix.
- **Cost and latency over time**: from the audit tables, on the demo's monitoring.

## Security notes

- **Prompt injection through the data**: notes, Garmin names and rationales can contain text
  aimed at the model. They can make it say something wrong, not change anything: every write
  needs a quote from an athlete message, checked in code.
- **No write tool for specialists**, no SQL for any model, strict schemas everywhere.
- **The model never sees credentials**; the hosted coach endpoint holds the Mistral key and the
  `lifter_coach` connection server-side.
- **Conversation messages**: athlete messages are written to `conversation_message` by the
  endpoint, before the model runs; `lifter_coach` may only insert the coach's own messages.
- **Personal and health data** (a sensitive category under the GDPR):
  - stored only in the EU database (Neon, encrypted at rest); never in the repository, the
    fixtures or the application logs;
  - `agent_run` and `agent_step` hold the context sent to the model, so health data: the full
    context is kept **90 days**, then only the metrics (tokens, seconds, verdicts) remain;
    reading the audit is limited to the owner and the roles that need it;
  - sent to Mistral: only what the task needs (the `indicators` context by default).

## Open questions

1. Chat language: the athlete writes in French; summaries and rationales follow
   `LIFTER_COACH_LANGUAGE`.
2. Whether suggestions should expire sooner than the start of their week, and how far back
   "undo" can reach (it is refused anyway when the row changed since).
3. Streaming of the coach's reply to the app.

## Who builds what (after validation)

| App session | Agents session |
|---|---|
| The catalogue (`operations.py`, `domain.py`), one migration after 008 for `change_log`, `conversation_message`, the trace columns and the records table; the audit's retention (full context 90 days); `lifter_coach` and its grants with the matrix test; the deferred trigger and the immutable log; the coverage test; the hosted conversation endpoint and the Coach tab; the change history in the app | The tools generated from the catalogue; the quote check; the rule check at apply time; `undo` from the coach's side; the coach graph and its prompt; the specialists; the bench scenarios per entity type and per conversation case |

Neither session edits `domain.py` or the catalogue while the other has a pull request open on it.

## Consequences

- The proposal lifecycle stays, as the trace of every change; approval moves from a card to a
  checked quote.
- The week planner keeps working as is; its sessions become suggestions in the conversation.
- Order: the write path (catalogue, trace, role) first, then the tools, the quote check and the
  single coach, then the specialists under the bench's decision rule.
