"""The API configured from the environment, the same way locally and when hosted on Vercel.

Locally (`lifter-api`), the API needs no token and allows the local app origins. Hosted
(the `VERCEL` variable is set), it refuses to start without LIFTER_API_TOKEN, answers the
deployment's own host names and allows no browser origin: only the app's server calls it.
"""

import os
from collections.abc import Mapping

from fastapi import FastAPI

from lifter.api.app import create_app
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
    hosts = [env[name] for name in VERCEL_HOST_VARIABLES if env.get(name)]
    hosts += split(env.get("LIFTER_API_HOSTS"))
    origins = split(env.get("LIFTER_APP_ORIGINS", "" if hosted else LOCAL_ORIGINS))
    return create_app(settings.database_url, origins, hosts=hosts, token=token)
