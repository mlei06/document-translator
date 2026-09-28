"""Host hardware and peak memory, recorded with every run so throughput numbers have context."""

import platform
import sys
import threading
import types
from pathlib import Path
from typing import Protocol, Self, cast

import psutil  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel, ConfigDict

_MB = 1024 * 1024


class _MemoryInfo(Protocol):
    @property
    def rss(self) -> int: ...


class _VirtualMemory(Protocol):
    @property
    def total(self) -> int: ...


class _Process(Protocol):
    def memory_info(self) -> _MemoryInfo: ...


class _Psutil(Protocol):
    """The part of the untyped ``psutil`` module used here."""

    def cpu_count(self, logical: bool = True) -> int | None: ...

    def virtual_memory(self) -> _VirtualMemory: ...

    def Process(self) -> _Process: ...  # noqa: N802 - mirrors the library's class name


_psutil = cast(_Psutil, psutil)


class HardwareInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    os: str
    os_version: str
    cpu: str
    logical_cores: int
    physical_cores: int
    ram_gb: float
    device: str
    """The engine's resolved device (``cpu``, ``cuda``), or ``remote`` for LLM mode."""


def collect_hardware(device: str) -> HardwareInfo:
    return HardwareInfo(
        os=platform.system(),
        os_version=platform.version(),
        cpu=_cpu_name(),
        logical_cores=_psutil.cpu_count(logical=True) or 0,
        physical_cores=_psutil.cpu_count(logical=False) or 0,
        ram_gb=round(_psutil.virtual_memory().total / 1024**3, 1),
        device=device,
    )


def _cpu_name() -> str:
    """The marketing CPU name where the OS exposes it, else ``platform.processor()``."""
    if sys.platform == "win32":
        import winreg

        key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value: object = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        except OSError:
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    return platform.processor() or "unknown"


class PeakMemory:
    """Samples this process's resident memory on a daemon thread and keeps the peak."""

    def __init__(self, interval_s: float = 0.5) -> None:
        self._interval_s = interval_s
        self._process = _psutil.Process()
        self._peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    @property
    def peak_mb(self) -> float:
        return round(self._peak / _MB, 1)

    def __enter__(self) -> Self:
        self._peak = self._process.memory_info().rss
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join()
        self._peak = max(self._peak, self._process.memory_info().rss)

    def _sample(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._peak = max(self._peak, self._process.memory_info().rss)
