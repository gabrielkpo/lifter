"""Entry point of the API on Vercel (pyproject.toml, [tool.vercel] entrypoint)."""

from lifter.api.hosted import create_app_from_env

app = create_app_from_env()
