"""Settings read from the environment (and from a local .env file when present)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    garmin_mcp_url: str
    garmin_mcp_token: str | None
    sync_delay_seconds: float

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
        )
