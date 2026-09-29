"""Versioned, model-native translation contracts; generic prompting stays unchanged."""

from typing import Literal

from doctranslator_core.types import Language

type SpecializedProfile = Literal["translategemma", "hy-mt2"]

PROMPT_VERSIONS: dict[SpecializedProfile, str] = {
    "translategemma": "translategemma-raw-10042cb0e6e7-v2",
    "hy-mt2": "hy-mt2-native-v1",
}

_LANGUAGE_NAMES = {
    Language.ZH: "Chinese",
    Language.EN: "English",
    Language.JA: "Japanese",
    Language.ES: "Spanish",
}


def hy_mt2_messages(text: str, target: Language) -> list[dict[str, object]]:
    return [
        {
            "role": "user",
            "content": (
                f"Translate the following text into {_LANGUAGE_NAMES[target]}. "
                "Note that you should only output the translated result without any additional "
                f"explanation:\n{text}"
            ),
        }
    ]


def translategemma_prompt(text: str, source: Language, target: Language) -> str:
    """Text branch of Google's template at revision 10042cb0e6e7.

    Pre-rendering retains language metadata on servers whose chat adapters discard
    unknown content fields. The completion server must recognize Gemma special tokens.
    """
    source_name, target_name = _LANGUAGE_NAMES[source], _LANGUAGE_NAMES[target]
    return (
        f"<bos><start_of_turn>user\nYou are a professional {source_name} ({source.value}) to "
        f"{target_name} ({target.value}) translator. Your goal is to accurately convey the meaning "
        f"and nuances of the original {source_name} text while adhering to {target_name} grammar, "
        f"vocabulary, and cultural sensitivities.\nProduce only the {target_name} translation, "
        "without any additional explanations or commentary. Please translate the following "
        f"{source_name} text into {target_name}:\n\n\n{text.strip()}"
        "<end_of_turn>\n<start_of_turn>model\n"
    )
