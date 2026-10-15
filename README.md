# Lifter

Training coach agent built on Garmin data: it reads metrics through the Garmin MCP server,
analyses recovery and load, proposes a weekly plan and never writes to Garmin without approval.

> Status: work in progress.

## What works today
Step 1 of the plan: Garmin data is copied into Postgres and turned into documented metrics.

- `lifter sync` calls the Garmin MCP server ([garmin-mcp-remote](https://github.com/gabrielkpo/garmin-mcp-remote))
  with **read tools only** and stores every answer as raw JSON, deduplicated by hash. Days
  already stored are not fetched again, except the last 3 (Garmin completes them late).
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
