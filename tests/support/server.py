"""Server test helpers: settings on a temporary data directory, a deterministic engine that runs
the real core pipeline with the fake translator, and user/key provisioning."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from doctranslator_core import DocumentLimits
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import (
    DocumentTranslationOptions,
    DocumentTranslationResult,
    FontManifest,
    TranslationMode,
    TranslationProgress,
)
from doctranslator_server import auth
from doctranslator_server.app import Services, build_services, migrate
from doctranslator_server.jobs.queue import Queue
from doctranslator_server.jobs.worker import Worker
from doctranslator_server.settings import ServerSettings
from support.fakes import FakeTranslator

__all__ = [
    "FakeEngines",
    "add_user",
    "make_queue",
    "make_services",
    "make_worker",
    "server_settings",
]


class FakeEngines:
    """Both modes, fingerprinted by a version string; translation through the real pipeline."""

    def __init__(
        self,
        version: str = "fake-1",
        *,
        before: Callable[[TranslationMode, Path], None] | None = None,
    ) -> None:
        self.version = version
        self.loaded_version = version
        self.before = before
        self.calls = 0
        self.translator = FakeTranslator()
        self.fonts: FontManifest | None = None
        """Font manifest for fit (``None``: changed containers are unresolved)."""

    @property
    def modes(self) -> list[TranslationMode]:
        return [TranslationMode.MT, TranslationMode.LLM]

    def _fingerprint(self, version: str, mode: TranslationMode, options: Any) -> str:
        payload = {"v": version, "mode": mode.value, "options": options.model_dump(mode="json")}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def fingerprint(self, mode: TranslationMode, options: DocumentTranslationOptions) -> str:
        """Submission side (metadata only)."""
        return self._fingerprint(self.version, mode, options)

    def close(self) -> None:
        pass

    # Worker side

    def translate(
        self,
        mode: TranslationMode,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool] | None = None,
    ) -> DocumentTranslationResult:
        self.calls += 1
        if self.before is not None:
            self.before(mode, source)
        return translate_document(
            self.translator,
            source,
            output,
            options=options,
            fingerprint=self._fingerprint(self.loaded_version, mode, options),
            limits=DocumentLimits(),
            on_progress=on_progress,
            fonts=self.fonts,
            should_skip_fit=should_skip_fit,
        )


class _Runner:
    """The worker's view of ``FakeEngines``: fingerprints from the loaded version."""

    def __init__(self, engines: FakeEngines) -> None:
        self._engines = engines

    def fingerprint(self, mode: TranslationMode, options: DocumentTranslationOptions) -> str:
        return self._engines._fingerprint(self._engines.loaded_version, mode, options)  # pyright: ignore[reportPrivateUsage]

    def translate(
        self,
        mode: TranslationMode,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool],
    ) -> DocumentTranslationResult:
        return self._engines.translate(mode, source, output, options, on_progress, should_skip_fit)


def server_settings(tmp_path: Path, **overrides: Any) -> ServerSettings:
    values: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "database_url": None,
        "workers": 0,
        "retry_delays_s": (0.0, 0.0),
        "mt_model_dir": None,
        "llm_base_url": None,
        "llm_api_key": None,
        "llm_model": None,
        "font_dirs": str(tmp_path / "no-fonts"),
    }
    values.update(overrides)
    return ServerSettings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def make_services(settings: ServerSettings, engines: FakeEngines) -> Services:
    migrate(settings)
    return build_services(settings, catalog=engines)


def make_queue(services: Services, clock: Callable[[], datetime] | None = None) -> Queue:
    settings = services.settings
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    return Queue(
        services.db,
        lease=timedelta(seconds=settings.lease_s),
        retry_delays=settings.retry_delays_s,
        temporary_retention=timedelta(hours=settings.temporary_retention_hours),
        superseded_retention=timedelta(days=settings.superseded_retention_days),
        **kwargs,
    )


def make_worker(
    services: Services, engines: FakeEngines, queue: Queue | None = None, worker_id: str = "w1"
) -> Worker:
    return Worker(
        services.settings,
        services.db,
        services.store,
        queue or make_queue(services),
        _Runner(engines),
        worker_id=worker_id,
    )


def add_user(services: Services, name: str = "Alice") -> tuple[str, dict[str, str]]:
    """A new user and the ``Authorization`` header for a fresh key."""
    user = auth.create_user(services.db, name)
    key = auth.create_key(services.db, user.id, "test")
    return user.id, {"Authorization": f"Bearer {key.secret}"}
