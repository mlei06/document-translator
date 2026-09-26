import importlib

MODULES = [
    "doctranslator_cli",
]


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(name)
