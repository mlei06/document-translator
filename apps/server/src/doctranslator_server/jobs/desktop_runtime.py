"""Owned, authenticated llama.cpp lifecycle for the installed HY-MT bundle."""

import os
import re
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import httpx


class ManagedLlama:
    """Load on first pin, reject removal while pinned, unload after five idle minutes.

    The shell's Windows Job Object contains this child automatically. The caller
    supplies only verified installed assets and signs the executable with the app.
    """

    def __init__(self, executable: Path, model: Path, *, idle_seconds: float = 300) -> None:
        self.executable = executable
        self.model = model
        self.idle_seconds = idle_seconds
        self.token = secrets.token_urlsafe(32)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = int(listener.getsockname()[1])
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        self._pins = 0
        self._timer: threading.Timer | None = None
        self._vulkan = False
        self._offloaded = False

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if not self.executable.is_file() or not self.model.is_file():
            raise FileNotFoundError("Offline support is not installed; install or repair it")
        self._vulkan = False
        self._offloaded = False
        environment = os.environ.copy()
        environment["LLAMA_API_KEY"] = self.token
        self._process = subprocess.Popen(  # noqa: S603 - approved local executable, no shell
            [
                str(self.executable),
                "-m",
                str(self.model),
                "--alias",
                "hy-mt",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "-t",
                "4",
                "-tb",
                "4",
                "-ngl",
                "99",
                "-c",
                "16384",
                "-np",
                "4",
                "--no-warmup",
                "--verbosity",
                "4",
                "--no-context-shift",
                "--cache-ram",
                "0",
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        def inspect_startup() -> None:
            process = self._process
            if process is None or process.stderr is None:
                return
            with process.stderr:
                for raw in process.stderr:
                    line = raw.decode("utf-8", errors="replace")
                    if "Vulkan" in line and ("using device" in line or "model buffer" in line):
                        self._vulkan = True
                    match = re.search(r"offloaded (\d+)/(\d+) layers to GPU", line)
                    if match and int(match[1]) == int(match[2]) and int(match[1]) > 0:
                        self._offloaded = True

        threading.Thread(target=inspect_startup, daemon=True, name="offline-capability").start()
        deadline = time.monotonic() + 180
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if self._process.poll() is not None:
                        raise RuntimeError("Offline runtime exited; repair offline support")
                    try:
                        response = client.get(
                            f"http://127.0.0.1:{self.port}/health",
                            headers={"Authorization": f"Bearer {self.token}"},
                        )
                        if response.status_code == 200:
                            if not self._vulkan or not self._offloaded:
                                raise RuntimeError(
                                    "This device cannot run the approved Vulkan offline profile"
                                )
                            return
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
            raise TimeoutError("Offline runtime did not become ready")
        except BaseException:
            self._stop()
            raise

    @contextmanager
    def pin(self) -> Generator[None]:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._start()
            self._pins += 1
        try:
            yield
        finally:
            with self._lock:
                self._pins -= 1
                if self._pins == 0:
                    self._timer = threading.Timer(self.idle_seconds, self.close)
                    self._timer.daemon = True
                    self._timer.start()

    def _stop(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._process = None

    def close(self) -> None:
        with self._lock:
            if self._pins:
                raise RuntimeError("Offline support is in use by active translations")
            if self._timer:
                self._timer.cancel()
            self._stop()
