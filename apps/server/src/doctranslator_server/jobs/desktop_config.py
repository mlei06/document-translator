"""Compose installed desktop capability into the common engine catalog."""

from doctranslator_core import DAVY_ORDER, AutomaticTranslationPolicy, LlmEngineConfig
from doctranslator_server.jobs.desktop_offline import OfflineSupport
from doctranslator_server.settings import ConfiguredTranslator, DavyModel, ServerSettings


def configure(settings: ServerSettings, offline: OfflineSupport) -> ServerSettings:
    if settings.davy_base_url is None and settings.llm_base_url and settings.llm_api_key:
        settings = settings.model_copy(
            update={
                "davy_base_url": settings.llm_base_url,
                "davy_api_key": settings.llm_api_key,
                "davy_models": [
                    DavyModel(
                        id=identifier,
                        label=identifier,
                        model="gemma-4-31b-it" if identifier == "gemma" else identifier,
                    )
                    for identifier in DAVY_ORDER
                ],
            }
        )
    # A desktop never silently connects to an administrator-owned local inference
    # daemon: the approved installed bundle is the sole offline candidate.
    entries = [
        entry
        for entry in settings.configured_translators()
        if isinstance(entry.engine, LlmEngineConfig)
        and entry.engine.execution_location == "remote"
        and entry.id not in {model.id for model in settings.davy_models}
    ]
    try:
        installed = offline.load()
    except OSError, ValueError:
        offline.error = "Installed offline support failed verification; repair it in Settings"
        installed = None
    if installed:
        runtime, identity = installed
        entries.append(
            ConfiguredTranslator(
                id="hy-mt-local",
                label="On this device",
                engine=LlmEngineConfig.model_validate(
                    {
                        "base_url": runtime.base_url,
                        "api_key": runtime.token,
                        "model": "hy-mt",
                        "protocol": "hy-mt",
                        "execution_location": "server",
                        "managed_runtime_identity": identity,
                        "deployment_revision": "desktop-vulkan-t4-tb4-slots4-v1",
                        "max_concurrency": 4,
                    }
                ),
            )
        )
    default = next(
        (model.id for model in settings.davy_models if model.enabled),
        entries[0].id if entries else None,
    )
    policy = AutomaticTranslationPolicy(
        revision="desktop-auto-v2",
        local_translator_id="hy-mt-local" if installed else None,
    )
    return settings.model_copy(
        update={
            "translators": entries,
            "default_translator_id": default,
            "web_translation_policy": policy.model_dump(mode="json"),
        }
    )
