import importlib

MODULES = [
    "doctranslator_cli",
    "doctranslator_cli.console",
    "doctranslator_cli.main",
    "doctranslator_cli.settings",
]


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(name)
