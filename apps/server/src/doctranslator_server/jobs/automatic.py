"""Pinned automatic policy. Discovery is execution-only, never required for a cache hit."""

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from doctranslator_core import AutomaticTranslationPolicy
from doctranslator_core.types import DocumentTranslationOptions
from doctranslator_server.jobs.engines import EngineIdentities
from doctranslator_server.jobs.errors import InvalidRequestError
from doctranslator_server.settings import ServerSettings


def pinned_policy(
    settings: ServerSettings,
    catalog: EngineIdentities,
    options: DocumentTranslationOptions,
    *,
    desktop: bool = False,
) -> dict[str, Any]:
    policy = settings.web_translation_policy
    if policy is None or not str(policy.get("revision", "")).strip():
        raise InvalidRequestError(
            "automatic translation policy is not configured", code="policy_configuration"
        )
    try:
        approved = AutomaticTranslationPolicy.model_validate(policy)
    except ValidationError as exc:
        raise InvalidRequestError(
            "automatic translation policy is invalid", code="policy_configuration"
        ) from exc
    configs = {entry.id: entry.engine for entry in settings.configured_translators()}
    gemma = configs.get("gemma")
    if gemma is None or getattr(gemma, "model", None) != "gemma-4-31b-it":
        raise InvalidRequestError("Gemma must bind to gemma-4-31b-it", code="policy_configuration")
    for identifier in approved.davy_order:
        config = configs.get(identifier)
        if config is None:
            continue
        expected = "gemma-4-31b-it" if identifier == "gemma" else identifier
        if (
            getattr(config, "model", None) != expected
            or getattr(config, "protocol", None) != "json-batch"
            or getattr(config, "execution_location", None) != "remote"
        ):
            raise InvalidRequestError(
                f"{identifier} must bind to its approved remote model",
                code="policy_configuration",
            )
    local = configs.get("hy-mt-local")
    if not desktop and (local is None or approved.local_translator_id != "hy-mt-local"):
        raise InvalidRequestError(
            "website requires configured HY-MT fallback", code="policy_configuration"
        )
    if local is not None and (
        getattr(local, "protocol", None) != "hy-mt"
        or getattr(local, "execution_location", None) != "server"
    ):
        raise InvalidRequestError(
            "HY-MT fallback must use the local HY-MT protocol", code="policy_configuration"
        )
    candidates = [
        {"id": identifier, "fingerprint": catalog.fingerprint(identifier, options)}
        for identifier in approved.candidates
        if identifier in configs
    ]
    profile = hashlib.sha256(
        json.dumps(options.model_dump(mode="json", exclude={"source"}), sort_keys=True).encode()
    ).hexdigest()
    body = {
        "schema": 2,
        "revision": policy["revision"],
        "candidates": candidates,
        "profile": profile,
    }
    body["digest"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body
