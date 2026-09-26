import importlib

MODULES = [
    "doctranslator_server",
    "doctranslator_server.api",
    "doctranslator_server.app",
    "doctranslator_server.auth",
    "doctranslator_server.db",
    "doctranslator_server.jobs",
    "doctranslator_server.mcp",
    "doctranslator_server.settings",
]


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(name)
