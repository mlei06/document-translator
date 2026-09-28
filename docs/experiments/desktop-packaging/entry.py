"""D0 packaging probe, not the production desktop host or job service."""

import importlib.metadata
import json
import multiprocessing
import sys

from doctranslator_cli.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--packaging-probe"]:
        print(
            json.dumps(
                {
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "python": sys.version.split()[0],
                    "executable": sys.executable,
                    "core_version": importlib.metadata.version("doctranslator-core"),
                    "cli_version": importlib.metadata.version("doctranslator-cli"),
                }
            )
        )
    else:
        main()
