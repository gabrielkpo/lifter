"""The API app on Vercel, imported by the deployment's entry point (api/index.py)."""

from lifter.api.hosted import create_app_from_env

app = create_app_from_env()
