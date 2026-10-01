"""Ephemeral desktop authentication; no session credential is stored in the database."""

import hmac
import uuid

from doctranslator_server.auth import AuthenticationError, Authenticator, Principal
from doctranslator_server.db import Database
from doctranslator_server.db.models import User


class DesktopAuthenticator(Authenticator):
    def __init__(self, db: Database, sid: str, token: str) -> None:
        super().__init__(db)
        owner = str(uuid.uuid5(uuid.NAMESPACE_URL, f"doctranslator:windows:{sid}"))
        with db.session() as session:
            user = session.get(User, owner)
            if user is None:
                session.add(User(id=owner, display_name="This device", kind="human"))
            elif not user.active:
                raise AuthenticationError
        self._principal = Principal(owner, "This device", "human")
        self._authorization = f"Bearer {token}"

    def authenticate(self, authorization: str | None) -> Principal:
        if authorization is None or not hmac.compare_digest(
            authorization.encode(), self._authorization.encode()
        ):
            raise AuthenticationError
        return self._principal
