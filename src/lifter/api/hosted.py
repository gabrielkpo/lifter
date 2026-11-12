"""The API configured from the environment, the same way locally and when hosted on Vercel.

Locally (`lifter-api`), the API needs no token and allows the local app origins. Hosted
(the `VERCEL` variable is set), it refuses to start without LIFTER_API_TOKEN or DATABASE_URL,
answers the deployment's own host names and allows no browser origin: only the app's server
calls it.
"""

import logging
import os
from collections.abc import Mapping

from fastapi import FastAPI

from lifter.api.app import create_app
from lifter.api.conversation import CoachSetup
from lifter.config import Settings
from lifter.db import as_role

LOCAL_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
VERCEL_HOST_VARIABLES = ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL")


def split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def create_app_from_env(env: Mapping[str, str] | None = None) -> FastAPI:
    # Errors with their traceback on stderr, which the platform keeps (no request body logged)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if env is None:
        settings = Settings.from_env()  # also loads .env into the environment
        env = os.environ
    else:
        settings = Settings.from_env(env)
    # The platform's own variables (VERCEL, its host names) are read here; Lifter's settings
    # come from Settings.
    hosted = bool(env.get("VERCEL"))
    token = settings.api_token
    if hosted and not token:
        raise RuntimeError("LIFTER_API_TOKEN is required when the API is hosted")
    if hosted and not env.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required when the API is hosted")
    hosts = [env[name] for name in VERCEL_HOST_VARIABLES if env.get(name)]
    hosts += split(settings.api_hosts)
    origins = split(
        settings.app_origins
        if settings.app_origins is not None
        else ("" if hosted else LOCAL_ORIGINS)
    )
    return create_app(
        settings.database_url,
        origins,
        hosts=hosts,
        token=token,
        coach=coach_setup(settings, hosted=hosted),
    )


def coach_urls(settings: Settings, *, hosted: bool) -> tuple[str | None, str | None]:
    """The conversation's and the coach's database URLs. Without their own URLs, locally,
    DATABASE_URL acting as lifter_chat and lifter_coach: the coach never writes as the owner,
    so the database's trace check and row policies hold here too."""
    local = None if hosted else settings.database_url
    return (
        settings.chat_database_url or (local and as_role(local, "lifter_chat")),
        settings.coach_database_url or (local and as_role(local, "lifter_coach")),
    )


def coach_setup(settings: Settings, *, hosted: bool) -> CoachSetup | None:
    """The coach's roles and model. Hosted, each role has its own URL (LIFTER_CHAT_DATABASE_URL
    as lifter_chat, LIFTER_COACH_DATABASE_URL as lifter_coach); locally, the API's database
    serves both, its sessions acting as those roles. Without them or without MISTRAL_API_KEY,
    the conversation is off (503)."""
    chat, coach = coach_urls(settings, hosted=hosted)
    key = settings.mistral_api_key
    if not (chat and coach and key):
        return None

    def model():
        from lifter.agents.coach import mistral_model

        return mistral_model(key, settings.coach_model, settings.max_output_tokens)

    return CoachSetup(
        chat_url=chat,
        coach_url=coach,
        model=model,
        model_name=settings.coach_model,
        language=settings.coach_language,
        token_budget=settings.coach_token_budget,
        daily_token_budget=settings.coach_daily_token_budget,
    )
