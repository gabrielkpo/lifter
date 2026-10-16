"""Settings read from the environment (and from a local .env file when present)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(ValueError):
    """A setting in the environment or .env has a value Lifter cannot use."""


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{key} must be a whole number, got {value!r}") from None


@dataclass(frozen=True)
class Settings:
    database_url: str
    garmin_mcp_url: str
    garmin_mcp_token: str | None
    sync_delay_seconds: float
    mistral_api_key: str | None = None
    model: str = "mistral-small-latest"
    coach_language: str = "English"
    llm_context: str = "indicators"
    bench_database_url: str = "postgresql:///lifter_bench"
    run_token_budget: int = 60_000
    bench_token_budget: int = 1_000_000
    max_output_tokens: int = 6_000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        if env is None:
            load_dotenv()
            env = os.environ
        return cls(
            database_url=env.get("DATABASE_URL", "postgresql:///lifter"),
            garmin_mcp_url=env.get("GARMIN_MCP_URL", "http://127.0.0.1:8080/mcp"),
            garmin_mcp_token=env.get("GARMIN_MCP_TOKEN") or None,
            sync_delay_seconds=float(env.get("SYNC_DELAY_SECONDS", "1.0")),
            mistral_api_key=env.get("MISTRAL_API_KEY") or None,
            model=env.get("LIFTER_MODEL", "mistral-small-latest"),
            coach_language=env.get("LIFTER_COACH_LANGUAGE", "English"),
            llm_context=env.get("LIFTER_LLM_CONTEXT", "indicators"),
            bench_database_url=env.get("BENCH_DATABASE_URL", "postgresql:///lifter_bench"),
            run_token_budget=_int(env, "LIFTER_RUN_TOKEN_BUDGET", 60_000),
            bench_token_budget=_int(env, "LIFTER_BENCH_TOKEN_BUDGET", 1_000_000),
            max_output_tokens=_int(env, "LIFTER_MAX_OUTPUT_TOKENS", 6_000),
        )
