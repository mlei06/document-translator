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

from sqlalchemy.exc import IntegrityError

from doctranslator_server.auth.passwords import hash_password, verify_password
from doctranslator_server.db import Database
from doctranslator_server.db.models import ApiKey, utcnow
from doctranslator_server.db.repositories import users as repo
from doctranslator_server.jobs.errors import ConflictError

__all__ = [
    "SESSION_ABSOLUTE",
    "SESSION_IDLE",
    "AuthenticationError",
    "Authenticator",
    "CsrfError",
    "IssuedKey",
    "KeyInfo",
    "NewSession",
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
SESSION_IDLE = timedelta(minutes=30)
SESSION_ABSOLUTE = timedelta(hours=12)
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuthenticationError(Exception):
    """Missing, malformed, unknown or revoked credential, or a disabled user (one outcome)."""


class UserNotFoundError(Exception):
    pass


class CsrfError(Exception):
    """A cookie-authenticated change without a matching CSRF token or from another origin."""


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. ``user_id`` is the only owner source (ADR-015)."""

    user_id: str
    display_name: str
    kind: str


@dataclass(frozen=True, slots=True)
class NewSession:
    """A signed-in browser session: ``token`` goes in the cookie, ``csrf`` to the page."""

    principal: Principal
    session_id: str
    token: str
    csrf: str
    expires_at: datetime


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
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _csrf_of(token: str) -> str:
    """A session's CSRF token, derived one-way from its cookie token so any tab of the signed-in
    page can recover it from ``GET /v1/sessions/current`` (it proves the same-origin page)."""
    raw = hashlib.sha256(b"doctranslator-csrf:" + token.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


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
        principal, _ = self._key(authorization.removeprefix("Bearer ").strip())
        return principal

    def _key(self, value: str) -> tuple[Principal, str]:
        """Validate an API key; returns the principal and the key's ID."""
        match = _KEY.match(value)
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
            key_id = key.id
        if principal is None:
            raise AuthenticationError
        return principal, key_id

    # Browser sessions (ADR-017)

    def start_session(self, key: str) -> NewSession:
        """Exchange a valid API key for a new browser session (the key is not kept)."""
        principal, key_id = self._key(key.strip())
        return self._start_session(principal, key_id)

    def _start_session(self, principal: Principal, key_id: str | None = None) -> NewSession:
        token = secrets.token_urlsafe(32)
        csrf = _csrf_of(token)
        now = utcnow()
        expires = now + SESSION_ABSOLUTE
        with self._db.session() as session:
            user = repo.get_user(session, principal.user_id)
            if user is None or not user.active:
                raise AuthenticationError
            row = repo.add_session(
                session,
                token_digest=_digest(token),
                csrf_digest=_digest(csrf),
                user_id=principal.user_id,
                api_key_id=key_id,
                created_at=now,
                last_seen_at=now,
                expires_at=expires,
            )
            repo.audit(
                session,
                "session_started",
                actor=principal.user_id,
                target_type="session",
                target_id=row.id,
            )
            session_id = row.id
        return NewSession(principal, session_id, token, csrf, expires)

    def register(self, email: str, password: str, display_name: str | None) -> NewSession:
        encoded = hash_password(password)
        try:
            with self._db.session() as session:
                user = repo.add_user(session, display_name or email.split("@", 1)[0], "human")
                user.email = email
                user.password_hash = encoded
                session.flush()
                principal = Principal(user.id, user.display_name, user.kind)
                repo.audit(
                    session,
                    "account_registered",
                    actor=user.id,
                    target_type="user",
                    target_id=user.id,
                )
        except IntegrityError:
            raise ConflictError(
                "Unable to create an account with these details", code="account_unavailable"
            ) from None
        return self._start_session(principal)

    def password_session(self, email: str, password: str) -> NewSession:
        with self._db.session() as session:
            user = repo.user_by_email(session, email)
            encoded = user.password_hash if user is not None else None
            principal = (
                Principal(user.id, user.display_name, user.kind) if user is not None else None
            )
        valid = verify_password(password, encoded)
        if not valid or principal is None or principal.kind != "human":
            raise AuthenticationError
        return self._start_session(principal)

    def from_session(
        self, token: str, *, method: str, csrf: str | None, origin: str | None, own_origin: str
    ) -> tuple[Principal, str]:
        """The principal for a session cookie; state-changing requests need the CSRF token and a
        same-origin ``Origin`` (when sent). Returns the principal and the session ID."""
        now = utcnow()
        with self._db.session() as session:
            found = repo.session_by_digest(session, _digest(token))
            if found is None:
                raise AuthenticationError
            row, key, user = found
            if (
                row.revoked_at is not None
                or row.expires_at <= now
                or now - row.last_seen_at >= SESSION_IDLE
                or (row.api_key_id is not None and (key is None or key.revoked_at is not None))
                or not user.active
            ):
                raise AuthenticationError
            if method.upper() in _UNSAFE_METHODS:
                if csrf is None or not hmac.compare_digest(row.csrf_digest, _digest(csrf)):
                    raise CsrfError
                if origin is not None and origin.rstrip("/") != own_origin.rstrip("/"):
                    raise CsrfError
            if now - row.last_seen_at >= _TOUCH_INTERVAL:
                repo.touch_session(session, row.id, now)
            return Principal(user.id, user.display_name, user.kind), row.id

    def session_csrf(self, token: str) -> tuple[str, datetime]:
        """The CSRF token and absolute expiry of a valid session cookie (for a reloaded page)."""
        with self._db.session() as session:
            found = repo.session_by_digest(session, _digest(token))
            if found is None:
                raise AuthenticationError
            csrf = _csrf_of(token)
            if not hmac.compare_digest(found[0].csrf_digest, _digest(csrf)):
                # Older releases used a random CSRF token that cannot be recovered from its
                # stored digest. Require sign-in instead of returning a token mutations reject.
                raise AuthenticationError
            return csrf, found[0].expires_at

    def end_session(self, session_id: str) -> None:
        with self._db.session() as session:
            repo.revoke_session(session, session_id, utcnow())


def create_user(db: Database, display_name: str, kind: str = "human") -> UserInfo:
    if kind not in ("human", "service"):
        raise ValueError("kind must be human or service")
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
