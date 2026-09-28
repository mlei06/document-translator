import importlib

MODULES = [
    "doctranslator_core",
    "doctranslator_core.config",
    "doctranslator_core.document",
    "doctranslator_core.engines",
    "doctranslator_core.engines.base",
    "doctranslator_core.engines.llm",
    "doctranslator_core.engines.llm_prompts",
    "doctranslator_core.engines.mt",
    "doctranslator_core.fit",
    "doctranslator_core.formats",
    "doctranslator_core.formats._ooxml",
    "doctranslator_core.formats.base",
    "doctranslator_core.formats.docx",
    "doctranslator_core.formats.pdf",
    "doctranslator_core.formats.pptx",
    "doctranslator_core.formats.txt",
    "doctranslator_core.formats.xlsx",
    "doctranslator_core.pipeline",
    "doctranslator_core.render",
    "doctranslator_core.translator",
    "doctranslator_core.types",
]


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(name)
