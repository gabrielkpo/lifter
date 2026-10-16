"""`lifter-api`: serve the API on 127.0.0.1 for the app.

Locally the API listens on 127.0.0.1 only: the host is fixed, only the port is configurable
(LIFTER_API_PORT). LIFTER_APP_ORIGINS lists the app origins allowed to call it from a browser,
comma-separated; LIFTER_API_TOKEN, when set, is required on every request (lifter.api.hosted).
"""

import os

import uvicorn

from lifter.api.hosted import create_app_from_env

HOST = "127.0.0.1"


def main() -> None:
    app = create_app_from_env()
    uvicorn.run(app, host=HOST, port=int(os.environ.get("LIFTER_API_PORT", "8000")))
