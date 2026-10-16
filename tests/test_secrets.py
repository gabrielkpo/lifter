"""Secrets never show in a repr or in a variable dbt could print (audit of 2026-10-16, M2)."""

import os

from lifter.config import Settings

SECRETS = {
    "DATABASE_URL": "postgresql://lifter:db-secret-1@db.example/lifter",
    "BENCH_DATABASE_URL": "postgresql://lifter:db-secret-2@localhost/lifter_bench",
    "GARMIN_MCP_TOKEN": "mcp-secret-3",
    "MISTRAL_API_KEY": "mistral-secret-4",
}


def test_settings_keep_secrets_out_of_their_repr():
    settings = Settings.from_env(SECRETS)
    assert settings.mistral_api_key == "mistral-secret-4"
    text = repr(settings)
    assert not any(secret in text for secret in ("secret-1", "secret-2", "secret-3", "secret-4"))
    assert "garmin_mcp_url" in text  # the rest is still there for debugging


def test_the_planner_keeps_its_key_out_of_its_repr(monkeypatch):
    from lifter.agents.planner import MistralPlanner

    class FakeChat:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, schema, include_raw):
            return object()

    monkeypatch.setattr("langchain_mistralai.ChatMistralAI", FakeChat)
    planner = MistralPlanner(api_key="mistral-secret-4", model="m")
    assert "mistral-secret-4" not in repr(planner)


def test_the_dbt_password_is_a_secret_variable_for_the_run_only(monkeypatch):
    from lifter import transform

    class Info:
        host, port, user, password, dbname = "h", 5432, "u", "db-secret-5", "d"

        def get_parameters(self):
            return {"sslmode": "require"}

    class Conn:
        info = Info()

    monkeypatch.delenv(transform.SECRET_PASSWORD, raising=False)
    with transform._profile_env(Conn(), "analytics"):
        assert os.environ[transform.SECRET_PASSWORD] == "db-secret-5"
        assert transform.SECRET_PASSWORD.startswith("DBT_ENV_SECRET_")  # scrubbed by dbt
        assert "db-secret-5" not in {v for k, v in os.environ.items() if "SECRET" not in k}
    assert transform.SECRET_PASSWORD not in os.environ
