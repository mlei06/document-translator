"""Immutable automatic translation policy shared by website and desktop."""

import hashlib
import json
from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

DAVY_ORDER = (
    "gemma",
    "nemotron-3-ultra",
    "nemotron-3-super-120b",
    "gpt-oss-120b-thinking",
    "gpt-oss-120b",
    "laguna-s-2.1",
)
LOCAL_TRANSLATOR_ID = "hy-mt-local"


class AutomaticTranslationPolicy(BaseModel):
    """Pin this policy and candidate fingerprints when accepting work.

    ``None`` local fallback is valid only for desktop online-only installations.
    Website configuration additionally requires the local candidate to be installed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    revision: str = "web-auto-v2"
    davy_order: tuple[str, ...] = DAVY_ORDER
    local_translator_id: Literal["hy-mt-local"] | None = LOCAL_TRANSLATOR_ID

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if not self.revision.strip():
            raise ValueError("automatic policy revision must not be empty")
        if len(self.davy_order) != len(set(self.davy_order)):
            raise ValueError("automatic policy contains duplicate Davy IDs")
        if set(self.davy_order) != set(DAVY_ORDER):
            raise ValueError("automatic policy must contain exactly the approved Davy IDs")
        return self

    @property
    def candidates(self) -> tuple[str, ...]:
        return self.davy_order + ((self.local_translator_id,) if self.local_translator_id else ())

    def digest(self, fingerprints: Mapping[str, str]) -> str:
        if set(fingerprints) != set(self.candidates) or any(
            not value.strip() for value in fingerprints.values()
        ):
            raise ValueError("every policy candidate requires its immutable fingerprint")
        payload = {
            "policy": self.model_dump(mode="json"),
            "candidates": [(candidate, fingerprints[candidate]) for candidate in self.candidates],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
