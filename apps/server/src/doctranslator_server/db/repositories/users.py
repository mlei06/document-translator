"""Users, API keys, audit events and named locks."""

from datetime import datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from doctranslator_server.db.models import ApiKey, AuditEvent, Lock, User
from doctranslator_server.db.models import Session as SessionRow
from doctranslator_server.db.repositories._rows import rowcount

__all__ = [
    "acquire_lock",
    "add_key",
    "add_session",
    "add_user",
    "audit",
    "get_user",
    "key_by_prefix",
    "keys_of",
    "list_users",
    "release_lock",
    "revoke_key",
    "revoke_session",
    "session_by_digest",
    "set_active",
    "touch_key",
    "touch_session",
]


def add_user(session: Session, display_name: str, kind: str) -> User:
    user = User(display_name=display_name, kind=kind)
    session.add(user)
    session.flush()
    return user


def get_user(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.created_at)))


def set_active(session: Session, user_id: str, active: bool, now: datetime) -> bool:
    result = session.execute(
        update(User)
        .where(User.id == user_id)
        .values(active=active, disabled_at=None if active else now)
    )
    return rowcount(result) == 1


def add_key(session: Session, user_id: str, prefix: str, digest: str, label: str) -> ApiKey:
    key = ApiKey(user_id=user_id, prefix=prefix, digest=digest, label=label)
    session.add(key)
    session.flush()
    return key


def key_by_prefix(session: Session, prefix: str) -> tuple[ApiKey, User] | None:
    row = session.execute(
        select(ApiKey, User).join(User, User.id == ApiKey.user_id).where(ApiKey.prefix == prefix)
    ).first()
    return None if row is None else (row[0], row[1])


def keys_of(session: Session, user_id: str) -> list[ApiKey]:
    return list(
        session.scalars(select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at))
    )


def revoke_key(session: Session, key_id: str, now: datetime) -> bool:
    result = session.execute(
        update(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return rowcount(result) == 1


def touch_key(session: Session, key_id: str, now: datetime) -> None:
    session.execute(update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=now))


def audit(
    session: Session,
    action: str,
    *,
    actor: str | None,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: str = "ok",
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
        )
    )


def acquire_lock(session: Session, name: str, holder: str, until: datetime, now: datetime) -> bool:
    """Take or renew the named lease; ``False`` while another holder's lease is live."""
    result = session.execute(
        update(Lock)
        .where(Lock.name == name, (Lock.until <= now) | (Lock.holder == holder))
        .values(holder=holder, until=until)
    )
    if rowcount(result) == 1:
        return True
    if session.get(Lock, name) is not None:
        return False
    try:
        with session.begin_nested():
            session.execute(insert(Lock).values(name=name, holder=holder, until=until))
    except IntegrityError:
        return False
    return True


def release_lock(session: Session, name: str, holder: str) -> None:
    session.execute(delete(Lock).where(Lock.name == name, Lock.holder == holder))


def add_session(session: Session, **fields: object) -> SessionRow:
    row = SessionRow(**fields)
    session.add(row)
    session.flush()
    return row


def session_by_digest(session: Session, digest: str) -> tuple[SessionRow, ApiKey, User] | None:
    row = session.execute(
        select(SessionRow, ApiKey, User)
        .join(ApiKey, ApiKey.id == SessionRow.api_key_id)
        .join(User, User.id == SessionRow.user_id)
        .where(SessionRow.token_digest == digest)
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def touch_session(session: Session, session_id: str, now: datetime) -> None:
    session.execute(update(SessionRow).where(SessionRow.id == session_id).values(last_seen_at=now))


def revoke_session(session: Session, session_id: str, now: datetime) -> None:
    session.execute(
        update(SessionRow)
        .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )
