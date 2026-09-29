"""Engine identities, fingerprints and translators for the service (ADR-011 identity, ADR-016).

The web process prepares each available mode's identity from configuration alone (no model load)
and fingerprints submissions with it. Workers create one ``Translator`` per mode, reuse it between
jobs and check that the loaded identity still matches before translating.
"""

import contextlib
import logging
from typing import Protocol

from pydantic import ValidationError

from doctranslator_core import Translator, build_font_manifest, output_fingerprint, prepare_identity
from doctranslator_core.types import (
    DocumentTranslationOptions,
    FontManifest,
    TranslationIdentity,
    TranslationMode,
)
from doctranslator_server.settings import ServerSettings

__all__ = ["EngineCatalog", "EngineIdentities", "load_font_manifest"]

logger = logging.getLogger(__name__)


def load_font_manifest(settings: ServerSettings) -> FontManifest:
    """The provisioned font manifest, reusing entries of unchanged files from the cache."""
    cache = settings.data_dir / "font-manifest.json"
    previous: FontManifest | None = None
    with contextlib.suppress(OSError, ValidationError, ValueError):
        previous = FontManifest.model_validate_json(cache.read_text(encoding="utf-8"))
    manifest = build_font_manifest(settings.font_directories(), previous=previous)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        temporary.write_text(manifest.model_dump_json(), encoding="utf-8")
        temporary.replace(cache)
    except OSError as exc:
        logger.warning("font manifest cache not written: %s", exc.strerror)
    return manifest


class EngineIdentities(Protocol):
    """What submission needs: the available modes and metadata-only fingerprints."""

    @property
    def modes(self) -> list[TranslationMode]: ...

    def fingerprint(self, mode: TranslationMode, options: DocumentTranslationOptions) -> str: ...

    def close(self) -> None: ...


class EngineCatalog:
    def __init__(self, settings: ServerSettings, fonts: FontManifest) -> None:
        self._settings = settings
        self.fonts = fonts
        self._identities: dict[TranslationMode, TranslationIdentity] = {}
        for mode in settings.available_modes():
            self._identities[mode] = prepare_identity(settings.engine_config(mode))
        self._translators: dict[TranslationMode, Translator] = {}

    @property
    def modes(self) -> list[TranslationMode]:
        return list(self._identities)

    def fingerprint(self, mode: TranslationMode, options: DocumentTranslationOptions) -> str:
        return output_fingerprint(self._identities[mode], options, self.fonts)

    def translator(self, mode: TranslationMode) -> Translator:
        """The worker's translator for ``mode``, created once (MT loads its model here)."""
        translator = self._translators.get(mode)
        if translator is None:
            config = self._settings.engine_config(mode)
            translator = Translator(config, fonts=self.fonts)
            self._translators[mode] = translator
        return translator

    def loaded_fingerprint(
        self, translator: Translator, options: DocumentTranslationOptions
    ) -> str:
        return output_fingerprint(translator.identity, options, self.fonts)

    def close(self) -> None:
        for translator in self._translators.values():
            translator.close()
        self._translators.clear()
