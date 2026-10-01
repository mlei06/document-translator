"""Explicit test-only loopback service: real API/storage/worker/core, deterministic translator.

Never import this entry point in production. Test credentials live only in this process.
"""

import sys
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import uvicorn
from starlette.requests import Request
from starlette.responses import Response

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))

from support.server import (  # noqa: E402
    FakeEngines,
    add_user,
    make_services,
    make_worker,
    server_settings,
)

from doctranslator_core.types import (  # noqa: E402
    DocumentDetection,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    TranslationMode,
    TranslationProgress,
)
from doctranslator_server.app import create_app  # noqa: E402
from doctranslator_server.jobs.engines import TranslatorInfo  # noqa: E402


class BrowserEngines(FakeEngines):
    @property
    def translators(self) -> list[TranslatorInfo]:
        return [
            *super().translators,
            TranslatorInfo("small100-beam4", "SMALL-100 beam 4", TranslationMode.MT, "server"),
            TranslatorInfo("small100-greedy", "SMALL-100 greedy", TranslationMode.MT, "server"),
            TranslatorInfo("gemma", "Gemma", TranslationMode.MT, "server"),
        ]

    def translate(
        self,
        mode: str,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool] | None = None,
        *,
        detection_metadata: DocumentDetection | None = None,
    ) -> DocumentTranslationResult:
        def progress(event: TranslationProgress) -> None:
            on_progress(event)
            if event.phase.value == "fit" and event.done == 0:
                # A deterministic control window, not simulated production progress.
                end = time.monotonic() + 5
                while time.monotonic() < end:
                    if should_skip_fit and should_skip_fit():
                        break
                    time.sleep(0.1)
            elif event.phase.value == "translate" and event.done == 0:
                time.sleep(0.3)

        return super().translate(
            mode,
            source,
            output,
            options,
            progress,
            should_skip_fit,
            detection_metadata=detection_metadata,
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="doctranslator-browser-") as temporary:
        engines = BrowserEngines()
        settings = server_settings(
            Path(temporary),
            web_dir=ROOT / "apps/web/dist",
            poll_s=0.1,
            registration_enabled=True,
            default_translator_id="gemma",
            web_translation_policy={
                "revision": "web-auto-v2",
                "davy_order": [
                    "gemma",
                    "nemotron-3-ultra",
                    "nemotron-3-super-120b",
                    "gpt-oss-120b-thinking",
                    "gpt-oss-120b",
                    "laguna-s-2.1",
                ],
                "local_translator_id": "hy-mt-local",
            },
            translators=[
                {
                    "id": "gemma",
                    "label": "Gemma",
                    "engine": {
                        "mode": "llm",
                        "base_url": "http://127.0.0.1:1/v1",
                        "api_key": "test-only",
                        "model": "gemma-4-31b-it",
                        "deployment_revision": "browser-test",
                    },
                },
                {
                    "id": "hy-mt-local",
                    "label": "HY-MT",
                    "engine": {
                        "mode": "llm",
                        "base_url": "http://127.0.0.1:1/v1",
                        "api_key": "test-only",
                        "model": "HY-MT",
                        "protocol": "hy-mt",
                        "execution_location": "server",
                        "deployment_revision": "browser-test",
                    },
                },
            ],
        )
        services = make_services(settings, engines)
        credentials: dict[str, dict[str, str]] = {}
        app = create_app(services)

        @app.middleware("http")
        async def isolate_browser_client(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            # Each browser test is a separate client. Keep the real per-client limiter,
            # without letting earlier scenarios consume the next scenario's allowance.
            if client := request.headers.get("x-test-client"):
                request.scope["client"] = (client, 0)
            return await call_next(request)

        @app.get("/test/credentials")
        def test_credentials(scope: str = "default") -> dict[str, str]:
            if scope not in credentials:
                credentials[scope] = {
                    name: add_user(services, name)[1]["Authorization"].removeprefix("Bearer ")
                    for name in ("Alice", "Bob")
                }
            return credentials[scope]

        app.router.routes.insert(0, app.router.routes.pop())

        worker = make_worker(services, engines)
        stop = threading.Event()
        thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
        thread.start()
        try:
            uvicorn.run(app, host="127.0.0.1", port=8876, log_level="warning")
        finally:
            stop.set()
            thread.join(timeout=10)
            services.db.dispose()


if __name__ == "__main__":
    main()
