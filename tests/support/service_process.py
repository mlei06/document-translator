"""The fake-engine service as a separate process, for end-to-end tests over real HTTP."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from support.server import FakeEngines, add_user, make_services, server_settings

__all__ = ["Provisioned", "provision", "running_service"]

SERVICE = Path(__file__).resolve().parent / "fake_service.py"


@dataclass(frozen=True)
class Provisioned:
    data_dir: Path
    alice: str
    bob: str


def provision(tmp_path: Path) -> Provisioned:
    """A migrated data directory with two users (Alice, Bob) and one key each."""
    data_dir = tmp_path / "service"
    services = make_services(server_settings(tmp_path, data_dir=data_dir), FakeEngines())
    try:
        _, alice = add_user(services, "Alice")
        _, bob = add_user(services, "Bob")
    finally:
        services.close()
    return Provisioned(
        data_dir,
        alice["Authorization"].removeprefix("Bearer "),
        bob["Authorization"].removeprefix("Bearer "),
    )


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_service(data_dir: Path, *options: str) -> Generator[str]:
    """Run the service on ``data_dir``; yields its base URL. Exiting kills the process
    (TerminateProcess on Windows): a crash, not a graceful stop."""
    port = _port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCTRANSLATOR_")}
    process = subprocess.Popen(  # noqa: S603 - our own test service
        [sys.executable, str(SERVICE), str(data_dir), str(port), *options],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):
            if process.poll() is not None:
                raise RuntimeError("the test service exited during startup")
            try:
                if httpx.get(url + "/v1/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("the test service did not start")
        yield url
    finally:
        process.kill()
        process.wait(timeout=30)
