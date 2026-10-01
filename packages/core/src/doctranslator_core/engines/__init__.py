"""Translation engines, one module per translation mode."""

from doctranslator_core.config import EngineConfig
from doctranslator_core.engines.base import TranslationEngine
from doctranslator_core.types import TranslationIdentity, TranslationMode

__all__ = ["TranslationEngine", "create_engine", "prepare_identity", "with_mt_decoding"]


def with_mt_decoding(
    engine: TranslationEngine, *, beam_size: int, max_batch_size: int
) -> TranslationEngine:
    """Create an independent MT binding without importing MT details into callers."""
    from doctranslator_core.engines.mt import MtEngine

    if not isinstance(engine, MtEngine):
        raise ValueError("decoding bindings require an MT engine")
    return engine.with_decoding(beam_size=beam_size, max_batch_size=max_batch_size)


def create_engine(config: EngineConfig) -> TranslationEngine:
    """Create the engine for ``config.mode``. Each mode's libraries load only when it is used."""
    match config.mode:
        case TranslationMode.LLM:
            if config.protocol == "hy-mt":
                from doctranslator_core.engines.hy_mt import HyMtEngine

                return HyMtEngine(config)
            from doctranslator_core.engines.llm import LlmEngine

            return LlmEngine(config)
        case TranslationMode.MT:
            from doctranslator_core.engines.mt import MtEngine

            return MtEngine(config)


def prepare_identity(config: EngineConfig) -> TranslationIdentity:
    """The engine's output identity from configuration, without loading a model (ADR-011)."""
    match config.mode:
        case TranslationMode.LLM:
            if config.protocol == "hy-mt":
                from doctranslator_core.engines.hy_mt import prepare_identity as hy_mt_identity

                return hy_mt_identity(config)
            from doctranslator_core.engines.llm import prepare_identity as llm_identity

            return llm_identity(config)
        case TranslationMode.MT:
            from doctranslator_core.engines.mt import prepare_identity as mt_identity

            return mt_identity(config)
