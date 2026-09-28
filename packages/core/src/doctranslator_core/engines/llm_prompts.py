"""Versioned prompt templates for the LLM engine.

Any change to prompt wording or structure bumps ``PROMPT_VERSION``: quality baselines are tied to
it (ADR-005).
"""

import json
from collections.abc import Sequence

from doctranslator_core.types import LANGUAGE_NAMES, Language

PROMPT_VERSION = "llm-translate-v1"

SYSTEM_TEMPLATE = """\
You are a professional translator. Translate each segment from {source} to {target}.

Rules:
- Translate every segment completely. Never merge, split, omit, or reorder segments.
- Return exactly one translation per input segment, in the same order.
- Keep numbers, units, URLs, email addresses, file paths, code, product names, and placeholders \
such as {{0}}, %s, or <tag> exactly as written.
- Keep line breaks that appear inside a segment.
- Output only the translation: no notes, explanations, or surrounding quotes.

Respond with a JSON object of the form {{"translations": ["...", "..."]}}."""


def system_prompt(source: Language, target: Language) -> str:
    return SYSTEM_TEMPLATE.format(source=LANGUAGE_NAMES[source], target=LANGUAGE_NAMES[target])


def user_message(segments: Sequence[str]) -> str:
    return json.dumps({"segments": list(segments)}, ensure_ascii=False)
