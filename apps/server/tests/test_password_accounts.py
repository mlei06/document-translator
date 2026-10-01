"""Password account HTTP lifecycle and ownership, alongside existing API keys."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from support.server import FakeEngines, make_services, server_settings

from doctranslator_server import auth
from doctranslator_server.app import create_app
from doctranslator_server.db.models import ApiKey, User

PASSWORD = "Test123!"  # noqa: S105 - deterministic test credential


def test_register_login_logout_and_disable(tmp_path: Path) -> None:
    services = make_services(server_settings(tmp_path, registration_enabled=True), FakeEngines())
    try:
        with TestClient(create_app(services)) as client:
            created = client.post(
                "/v1/accounts", json={"email": " Person@Example.COM ", "password": PASSWORD}
            )
            assert created.status_code == 201, created.text
            account = created.json()
            user_id = account["user"]["id"]
            assert "httponly" in created.headers["set-cookie"].lower()
            assert client.get("/v1/sessions/current").status_code == 200
            csrf = {"X-CSRF-Token": account["csrf_token"]}
            assert client.delete("/v1/sessions/current", headers=csrf).status_code == 204
            assert client.get("/v1/me").status_code == 401
            wrong = client.post(
                "/v1/sessions", json={"email": "person@example.com", "password": "wrong"}
            )
            unknown = client.post(
                "/v1/sessions", json={"email": "missing@example.com", "password": "wrong"}
            )
            assert wrong.status_code == unknown.status_code == 401
            assert wrong.json()["message"] == unknown.json()["message"]
            login = client.post(
                "/v1/sessions", json={"email": "PERSON@example.com", "password": PASSWORD}
            )
            assert login.status_code == 201 and login.json()["user"]["id"] == user_id
            assert (
                client.post(
                    "/v1/batches", json={"idempotency_key": "00000000-0000-0000-0000-000000000001"}
                ).status_code
                == 403
            )
            duplicate = client.post(
                "/v1/accounts", json={"email": "person@example.com", "password": PASSWORD}
            )
            assert duplicate.status_code == 409
            with services.db.session() as session:
                user = session.get(User, user_id)
                assert user is not None and user.email == "person@example.com"
                assert user.password_hash is not None and user.password_hash.startswith(
                    "scrypt-v1$"
                )
                assert PASSWORD not in user.password_hash
                assert session.scalar(select(ApiKey)) is None
            auth.set_user_active(services.db, user_id, False)
            assert client.get("/v1/me").status_code == 401
            assert (
                client.post(
                    "/v1/sessions", json={"email": "person@example.com", "password": PASSWORD}
                ).status_code
                == 401
            )
    finally:
        services.close()


def test_registration_flag_origin_validation_and_limiter(tmp_path: Path) -> None:
    settings = server_settings(tmp_path, registration_enabled=False)
    services = make_services(settings, FakeEngines())
    try:
        with TestClient(create_app(services)) as client:
            assert (
                client.post(
                    "/v1/accounts", json={"email": "a@example.com", "password": PASSWORD}
                ).status_code
                == 404
            )
        settings.registration_enabled = True
        with TestClient(create_app(services)) as client:
            assert (
                client.post(
                    "/v1/accounts",
                    json={"email": "a@example.com", "password": PASSWORD},
                    headers={"Origin": "https://attacker.example"},
                ).status_code
                == 403
            )
            bad = client.post(
                "/v1/accounts", json={"email": "a@example.com", "password": "short12"}
            )
            assert bad.status_code == 422 and "short12" not in bad.text
            for _ in range(10):
                assert client.post("/v1/sessions", json={"key": "wrong"}).status_code == 401
            assert client.post("/v1/sessions", json={"key": "wrong"}).status_code == 429
    finally:
        services.close()
