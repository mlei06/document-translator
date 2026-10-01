"""API keys and user administration (ADR-015)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from support.server import FakeEngines, make_services, server_settings

from doctranslator_server import auth
from doctranslator_server.app import Services, migrate
from doctranslator_server.db import Database, MigrationRequiredError
from doctranslator_server.db.models import ApiKey, AuditEvent


@pytest.fixture
def services(tmp_path: Path) -> Iterator[Services]:
    services = make_services(server_settings(tmp_path), FakeEngines())
    yield services
    services.close()


def test_keys_are_stored_as_digests_and_shown_once(services: Services) -> None:
    user = auth.create_user(services.db, "Alice")
    issued = auth.create_key(services.db, user.id, "laptop")
    assert issued.secret.startswith(f"dt_{issued.info.prefix}_")
    assert len(issued.secret) == 3 + 12 + 1 + 43
    with services.db.session() as session:
        stored = session.get(ApiKey, issued.info.id)
        assert stored is not None
        assert issued.secret.split("_")[-1] not in (stored.digest, stored.prefix, stored.label)
    principal = services.auth.authenticate(f"Bearer {issued.secret}")
    assert principal.user_id == user.id


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Bearer dt_", "Token abc", "Bearer dt_aaaaaaaaaaaa_short"],
)
def test_malformed_credentials_fail(services: Services, header: str | None) -> None:
    with pytest.raises(auth.AuthenticationError):
        services.auth.authenticate(header)


def test_revoked_keys_and_disabled_users_fail_and_are_audited(services: Services) -> None:
    user = auth.create_user(services.db, "Alice")
    first = auth.create_key(services.db, user.id)
    second = auth.create_key(services.db, user.id)  # rotation overlap: both work
    services.auth.authenticate(f"Bearer {first.secret}")
    services.auth.authenticate(f"Bearer {second.secret}")
    assert auth.revoke_key(services.db, first.info.id) is True
    assert auth.revoke_key(services.db, first.info.id) is False
    with pytest.raises(auth.AuthenticationError):
        services.auth.authenticate(f"Bearer {first.secret}")
    services.auth.authenticate(f"Bearer {second.secret}")
    auth.set_user_active(services.db, user.id, active=False)
    with pytest.raises(auth.AuthenticationError):
        services.auth.authenticate(f"Bearer {second.secret}")
    auth.set_user_active(services.db, user.id, active=True)
    services.auth.authenticate(f"Bearer {second.secret}")
    with services.db.session() as session:
        actions = [e.action for e in session.query(AuditEvent).order_by(AuditEvent.id)]
    assert actions.count("auth_failed") == 2
    assert {"user_created", "key_created", "key_revoked", "user_disabled", "user_enabled"} <= set(
        actions
    )


def test_unknown_user_operations_fail(services: Services) -> None:
    with pytest.raises(auth.UserNotFoundError):
        auth.create_key(services.db, "00000000-0000-0000-0000-000000000000")
    with pytest.raises(auth.UserNotFoundError):
        auth.set_user_active(services.db, "00000000-0000-0000-0000-000000000000", active=False)


def test_services_refuse_an_unmigrated_database(tmp_path: Path) -> None:
    settings = server_settings(tmp_path)
    database = Database(settings.database)
    try:
        with pytest.raises(MigrationRequiredError):
            database.require_current()
        assert migrate(settings) == "0007"
        database.require_current()
    finally:
        database.dispose()
