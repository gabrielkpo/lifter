"""`lifter-api`: serve the API on 127.0.0.1 for the app.

The API has no authentication yet, so it never listens on another interface: the host is
fixed, only the port is configurable (LIFTER_API_PORT). LIFTER_APP_ORIGINS lists the app
origins allowed to call it from a browser, comma-separated.
"""

import os

import uvicorn

from lifter.api.app import create_app
from lifter.config import Settings

HOST = "127.0.0.1"


def main() -> None:
    settings = Settings.from_env()  # also loads .env into the environment
    origins = os.environ.get("LIFTER_APP_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    app = create_app(settings.database_url, [o.strip() for o in origins.split(",") if o.strip()])
    uvicorn.run(app, host=HOST, port=int(os.environ.get("LIFTER_API_PORT", "8000")))
