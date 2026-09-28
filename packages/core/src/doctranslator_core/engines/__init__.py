"""Translation engines, one module per translation mode."""

from doctranslator_core.config import EngineConfig
from doctranslator_core.engines.base import TranslationEngine
from doctranslator_core.types import TranslationMode

__all__ = ["TranslationEngine", "create_engine"]


def create_engine(config: EngineConfig) -> TranslationEngine:
    """Create the engine for ``config.mode``. Each mode's libraries load only when it is used."""
    match config.mode:
        case TranslationMode.LLM:
            from doctranslator_core.engines.llm import LlmEngine

            return LlmEngine(config)
        case TranslationMode.MT:
            from doctranslator_core.engines.mt import MtEngine

            return MtEngine(config)
