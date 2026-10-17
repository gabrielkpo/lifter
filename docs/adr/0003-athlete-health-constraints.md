# ADR 0003: health constraints belong to each athlete, gathered by the coach

- Status: proposed (2026-10-17), to be validated by the project owner before any code.
- Scope: the agents (coach, planner, guardrail, bench) and the app (schema, operations,
  profile), written by the agents session.

## Context

Lifter is meant for more than one athlete. What one athlete must avoid comes from their own
body: a joint condition, a limited range of motion, a past injury. Another athlete has other
limits, or none. The owner's rule: **nothing specific to an athlete is written in code**, and
nothing about the body is decided in advance for everyone: not the list of what an exercise
demands, not which body part limits which movement, not what to do after a pain. The coach
gathers it in conversation, writes it to the athlete's profile in the database, and the
programme follows from it.

The coach never makes a diagnosis. When the athlete gives one, or a professional's instruction
("my physio says patellar tendinopathy, no deep knee flexion under load for six weeks"), the
coach records it and adapts the training to it.

What exists today, after ADR 0002:

| Piece | Where it lives | Specific to the athlete? |
|---|---|---|
| Rules (`athlete_rule`: forbid a flag, stop after pain, progression) | data, per athlete; the coach can add, change or deactivate one | yes |
| How a rule type is checked (`guardrail.py`) | code | no, and that is right |
| Exercise flags (`free_barbell_legs`, `impact`, `running`) | data, but chosen for one athlete's rules | **mixed**: `free_barbell_legs` only makes sense for one athlete |
| The stop rule's scope: the **movement pattern** of the painful session (`legs`, `hinge`) | code | no, but decided for everyone and too coarse: a knee pain after a legs session caps every `legs` exercise and none of the `hinge` ones, whatever the knee has |
| Health issues (`health_issue`: body part, side, kind, the athlete's words, guidance) | data, recorded by the coach | yes, but **the planner never reads them**: ADR 0002 says it does, the code does not |

So a diagnosis given to the coach is stored and then ignored by the programme, and the only
ways to protect a joint are a flag invented for one athlete or a pattern fixed in code.

## Principle: the code knows how to check, the data says what

The code holds only mechanisms that are the same for every athlete: store a demand, store a
constraint, compare a planned exercise with the athlete's constraints, refuse what breaks one.
Every fact about bodies and exercises is a row in the database, written in conversation and
visible on the profile:

| Fact | Where | Written by |
|---|---|---|
| What an exercise demands ("the back squat flexes the knee deeply") | `exercise_demand` rows, plus the athlete's own corrections | the coach, from the conversation or when an exercise is added |
| The names of demands ("knee flexion", "ankle dorsiflexion", "overhead") | a `demand` table: rows, no list in code or in a `check` | the coach, as the athlete's words need them |
| What an athlete must avoid, and why | `constraint` rows attached to a health issue | the coach, from what the athlete or their professional says |
| How long it lasts | the constraint's end date, or the issue's status | the coach, from what the athlete says |
| What a pain limits | the constraints the coach writes for that issue | the coach, from the athlete's words |

## Decision 1: exercise demands are data, with an open vocabulary

Each exercise can carry **demands**: a demand and a level ("knee flexion: deep", "impact:
high"). The demands themselves are rows of a `demand` table, not a list in code: when an
athlete's issue concerns something no exercise is described by yet (grip, hip rotation), the
coach adds that demand and describes the exercises concerned, and the athlete sees it on the
profile. Exercise demands and constraints both point to a `demand` row, so a constraint can
never name a demand that the exercises spell differently; the coach reuses an existing demand
before adding one.

Demands describe the exercise, so the bank's description is shared. A correction from one
athlete ("the RDL hardly bends my knee") is stored **for that athlete only**, as an override
of the shared level; the shared description changes only through the bank's maintainer (the
owner today), never from another athlete's conversation. One athlete's words, or text planted
in their data, can never loosen another athlete's protection.

The athlete-specific flags (`free_barbell_legs`) disappear: what they stood for becomes a
constraint (Decision 2). Generic facts (`running`, `impact`) become demands.

Transition: `forbid_flag` rules keep working (guardrail, the coach's `forbidden_exercises`) until
every one of them is rewritten as a constraint; the guardrail checks both meanwhile, and
`forbid_flag` is removed only once no active rule uses it.

## Decision 2: a constraint is the athlete's, attached to a health issue

A **constraint** names a demand, a limit (avoid it, or a level not to exceed, with or without
load), the health issue it comes from, and when it ends. Examples of what a coach could write:

- "knee flexion: partial at most under load, until 2026-12-01" (from a knee issue given with a
  physio's instruction);
- "overhead: avoid" (from a shoulder range limit the athlete describes).

The guardrail has one generic check: a planned exercise whose demands (with the athlete's
overrides) break an active constraint is refused, with the constraint's reason. An exercise with
no level recorded for a constrained demand is refused too, with "not described": the check
fails closed, and the coach describes the exercise. When the issue is resolved or the end date
passes, the constraint stops applying.

With this, the RDL question is answered by the athlete's own data: if the athlete's knee
constraint is about deep flexion and the RDL's demand is partial flexion, the RDL stays.

The stop rule keeps its mechanism (a pain above the athlete's threshold after a session), but
what it caps comes from the athlete's data: the constraints of the painful issue if the coach
has written them, otherwise every exercise the painful session loaded (a feedback records pain
for a session, not for one exercise). No body part is mapped to movements in code.

## Decision 3: the coach gathers and writes, the athlete sees and corrects

| The athlete says | What the coach does |
|---|---|
| A diagnosis or a professional's instruction ("physio: no deep squats for six weeks") | Records the health issue with the athlete's words and the constraints the instruction states, with their end date; reports what it wrote |
| A pain ("my knee hurts after squats") | Records the health issue with the athlete's words and, from what the athlete describes, the constraints it implies; asks what it cannot know (how bad, which movements); suggests seeing a professional |
| A limit they know ("my hips are tight in the squat") | Records it and the matching constraint |
| A correction ("the RDL doesn't bother my knee") | Changes the constraint or the exercise's demand |
| "it's healed" | Resolves the issue; its constraints stop; says what comes back into the programme |

Every write goes through `operations.run` (ADR 0002): quoted from the athlete's message,
traced, undoable. The coach always says what it added to the profile, so the athlete can
correct or undo it. It never names a condition the athlete did not name.

**This amends ADR 0002 for one case.** ADR 0002 forbids the coach to apply its own idea without
the athlete's choice. Here the coach writes a constraint it infers from a pain the athlete
described, without waiting for "ok". The exception holds because a constraint only
**restricts** the programme: written wrongly, it makes training more careful, never more
dangerous, and it is reported and undoable. Anything that **loosens** a protection (relaxing
or removing a constraint, an override that lowers a demand, resolving an issue) stays an
instruction the athlete gives, quoted, as ADR 0002 requires.

## Decision 4: the planner programmes from the profile

The planner's context gains the active health issues (with the athlete's words and the
guidance), the active constraints and the demands of the bank's exercises. Its prompt says to
adapt within them (choose the exercise whose demands fit, not just drop the session), and the
guardrail refuses a plan that breaks a constraint. The coach's snapshot shows the same, so a
suggestion never breaks one.

## Who does what

- **App session**: migration (`demand`, `exercise_demand`, the athlete's overrides,
  `constraint` linked to `health_issue`), the operations that write them, the profile page
  showing issues, constraints and demands.
- **Agents session**: the generic constraint check and the stop rule from the athlete's data in
  the guardrail, the planner context and prompt, the coach prompt and snapshot, bench scenarios
  (a physio's instruction, a pain, a correction, an issue resolved, two athletes with different
  limits on the same bank).
- **Owner**: tells the coach about his own body, as any athlete would; nothing to fill in by hand.

## Open question for the owner

The coach writes a constraint it infers from a pain without waiting for a "yes", says what it
wrote, and the athlete corrects or undoes it (proposed above, as an amendment to ADR 0002). Or
should a constraint the coach infers wait for the athlete's "ok", as ADR 0002 has it today?

## Consequences

- A second athlete starts with an empty profile and no inherited limits.
- The guardrail stays deterministic: models gather and write, code checks.
- Nothing about bodies is in code: a new kind of limit needs a conversation, not a release.
- Until this is built, a health issue recorded by the coach does not reach the planner. ADR 0002
  ("the planner reads it") and the `add_health_issue` docstring ("the planner respects the
  active ones") say otherwise; they are corrected with the first change that implements this
  ADR.
