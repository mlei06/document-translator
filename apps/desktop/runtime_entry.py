"""PyInstaller entry: the existing service, including its desktop profile."""

import multiprocessing

from doctranslator_server.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
