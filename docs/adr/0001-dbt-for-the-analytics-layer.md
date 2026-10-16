# ADR 0001: dbt for the analytics layer

- Status: accepted (2026-10-16)
- Decided by: the project owner, after weighing it against plain SQL views

## Context

Lifter turns raw Garmin answers and the athlete's log into the numbers its agents cite (HRV
against baseline, acute and chronic load, recovery score, sessions done, block progress). The
week planner reads those numbers, the guardrail checks every number the model cites against
them, and the evaluation bench grades the plans with them. A wrong or silently renamed column is
a wrong plan, not a cosmetic bug.

Until now the transformations lived in one `views.sql` file (about 25 views and 2 functions),
recreated by `lifter migrate` when the file changed, tested by hand-written pytest checks.

The data is small: about 11 MB for a season, a few thousand rows.

## Decision

Build the `analytics` schema with **dbt** (dbt-core and dbt-postgres only, no packages, no dbt
Cloud):

- one model per view, in layers: `staging` (typed columns read from the raw JSON),
  `intermediate` (daily grid, activity to session matching), `marts` (what the API and the
  agents read);
- sources declared on the `public` tables, with a freshness check on the raw Garmin layer;
- data tests (unique, not null, accepted values, relationships, and Lifter's own rules such as
  "an activity belongs to one session at most");
- **model contracts** (column names and types) on the marts the API and the agents read, so a
  renamed or retyped column fails the build instead of the app or a plan;
- documentation and lineage generated from the models.

## Why, given the size

Not for volume: plain views over 11 MB are fast and a warehouse tool brings nothing there.
dbt is chosen for **guarantees on the numbers**: contracts, tests that run on the real data, and
a dependency graph that shows where every cited number comes from. These matter at any size
when a language model builds its plans on them.

## What does not change

- `lifter migrate` stays the single entry point: numbered migrations, then the dbt models when
  they changed, then `roles.sql` (recreated views lose their grants). Tests, the bench, the CI
  and the hosted database go through it as before.
- Every model stays a **view**: the planner reads the state right after a sync or a log, and a
  table would need a rebuild after every write.
- Everything stays in the `analytics` schema under its current name (`generate_schema_name` is
  overridden): no reader changes.
- The connection comes from the URL given to `lifter migrate`; there is no `profiles.yml`
  pointing at a database by default.

## Costs

- A dependency (dbt-core, dbt-postgres, the `transform` extra) for whoever migrates or runs
  the data tests; the API and the scheduled sync do not import it.
- A compile step: a few seconds per migration, once per test session.
- A second place to learn: SQL now sits in `src/lifter/transform/models/` with YAML next to it.

## Alternatives considered

- **Plain views in one file, with hand-written tests** (the previous state): simpler, no new
  tool, about 80 % of the benefit. Rejected because contracts, data tests on the real data and
  lineage would have to be rebuilt by hand.
- **Materialised tables** (dbt or not): rejected for now, see "What does not change".

## When to revisit

- A mart too slow for a view: make it an incremental table, rebuilt by the sync.
- Several athletes per database: row-level security, and models partitioned by athlete.
