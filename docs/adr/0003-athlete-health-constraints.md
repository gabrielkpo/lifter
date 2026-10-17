# ADR 0003: health constraints belong to each athlete, gathered by the coach

- Status: proposed (2026-10-17), to be validated by the project owner before any code.
- Scope: the agents (coach, planner, guardrail, bench) and the app (schema, operations,
  profile), written by the agents session.

## Context

Lifter is meant for more than one athlete. What one athlete must avoid comes from their own
body: a joint condition, a limited range of motion, a past injury. Another athlete has other
limits, or none. The owner's rule: **nothing specific to an athlete is written in code**.
The coach gathers it in conversation, records it on the athlete's profile, and the programme
follows from it.

The coach never makes a diagnosis. When the athlete gives one ("my physio says patellar
tendinopathy, no deep knee flexion under load for six weeks"), the coach records it and adapts
the training to it.

What exists today, after ADR 0002:

| Piece | Where it lives | Specific to the athlete? |
|---|---|---|
| Rules (`athlete_rule`: forbid a flag, stop after pain, progression) | data, per athlete; the coach can add, change or deactivate one | yes |
| How a rule type is checked (`guardrail.py`) | code | no, and that is right |
| Exercise flags (`free_barbell_legs`, `impact`, `running`) | data, but chosen for one athlete's rules | **mixed**: `free_barbell_legs` only makes sense for one athlete |
| The stop rule's scope: the **movement pattern** of the painful session (`legs`, `hinge`) | code | no, but too coarse: a knee pain after a legs session caps every `legs` exercise and none of the `hinge` ones, whatever the knee has |
| Health issues (`health_issue`: body part, side, kind, the athlete's words, guidance) | data, recorded by the coach | yes, but **the planner never reads them**: ADR 0002 says it does, the code does not |

So a diagnosis given to the coach is stored and then ignored by the programme. And the only way
to protect a joint is a flag invented for one athlete, or a pattern that is too broad and too
narrow at once.

## Decision 1: exercises are described by what they demand, the same for everyone

Each exercise of the bank gets **movement demands**: facts about the exercise, true for every
athlete, never tied to anyone's rules. A first list, to be completed with the owner:

| Demand | Levels | Examples |
|---|---|---|
| `knee_flexion` | none, partial, deep | RDL: partial; leg press: partial to deep; back squat: deep |
| `ankle_dorsiflexion` | low, medium, high | deadlift: low; front squat: high |
| `shoulder_overhead` | none, partial, full | bench press: none; push press: full; snatch: full |
| `spinal_load` | low, medium, high | leg press: low; back squat: high |
| `impact` | none, low, high | row: none; box jump: high; run: high |
| `wrist_extension_loaded` | no, yes | front rack, push-up, dips: yes |

The athlete-specific flags (`free_barbell_legs`) disappear: what they stood for is written as a
constraint on demands (Decision 2). Generic facts (`running`, `impact`) become demands.

Transition: `forbid_flag` rules keep working (guardrail, the coach's `forbidden_exercises`) until
every one of them is rewritten as a constraint; the guardrail checks both meanwhile, and
`forbid_flag` is removed only once no active rule uses it.

## Decision 2: a constraint is the athlete's, attached to a health issue

A **constraint** says which demand to avoid or cap, for which athlete, because of which health
issue, until when:

- "no `knee_flexion` deep under load" (from a knee issue);
- "`shoulder_overhead` partial at most" (from a shoulder range limit);
- "`impact` none" (from an Achilles issue).

It is stored as data (`athlete_rule` with a generic code such as `limit_demand`, its params, and
the health issue it comes from). The guardrail checks it in code against the exercises' demands,
the same way for every athlete. When the issue is resolved, its constraints stop applying.

With this, the RDL question answers itself: a knee issue limited to deep flexion does not touch
the RDL (partial flexion), and nobody has to remember to exclude or include `hinge`.

The stop rule stays generic (pain above the athlete's threshold after a session), but its scope
becomes the **demands** that session loaded on the painful body part, not the whole pattern.

## Decision 3: the coach gathers, the athlete confirms

| The athlete says | What the coach does |
|---|---|
| A diagnosis or a professional's instruction ("physio: no deep squats for six weeks") | Records the health issue with the athlete's words; applies the constraint the instruction states, since it is the athlete's instruction (ADR 0002) |
| A pain, without a diagnosis ("my knee hurts after squats") | Records the health issue (`monitoring`); the stop rule protects the next sessions; the coach **suggests** a constraint and suggests seeing a professional, and applies nothing on its own |
| A range limit they know ("my hips are tight") | Records it; suggests the matching constraint |
| "it's healed" | Resolves the issue; its constraints stop; the coach says what comes back into the programme |

The coach never names a condition the athlete did not name, and never turns a pain into a
diagnosis. A constraint it infers is always a suggestion, answered with "ok for N".

## Decision 4: the planner programmes from the profile

The planner's context gains the active health issues (with the athlete's words and the
guidance) and the active constraints. Its prompt says to adapt within them (choose the
exercise whose demands fit, not just drop the session), and the guardrail refuses a plan that
breaks a constraint. The coach's snapshot shows the same, so a suggestion never breaks one.

## Who does what

- **App session**: migration (exercise demands, the link from a rule to its health issue), the
  operations that write them, the profile page showing issues and their constraints.
- **Agents session**: the `limit_demand` check and the stop rule by demand in the guardrail,
  the planner context and prompt, the coach prompt and snapshot, bench scenarios (a diagnosis
  given, a pain without one, an issue resolved, two athletes with different limits).
- **Owner**: the list of demands and their levels; the demands of the exercises in the bank;
  which existing profile rules become constraints.

## Open questions for the owner

1. Is the first list of demands right? What is missing for CrossFit (hip flexion, grip,
   rotation)?
2. A constraint the athlete dictates from a professional: applied at once (proposed above), or
   still confirmed?
3. Should a pain without a diagnosis create a temporary constraint by itself (for example two
   weeks), or only the stop rule?
4. Which demands does a painful body part limit (a knee: `knee_flexion`, `impact`; a shoulder:
   `shoulder_overhead`...)? The stop rule by demand needs this table. It is generic (anatomy, the
   same for everyone) and data, not code, so it can be corrected without a release.

## Consequences

- A second athlete starts with an empty profile and no inherited limits.
- The guardrail stays deterministic: models gather and suggest, code checks.
- Until this is built, a health issue recorded by the coach does not reach the planner. ADR 0002
  ("the planner reads it") and the `add_health_issue` docstring ("the planner respects the
  active ones") say otherwise; they are corrected with the first change that implements this
  ADR.
