"""Authentication and user administration (ADR-015): per-user opaque API keys.

A key is ``dt_<prefix>_<secret>``; only SHA-256 of the 256-bit secret is stored. Every failure
looks the same to the caller. Nothing here logs or returns a secret after creation.
"""

import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from doctranslator_server.db import Database
from doctranslator_server.db.models import ApiKey, utcnow
from doctranslator_server.db.repositories import users as repo

__all__ = [
    "AuthenticationError",
    "Authenticator",
    "IssuedKey",
    "KeyInfo",
    "Principal",
    "UserInfo",
    "UserNotFoundError",
    "create_key",
    "create_user",
    "list_keys",
    "list_users",
    "revoke_key",
    "set_user_active",
]

logger = logging.getLogger(__name__)

_KEY = re.compile(r"^dt_([a-z2-7]{12})_([A-Za-z0-9_-]{43})$")
_TOUCH_INTERVAL = timedelta(minutes=1)


class AuthenticationError(Exception):
    """Missing, malformed, unknown or revoked credential, or a disabled user (one outcome)."""


class UserNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. ``user_id`` is the only owner source (ADR-015)."""

    user_id: str
    display_name: str
    kind: str


@dataclass(frozen=True, slots=True)
class UserInfo:
    id: str
    display_name: str
    kind: str
    active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class KeyInfo:
    id: str
    prefix: str
    label: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedKey:
    """A new key: ``secret`` is shown once and never stored."""

    info: KeyInfo
    secret: str


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def _new_key() -> tuple[str, str, str]:
    prefix = base64.b32encode(secrets.token_bytes(10)).decode("ascii").lower()[:12]
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    return f"dt_{prefix}_{secret}", prefix, secret


def _key_info(key: ApiKey) -> KeyInfo:
    return KeyInfo(key.id, key.prefix, key.label, key.created_at, key.last_used_at, key.revoked_at)


class Authenticator:
    def __init__(self, db: Database) -> None:
        self._db = db

    def authenticate(self, authorization: str | None) -> Principal:
        """The principal for an ``Authorization`` header value, or ``AuthenticationError``."""
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError
        match = _KEY.match(authorization.removeprefix("Bearer ").strip())
        if match is None:
            raise AuthenticationError
        prefix, secret = match.groups()
        now = utcnow()
        principal: Principal | None = None
        with self._db.session() as session:
            found = repo.key_by_prefix(session, prefix)
            if found is None:
                raise AuthenticationError
            key, user = found
            valid = hmac.compare_digest(key.digest, _digest(secret))
            if valid and key.revoked_at is None and user.active:
                if key.last_used_at is None or now - key.last_used_at >= _TOUCH_INTERVAL:
                    repo.touch_key(session, key.id, now)
                principal = Principal(user.id, user.display_name, user.kind)
            else:  # committed with the session; the caller learns only "not authenticated"
                repo.audit(
                    session, "auth_failed", actor=None, target_type="api_key", target_id=key.id
                )
        if principal is None:
            raise AuthenticationError
        return principal


def create_user(db: Database, display_name: str, kind: str = "person") -> UserInfo:
    if kind not in ("person", "service"):
        raise ValueError("kind must be person or service")
    with db.session() as session:
        user = repo.add_user(session, display_name, kind)
        repo.audit(session, "user_created", actor=None, target_type="user", target_id=user.id)
        return UserInfo(user.id, user.display_name, user.kind, user.active, user.created_at)


def list_users(db: Database) -> list[UserInfo]:
    with db.session() as session:
        return [
            UserInfo(u.id, u.display_name, u.kind, u.active, u.created_at)
            for u in repo.list_users(session)
        ]


def set_user_active(db: Database, user_id: str, active: bool) -> None:
    """Enable or disable a user. Disabling blocks every key at once; jobs are cancelled by the
    job service (``jobs.cancel_user_jobs``), and a worker cannot publish for a disabled user."""
    with db.session() as session:
        if not repo.set_active(session, user_id, active, utcnow()):
            raise UserNotFoundError(user_id)
        action = "user_enabled" if active else "user_disabled"
        repo.audit(session, action, actor=None, target_type="user", target_id=user_id)


def create_key(db: Database, user_id: str, label: str = "") -> IssuedKey:
    secret_key, prefix, secret = _new_key()
    with db.session() as session:
        if repo.get_user(session, user_id) is None:
            raise UserNotFoundError(user_id)
        key = repo.add_key(session, user_id, prefix, _digest(secret), label)
        repo.audit(session, "key_created", actor=None, target_type="api_key", target_id=key.id)
        return IssuedKey(_key_info(key), secret_key)


def list_keys(db: Database, user_id: str) -> list[KeyInfo]:
    with db.session() as session:
        return [_key_info(k) for k in repo.keys_of(session, user_id)]


def revoke_key(db: Database, key_id: str) -> bool:
    with db.session() as session:
        revoked = repo.revoke_key(session, key_id, utcnow())
        if revoked:
            repo.audit(session, "key_revoked", actor=None, target_type="api_key", target_id=key_id)
        return revoked
