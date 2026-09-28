import importlib

MODULES = [
    "doctranslator_eval",
    "doctranslator_eval.baselines",
    "doctranslator_eval.cli",
    "doctranslator_eval.compare",
    "doctranslator_eval.datasets",
    "doctranslator_eval.hardware",
    "doctranslator_eval.runner",
    "doctranslator_eval.runs",
    "doctranslator_eval.scoring",
    "doctranslator_eval.settings",
]


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(name)
