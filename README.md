# Lifter

[![CI](https://github.com/gabrielkpo/lifter/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrielkpo/lifter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A training coach agent for athletes who wear a Garmin watch: it reads their data through the
Garmin MCP server, analyses recovery and load, proposes a weekly plan and never writes to
Garmin without their approval.

> **Status: under active development, built in public.** Step 1 of 10 is done (see
> [Status / Roadmap](#status--roadmap)). Expect breaking changes until the first release.

## Why
A Garmin watch records hundreds of measures a day (heart rate, heart rate variability, sleep,
training load), but turning them into a decision ("what do I do this week?") still takes a
coach. Lifter plays that role from the athlete's own data, and explains every recommendation
with numbers it can trace back to a source.

It is also a test bed for a real agent inside an application: tools, memory, guardrails,
human approval before any write, an audit trail, and a measured comparison of a multi-agent
graph against a single agent.

## How it works
```
Garmin Connect ─► garmin-mcp-remote (MCP server, bearer token)
                          │  read tools only (allowlist)
                          ▼
   lifter sync ─► Postgres: raw_garmin_payload (JSON as received, deduplicated)
                          │
                          ▼
              analytics schema: SQL views ─► daily_metrics, daily_alerts, weekly_training
                          │
                          ▼   (from step 2)
   LangGraph agent (Mistral) ─► guardrail ─► human approval ─► Garmin write
```

Choices and their trade-offs:
- **Raw layer first.** Every MCP answer is stored as received, so the metrics can be rebuilt
  without calling Garmin again, at the cost of some disk space.
- **Plain SQL views, not dbt.** Fewer moving parts and every line is readable; the views are
  pinned by tests with hand-computed cases instead of dbt tests. They live in an `analytics`
  schema recreated whenever `views.sql` changes, so a view change needs no migration.
- **Agents read numbers, they never compute them.** Every metric is defined once in
  [docs/metrics.md](docs/metrics.md); the agent may only cite those values, and the guardrail
  will check each number against them.
- **Deletions are confirmed, not guessed.** An activity missing from a listing is only dropped
  when Garmin answers "not found" for it, so a paging shift never deletes a real session.

## Status / Roadmap
Each step lands as a reviewed pull request with green CI. There are no results yet: the
evaluation bench comes at step 7.

| # | Step | Status |
|---|---|---|
| 1 | Garmin sync into Postgres, metric definitions, tests on synthetic data | ✅ Done |
| 2 | Single agent (LangGraph + Mistral): read tools, structured output, deterministic guardrail, dry-run mode | ⏳ Next |
| 3 | Long-term memory (goals, injuries, preferences, past plans) and a `remember` tool | Planned |
| 4 | Human in the loop: pause before any write, approve / edit / reject in a first Next.js UI over a FastAPI API, Postgres checkpoints | Planned |
| 5 | Audit log of every node and tool call, with an audit page | Planned |
| 6 | Multi-agent graph (recovery analyst, load analyst, planner, guardrail, writer) on the same state and tools | Planned |
| 7 | Evaluation bench: 20 to 40 scenarios, expectations written first, single agent vs multi-agent | Planned |
| 8 | Approved writes to Garmin (`schedule_workout`), outside dry-run only | Planned |
| 9 | Private deployment of the UI and API behind authentication, CI/CD and monitoring | Planned |
| 10 | Results write-up: architecture diagram, bench results and limits | Planned |

The multi-agent graph is kept only if it has no constraint violation, cites numbers at least
as accurately as the single agent, and costs at most twice as many tokens. If it does not,
this README will say so.

## Run it
Needs a local Postgres and a running [garmin-mcp-remote](https://github.com/gabrielkpo/garmin-mcp-remote).
```
cp .env.example .env               # then set GARMIN_MCP_TOKEN
createdb lifter
uv sync
uv run lifter sync --days 90       # creates or updates the schema, then syncs (read-only)
uv run lifter metrics --days 14
```
Days already stored are not fetched again, except the last 3 (Garmin completes them late);
`lifter sync --refresh` refetches the whole range. A failed call is logged and the sync goes
on, and it stops after 5 failures in a row.

## Project structure
```
src/lifter/
  cli.py          lifter migrate | sync | metrics
  garmin.py       MCP client, read-only tool allowlist
  sync.py         Garmin → raw layer, deletion checks
  db.py           connection, migrations, views
  sql/            numbered table migrations + views.sql (analytics schema)
docs/metrics.md   every metric definition and threshold
tests/            pytest on synthetic data (a throwaway Postgres database)
```

## Data and privacy
- The code is public; the author's health data never is. Tests and demos use synthetic data;
  `data/` and `.env` are ignored by Git; gitleaks scans every pull request and push to `main`.
- Real Garmin data stays in a local Postgres database. Lifter reaches the Garmin MCP server on
  the loopback or a private network, and that server is never exposed without authentication.
- Lifter gives no medical advice. Unusual signals already raise `critical` alerts
  ([docs/metrics.md](docs/metrics.md)); from step 2 the guardrail uses them to block intense
  plans and point to a health professional.

## Limitations / next
- Metric thresholds are version 1: training heuristics for one athlete, to be tuned with the
  evaluation bench, not medical criteria.
- Lifter computes its own acute and chronic load (rolling sums), not Garmin's exponentially
  weighted values.
- The sync runs on demand; scheduling it daily is not automated yet.
- No agent yet: step 2 adds the single agent in dry-run mode.

## Development
```
uv sync --group dev
uv run ruff check . && uv run ruff format --check .
uv run pytest               # needs a local Postgres (TEST_DATABASE_URL, default postgresql:///postgres)
```

## License
[MIT](LICENSE)
