"""Run the real service (REST + worker threads) with the deterministic fake engine.

Used by end-to-end tests as a separate process so the CLI talks to it over real HTTP:

    python tests/support/fake_service.py DATA_DIR PORT [--lease 60] [--workers 1] [--slow 0]

The database must already be migrated (``support.server.make_services`` does that).
"""

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from doctranslator_core.types import TranslationMode
from doctranslator_server.app import build_services, create_app
from support.server import FakeEngines, make_worker, server_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("port", type=int)
    parser.add_argument("--lease", type=float, default=60.0)
    parser.add_argument("--heartbeat", type=float, default=20.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--slow", type=float, default=0.0, help="Seconds per translation.")
    parser.add_argument("--max-per-user", type=int, default=200)
    args = parser.parse_args()

    def slow(_mode: TranslationMode, _source: Path) -> None:
        time.sleep(args.slow)

    engines = FakeEngines(before=slow if args.slow else None)
    settings = server_settings(
        args.data_dir.parent,
        data_dir=args.data_dir,
        lease_s=args.lease,
        heartbeat_s=args.heartbeat,
        poll_s=0.2,
        max_queued_jobs_per_user=args.max_per_user,
    )
    services = build_services(settings, catalog=engines)
    stop = threading.Event()
    for index in range(args.workers):
        worker = make_worker(services, engines, worker_id=f"fake-{index}")
        threading.Thread(target=worker.run, args=(stop,), daemon=True).start()
    try:
        uvicorn.run(create_app(services), host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
