"""Settings read from the environment (and from a local .env file when present)."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

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
    if not math.isfinite(number) or number < 0:
        raise ConfigError(f"{key} must be a number of 0 or more, got {value!r}")
    return number


# The coach's language is written into the system prompt: a known language name, nothing else
# (a free pattern let any few words through, an instruction included).
LANGUAGES = {
    name.casefold(): name
    for name in (
        "English", "French", "Français", "Spanish", "Español", "German", "Deutsch", "Italian",
        "Italiano", "Portuguese", "Português", "Brazilian Portuguese", "Dutch", "Catalan",
        "Basque", "Breton", "Polish", "Swedish", "Norwegian", "Danish", "Finnish", "Greek",
        "Romanian", "Czech", "Japanese", "Chinese", "Korean", "Arabic",
    )
}  # fmt: skip


def _language(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key) or default
    name = LANGUAGES.get(" ".join(value.split()).casefold())
    if name is None:
        raise ConfigError(f"{key} must be a language name such as English or French, got {value!r}")
    return name


def _choice(env: Mapping[str, str], key: str, default: str, allowed: tuple[str, ...]) -> str:
    value = env.get(key) or default
    if value not in allowed:
        raise ConfigError(f"{key} must be one of {', '.join(allowed)}, got {value!r}")
    return value


def _port(env: Mapping[str, str], key: str, default: int) -> int:
    port = _int(env, key, default)
    if not 1 <= port <= 65535:
        raise ConfigError(f"{key} must be a port between 1 and 65535, got {port}")
    return port


@dataclass(frozen=True)
class Settings:
    # Secrets (and URLs that may carry a password) stay out of the repr, so a traceback with
    # its locals, `pytest --showlocals` or a log line with %r never prints them.
    database_url: str = field(repr=False)
    garmin_mcp_url: str
    garmin_mcp_token: str | None = field(repr=False)
    sync_delay_seconds: float
    mistral_api_key: str | None = field(default=None, repr=False)
    model: str = "mistral-small-latest"  # the week planner's model
    coach_model: str = "mistral-medium-latest"  # the coach in conversation (bench: +8 points)
    coach_language: str = "English"
    llm_context: Literal["indicators", "full"] = "indicators"
    bench_database_url: str = field(default="postgresql:///lifter_bench", repr=False)
    run_token_budget: int = 60_000  # a week planner run
    # The coach: a turn may take 8 calls of about 12,000 tokens, and a day has a ceiling so a
    # client retrying in a loop, or anyone past the access control, cannot spend without bound.
    coach_token_budget: int = 100_000
    coach_daily_token_budget: int = 600_000
    bench_token_budget: int = 1_000_000
    max_output_tokens: int = 6_000
    # The API (lifter.api.hosted): its bearer token, host names and browser origins (comma
    # separated), the conversation's two role URLs when hosted, and the local port.
    api_token: str | None = field(default=None, repr=False)
    api_hosts: str = ""
    app_origins: str | None = None
    chat_database_url: str | None = field(default=None, repr=False)
    coach_database_url: str | None = field(default=None, repr=False)
    api_port: int = 8000

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
            coach_model=env.get("LIFTER_COACH_MODEL", "mistral-medium-latest"),
            coach_language=_language(env, "LIFTER_COACH_LANGUAGE", "English"),
            llm_context=_choice(env, "LIFTER_LLM_CONTEXT", "indicators", ("indicators", "full")),
            bench_database_url=env.get("BENCH_DATABASE_URL", "postgresql:///lifter_bench"),
            run_token_budget=_int(env, "LIFTER_RUN_TOKEN_BUDGET", 60_000),
            coach_token_budget=_int(env, "LIFTER_COACH_TOKEN_BUDGET", 100_000),
            coach_daily_token_budget=_int(env, "LIFTER_COACH_DAILY_TOKEN_BUDGET", 600_000),
            bench_token_budget=_int(env, "LIFTER_BENCH_TOKEN_BUDGET", 1_000_000),
            max_output_tokens=_int(env, "LIFTER_MAX_OUTPUT_TOKENS", 6_000),
            api_token=env.get("LIFTER_API_TOKEN") or None,
            api_hosts=env.get("LIFTER_API_HOSTS", ""),
            app_origins=env.get("LIFTER_APP_ORIGINS"),
            chat_database_url=env.get("LIFTER_CHAT_DATABASE_URL") or None,
            coach_database_url=env.get("LIFTER_COACH_DATABASE_URL") or None,
            api_port=_port(env, "LIFTER_API_PORT", 8000),
        )
