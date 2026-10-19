"""The API configured from the environment, the same way locally and when hosted on Vercel.

Locally (`lifter-api`), the API needs no token and allows the local app origins. Hosted
(the `VERCEL` variable is set), it refuses to start without LIFTER_API_TOKEN or DATABASE_URL,
answers the deployment's own host names and allows no browser origin: only the app's server
calls it.
"""

import os
from collections.abc import Mapping

from fastapi import FastAPI

from lifter.api.app import create_app
from lifter.api.conversation import CoachSetup
from lifter.config import Settings

LOCAL_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
VERCEL_HOST_VARIABLES = ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL")


def split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def create_app_from_env(env: Mapping[str, str] | None = None) -> FastAPI:
    if env is None:
        settings = Settings.from_env()  # also loads .env into the environment
        env = os.environ
    else:
        settings = Settings.from_env(env)
    hosted = bool(env.get("VERCEL"))
    token = env.get("LIFTER_API_TOKEN") or None
    if hosted and not token:
        raise RuntimeError("LIFTER_API_TOKEN is required when the API is hosted")
    if hosted and not env.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required when the API is hosted")
    hosts = [env[name] for name in VERCEL_HOST_VARIABLES if env.get(name)]
    hosts += split(env.get("LIFTER_API_HOSTS"))
    origins = split(env.get("LIFTER_APP_ORIGINS", "" if hosted else LOCAL_ORIGINS))
    return create_app(
        settings.database_url,
        origins,
        hosts=hosts,
        token=token,
        coach=coach_setup(env, settings, hosted=hosted),
    )


def coach_setup(env: Mapping[str, str], settings: Settings, *, hosted: bool) -> CoachSetup | None:
    """The coach's roles and model. Hosted, each role has its own URL (LIFTER_CHAT_DATABASE_URL
    as lifter_chat, LIFTER_COACH_DATABASE_URL as lifter_coach); locally, the API's database
    serves both. Without them or without MISTRAL_API_KEY, the conversation is off (503)."""
    chat = env.get("LIFTER_CHAT_DATABASE_URL") or (None if hosted else settings.database_url)
    coach = env.get("LIFTER_COACH_DATABASE_URL") or (None if hosted else settings.database_url)
    key = settings.mistral_api_key
    if not (chat and coach and key):
        return None

    def model():
        from lifter.agents.coach import mistral_model

        return mistral_model(key, settings.model, settings.max_output_tokens)

    return CoachSetup(
        chat_url=chat,
        coach_url=coach,
        model=model,
        model_name=settings.model,
        language=settings.coach_language,
        token_budget=settings.run_token_budget,
    )
