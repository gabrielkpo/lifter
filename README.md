# Lifter

[![CI](https://github.com/gabrielkpo/lifter/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrielkpo/lifter/actions/workflows/ci.yml)

Training coach agent built on Garmin data: it reads metrics through the Garmin MCP server,
analyses recovery and load, proposes a weekly plan and never writes to Garmin without approval.

> **Status: under active development, built in public.** Step 1 of 10 is done (see the
> roadmap). Expect breaking changes until the first release.

## Roadmap
Each step lands as a reviewed pull request with green CI.

| # | Step | Status |
|---|---|---|
| 1 | Garmin sync into Postgres, metric definitions, tests on synthetic data | ✅ Done |
| 2 | Single agent (LangGraph + Mistral): read tools, structured output, deterministic guardrail, dry-run mode | ⏳ Next |
| 3 | Long-term memory (goals, injuries, preferences, past plans) and a `remember` tool | Planned |
| 4 | Human in the loop: pause before any write, approve / edit / reject, Postgres checkpoints | Planned |
| 5 | Audit log of every node and tool call, with an audit page | Planned |
| 6 | Multi-agent graph (recovery analyst, load analyst, planner, guardrail, writer) on the same state and tools | Planned |
| 7 | Evaluation bench: 20 to 40 scenarios, expectations written first, single agent vs multi-agent | Planned |
| 8 | Approved writes to Garmin (`schedule_workout`), outside dry-run only | Planned |
| 9 | Private deployment behind authentication, CI/CD and monitoring | Planned |
| 10 | Results write-up: architecture diagram, bench results and limits | Planned |

The multi-agent graph is kept only if it beats the single agent on the bench, by a rule fixed
before the runs. If it does not, the README will say so.

## Data and privacy
- The code is public; the author's health data never is. Tests and demos use synthetic data;
  `data/` and `.env` are ignored by Git; gitleaks scans every pull request and push to `main`.
- Real Garmin data stays in a local Postgres database. Lifter reaches the Garmin MCP server on
  the loopback or a private network, and that server is never exposed without authentication.
- Lifter gives no medical advice. Unusual signals already raise `critical` alerts
  ([docs/metrics.md](docs/metrics.md)); from step 2 the guardrail uses them to block intense
  plans and point to a health professional.

## What works today
Step 1 of the plan: Garmin data is copied into Postgres and turned into documented metrics.

- `lifter sync` calls the Garmin MCP server ([garmin-mcp-remote](https://github.com/gabrielkpo/garmin-mcp-remote))
  with **read tools only** and stores every answer as raw JSON, deduplicated by hash. Days
  already stored are not fetched again, except the last 3 (Garmin completes them late);
  `--refresh` refetches the whole range. A failed call is logged and the sync goes on (it
  stops after 5 failures in a row). Activities that Garmin confirms deleted stop counting.
- SQL views turn the raw layer into daily metrics: acute and chronic load, ACWR, HRV and
  resting heart rate against a personal baseline, a recovery score, a trend and alerts.
  Every definition is in [docs/metrics.md](docs/metrics.md).

```
cp .env.example .env        # then set GARMIN_MCP_TOKEN
createdb lifter
uv run lifter migrate
uv run lifter sync --days 90
uv run lifter metrics --days 14
```

## Development
```
uv sync --group dev
uv run ruff check . && uv run ruff format --check .
uv run pytest               # needs a local Postgres (TEST_DATABASE_URL, default postgresql:///postgres)
```
Health data never goes into this repository: tests and demos use synthetic data only.
