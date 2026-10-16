"""Settings read from the environment (and from a local .env file when present)."""

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

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


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ConfigError(f"{key} must be a number, got {value!r}")
    return number


# The coach's language is written into the system prompt: a language name, nothing else.
LANGUAGE = re.compile(r"[^\W\d_][^\W\d_ -]*(?:[ -][^\W\d_]+){0,2}")


def _language(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key) or default
    if len(value) > 40 or not LANGUAGE.fullmatch(value):
        raise ConfigError(f"{key} must be a language name such as English or French, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    # Secrets (and URLs that may carry a password) stay out of the repr, so a traceback with
    # its locals, `pytest --showlocals` or a log line with %r never prints them.
    database_url: str = field(repr=False)
    garmin_mcp_url: str
    garmin_mcp_token: str | None = field(repr=False)
    sync_delay_seconds: float
    mistral_api_key: str | None = field(default=None, repr=False)
    model: str = "mistral-small-latest"
    coach_language: str = "English"
    llm_context: str = "indicators"
    bench_database_url: str = field(default="postgresql:///lifter_bench", repr=False)
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
            sync_delay_seconds=_float(env, "SYNC_DELAY_SECONDS", 1.0),
            mistral_api_key=env.get("MISTRAL_API_KEY") or None,
            model=env.get("LIFTER_MODEL", "mistral-small-latest"),
            coach_language=_language(env, "LIFTER_COACH_LANGUAGE", "English"),
            llm_context=env.get("LIFTER_LLM_CONTEXT", "indicators"),
            bench_database_url=env.get("BENCH_DATABASE_URL", "postgresql:///lifter_bench"),
            run_token_budget=_int(env, "LIFTER_RUN_TOKEN_BUDGET", 60_000),
            bench_token_budget=_int(env, "LIFTER_BENCH_TOKEN_BUDGET", 1_000_000),
            max_output_tokens=_int(env, "LIFTER_MAX_OUTPUT_TOKENS", 6_000),
        )
