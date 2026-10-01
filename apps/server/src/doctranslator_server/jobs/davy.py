"""Cached, secret-safe Davy model discovery. Never sends document text or inference requests."""

import ssl
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
import truststore
from pydantic import BaseModel, Field

from doctranslator_server.settings import ServerSettings

type DavyStatus = Literal[
    "not_configured", "available", "unreachable", "authentication_failed", "no_models", "error"
]


@dataclass(frozen=True)
class DavyState:
    status: DavyStatus = "not_configured"
    message: str = "Davy isn't configured."
    checked_at: datetime | None = None


class _Model(BaseModel):
    id: str = Field(min_length=1, strict=True)


class _Models(BaseModel):
    data: list[_Model]


class DavyDiscovery:
    def __init__(self, settings: ServerSettings, *, transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._transport = transport
        self._lock = threading.Lock()
        self._state = DavyState()
        self._models: frozenset[str] = frozenset()
        self._checked = float("-inf")

    def snapshot(self, *, force: bool = False) -> tuple[DavyState, frozenset[str]]:
        with self._lock:
            if not (
                self._settings.davy_base_url
                and self._settings.davy_api_key
                and self._settings.davy_api_key.get_secret_value().strip()
            ):
                return self._state, self._models
            if time.monotonic() - self._checked < (5 if force else 60):
                return self._state, self._models
            self._state, self._models = self._fetch()
            self._checked = time.monotonic()
            return self._state, self._models

    def _fetch(self) -> tuple[DavyState, frozenset[str]]:
        checked = datetime.now(UTC)

        def failed(status: DavyStatus, message: str) -> tuple[DavyState, frozenset[str]]:
            return DavyState(status, message, checked), frozenset()

        key = self._settings.davy_api_key
        if key is None:
            return DavyState(), frozenset()
        try:
            with httpx.Client(
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                transport=self._transport,
                timeout=5.0,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    str(self._settings.davy_base_url).rstrip("/") + "/models",
                    headers={"Authorization": "Bearer " + key.get_secret_value()},
                )
            if response.status_code in (401, 403):
                return failed("authentication_failed", "Davy rejected the API credentials.")
            if response.status_code >= 500:
                return failed("unreachable", "Can't reach Davy. Check your network or VPN.")
            if response.status_code != 200:
                return failed("error", "Davy model discovery failed.")
            payload = _Models.model_validate_json(response.content)
            models = frozenset(item.id for item in payload.data)
            approved = {entry.model for entry in self._settings.davy_models if entry.enabled}
            if not models.intersection(approved):
                return failed(
                    "no_models", "No configured translation models are available on Davy."
                )
            return DavyState("available", "Davy is connected.", checked), models
        except httpx.RequestError:
            return failed("unreachable", "Can't reach Davy. Check your network or VPN.")
        except ValueError, UnicodeDecodeError:
            return failed("error", "Davy returned an invalid model list.")
