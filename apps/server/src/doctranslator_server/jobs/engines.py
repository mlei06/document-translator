"""Engine identities, fingerprints and translators for the service (ADR-011 identity, ADR-016).

The web process prepares configured translator identities without loading models. Workers load
selected translators lazily, bound retained local runtimes, and check the loaded identity before
translating. IDs choose configurations; output fingerprints determine compatible reuse.
"""

import contextlib
import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import ValidationError

from doctranslator_core import Translator, build_font_manifest, output_fingerprint, prepare_identity
from doctranslator_core.types import (
    DocumentTranslationOptions,
    EngineUnavailableError,
    FontManifest,
    TranslationIdentity,
    TranslationMode,
)
from doctranslator_server.jobs.davy import DavyDiscovery, DavyState
from doctranslator_server.jobs.errors import InvalidRequestError
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


@dataclass(frozen=True)
class TranslatorInfo:
    id: str
    label: str
    mode: TranslationMode
    location: Literal["server", "remote"]


def resolve_translator(
    entries: list[TranslatorInfo],
    default_id: str | None,
    translator_id: str | None,
    mode: str | None,
) -> TranslatorInfo:
    if translator_id is None and mode is None and default_id is not None:
        translator_id = default_id
    if not entries and translator_id is None:
        raise InvalidRequestError("no translation engine is configured", code="no_engine")
    if mode is not None and mode not in ("mt", "llm"):
        raise InvalidRequestError("unknown mode", code="invalid_options")
    if translator_id is not None:
        entry = next((entry for entry in entries if entry.id == translator_id), None)
        if entry is None:
            raise InvalidRequestError("translator is unavailable", code="translator_unavailable")
        if mode is not None and entry.mode.value != mode:
            raise InvalidRequestError("translator and mode conflict", code="invalid_options")
        return entry
    candidates = [entry for entry in entries if mode is None or entry.mode.value == mode]
    if not candidates:
        raise InvalidRequestError("mode is not available", code="mode_unavailable")
    return next((entry for entry in candidates if entry.id == default_id), candidates[0])


class EngineIdentities(Protocol):
    @property
    def modes(self) -> list[TranslationMode]: ...
    @property
    def translators(self) -> list[TranslatorInfo]: ...
    @property
    def default_translator_id(self) -> str | None: ...
    def discovery(self, *, force: bool = False) -> DavyState: ...
    def fingerprint(self, mode: str, options: DocumentTranslationOptions) -> str: ...
    def close(self) -> None: ...


class EngineCatalog:
    def __init__(self, settings: ServerSettings, fonts: FontManifest) -> None:
        self._settings = settings
        self.fonts = fonts
        self._davy = DavyDiscovery(settings)
        self._configs = {entry.id: entry for entry in settings.configured_translators()}
        self._identities: dict[str, TranslationIdentity] = {}
        for key, entry in self._configs.items():
            try:
                self._identities[key] = prepare_identity(entry.engine)
            except EngineUnavailableError, OSError:
                if entry.engine.mode != TranslationMode.MT:
                    raise
                logger.warning("Configured local translator %s is unavailable", key)
        self._translators: dict[str, Translator] = {}
        # In insertion/LRU order. One entry represents weights, not a decoding preset.
        self._local_groups: dict[tuple[str, ...], list[str]] = {}

    def _runtime_key(self, identifier: str) -> tuple[str, ...]:
        config = self._configs[identifier].engine
        if config.mode != TranslationMode.MT:
            raise ValueError("runtime keys require an MT configuration")
        identity = self._identities[identifier]
        return (
            str(config.model_dir.resolve()),
            config.model_dir.name,
            config.model_family,
            identity.details["artifact_sha256"],
            identity.details["device"],
            config.compute_type,
            str(config.cpu_threads),
        )

    def discovery(self, *, force: bool = False) -> DavyState:
        return self._davy.snapshot(force=force)[0]

    @property
    def translators(self) -> list[TranslatorInfo]:
        _, models = self._davy.snapshot()
        davy = {entry.id: entry.model for entry in self._settings.davy_models}
        return [
            TranslatorInfo(
                entry.id,
                entry.label,
                entry.engine.mode,
                "server"
                if entry.engine.mode == TranslationMode.MT
                else entry.engine.execution_location,
            )
            for entry in self._configs.values()
            if entry.id in self._identities and (entry.id not in davy or davy[entry.id] in models)
        ]

    @property
    def default_translator_id(self) -> str | None:
        return self._settings.default_translator_id or next(iter(self._configs), None)

    @property
    def modes(self) -> list[TranslationMode]:
        return list(dict.fromkeys(entry.mode for entry in self.translators))

    def fingerprint(self, mode: str, options: DocumentTranslationOptions) -> str:
        if mode not in self._identities:
            raise InvalidRequestError("translator is unavailable", code="translator_unavailable")
        return output_fingerprint(
            self._identities[mode],
            options,
            self.fonts,
        )

    def translator(self, mode: str) -> Translator:
        entry = self._configs.get(mode)
        if entry is None or mode not in self._identities:
            raise InvalidRequestError(
                "selected translator is no longer configured", code="translator_unavailable"
            )
        translator = self._translators.get(mode)
        runtime_key = self._runtime_key(mode) if entry.engine.mode == TranslationMode.MT else None
        if translator is None:
            if entry.engine.mode == TranslationMode.MT and runtime_key is not None:
                aliases = self._local_groups.get(runtime_key)
                if aliases:
                    translator = self._translators[aliases[0]].with_mt_decoding(
                        beam_size=entry.engine.beam_size,
                        max_batch_size=entry.engine.max_batch_size,
                    )
                    aliases.append(mode)
                else:
                    while len(self._local_groups) >= self._settings.max_loaded_local_models:
                        oldest = next(iter(self._local_groups))
                        for alias in self._local_groups.pop(oldest):
                            self._translators.pop(alias).close()
                    translator = Translator(entry.engine, fonts=self.fonts)
                    self._local_groups[runtime_key] = [mode]
            else:
                translator = Translator(entry.engine, fonts=self.fonts)
            self._translators[mode] = translator
        if runtime_key is not None:
            aliases = self._local_groups.pop(runtime_key)
            self._local_groups[runtime_key] = aliases
        return translator

    def loaded_fingerprint(
        self, translator: Translator, options: DocumentTranslationOptions
    ) -> str:
        return output_fingerprint(translator.identity, options, self.fonts)

    def close(self) -> None:
        for translator in self._translators.values():
            translator.close()
        self._translators.clear()
        self._local_groups.clear()
