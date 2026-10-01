"""Shared worker adapter that pins a managed local runtime for a document attempt."""

from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

from doctranslator_core.types import (
    DocumentDetection,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    TranslationProgress,
)
from doctranslator_server.jobs.desktop_runtime import ManagedLlama
from doctranslator_server.jobs.engines import EngineCatalog


class DesktopRunner:
    def __init__(self, catalog: EngineCatalog, runtime: ManagedLlama | None) -> None:
        self.catalog = catalog
        self.runtime = runtime

    def available(self) -> set[str]:
        return {entry.id for entry in self.catalog.translators}

    def fingerprint(self, mode: str, options: DocumentTranslationOptions) -> str:
        return self.catalog.fingerprint(mode, options)

    def translate(
        self,
        mode: str,
        source: Path,
        output: Path,
        options: DocumentTranslationOptions,
        on_progress: Callable[[TranslationProgress], None],
        should_skip_fit: Callable[[], bool],
        *,
        detection_metadata: DocumentDetection | None = None,
    ) -> DocumentTranslationResult:
        scope = self.runtime.pin() if mode == "hy-mt-local" and self.runtime else nullcontext()
        with scope:
            return self.catalog.translator(mode).translate_document(
                source,
                output,
                options=options,
                on_progress=on_progress,
                should_skip_fit=should_skip_fit,
                detection_metadata=detection_metadata,
            )
