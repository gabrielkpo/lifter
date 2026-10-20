"""The API configured from the environment: token and host names when hosted (lifter.api.hosted)."""

import pytest
from fastapi.testclient import TestClient

from lifter.api.hosted import create_app_from_env

TOKEN = "test-token-not-a-secret"


def hosted_env(database_url, **extra):
    return {
        "DATABASE_URL": database_url,
        "VERCEL": "1",
        "VERCEL_URL": "lifter-api-abc123.vercel.app",
        "VERCEL_PROJECT_PRODUCTION_URL": "lifter-api.vercel.app",
        "LIFTER_API_TOKEN": TOKEN,
        **extra,
    }


def test_hosted_api_refuses_to_start_without_a_token(database_url):
    with pytest.raises(RuntimeError, match="LIFTER_API_TOKEN"):
        create_app_from_env(hosted_env(database_url, LIFTER_API_TOKEN=""))


def test_hosted_api_refuses_to_start_without_a_database_url(database_url):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app_from_env(hosted_env(database_url, DATABASE_URL=""))


def test_hosted_api_needs_the_token_on_every_request(conn, database_url):
    api = TestClient(
        create_app_from_env(hosted_env(database_url)), base_url="https://lifter-api.vercel.app"
    )

    assert api.get("/bests").status_code == 401
    assert api.get("/bests", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get("/bests", headers={"Authorization": TOKEN}).status_code == 401
    ok = api.get("/bests", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
    assert api.get("/docs").status_code == 401  # nothing is readable without the token
    # No browser or proxy keeps a copy of an answer, a refusal included.
    assert ok.headers["cache-control"] == "no-store"
    assert api.get("/bests").headers["cache-control"] == "no-store"


def test_hosted_api_answers_only_its_own_host_names(conn, database_url):
    api = TestClient(create_app_from_env(hosted_env(database_url)))
    auth = {"Authorization": f"Bearer {TOKEN}"}

    assert api.get("/bests", headers={**auth, "Host": "lifter-api-abc123.vercel.app"}).is_success
    assert api.get("/bests", headers={**auth, "Host": "other-app.vercel.app"}).status_code == 400


def test_hosted_api_allows_no_browser_origin_by_default(conn, database_url):
    api = TestClient(
        create_app_from_env(hosted_env(database_url)), base_url="https://lifter-api.vercel.app"
    )
    response = api.get(
        "/bests",
        headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://lifter-three.vercel.app"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_local_api_needs_no_token_and_allows_the_local_app(conn, database_url):
    api = TestClient(
        create_app_from_env({"DATABASE_URL": database_url}), base_url="http://127.0.0.1:8000"
    )
    response = api.get("/bests", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
