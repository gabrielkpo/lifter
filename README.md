# Lifter

Training coach agent built on Garmin data: it reads metrics through the Garmin MCP server,
analyses recovery and load, proposes a weekly plan and never writes to Garmin without approval.

> Status: work in progress.

## Development
```
uv sync --group dev
uv run ruff check . && uv run ruff format --check .
uv run pytest
```
Health data never goes into this repository: tests and demos use synthetic data only.
