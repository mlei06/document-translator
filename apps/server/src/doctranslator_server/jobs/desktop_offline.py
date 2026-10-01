"""One approved offline bundle and its per-user activation record."""

import hashlib
import json
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from doctranslator_server.jobs.desktop_assets import Asset, install
from doctranslator_server.jobs.desktop_files import digest
from doctranslator_server.jobs.desktop_runtime import ManagedLlama


class BundleFile(BaseModel):
    path: str
    url: str
    size: int = Field(gt=0)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class OfflineManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern="^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")
    model_id: Literal["HY-MT1.5-1.8B-Q8_0"]
    adapter_version: Literal["hy-mt-v1"]
    runtime_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    runtime_files: dict[str, str] = Field(min_length=1)
    provenance: str
    license: str
    language_pairs: list[str] = Field(min_length=12, max_length=12)
    resource_guidance: str
    files: list[BundleFile] = Field(min_length=1)
    weights: str

    @model_validator(mode="after")
    def supported(self) -> OfflineManifest:
        expected = {
            f"{source}-{target}"
            for source in ("en", "zh", "ja", "es")
            for target in ("en", "zh", "ja", "es")
            if source != target
        }
        if set(self.language_pairs) != expected:
            raise ValueError("Offline bundle must cover all twelve approved language pairs")
        if len({file.path for file in self.files}) != len(self.files):
            raise ValueError("Duplicate offline asset paths")
        if (
            not self.provenance.strip()
            or not self.license.strip()
            or not self.resource_guidance.strip()
        ):
            raise ValueError(
                "Offline bundle provenance, license and resource guidance are required"
            )
        for name, checksum in self.runtime_files.items():
            if Path(name).name != name or Path(name).suffix.lower() not in {".dll", ".exe"}:
                raise ValueError("Invalid runtime asset")
            if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
                raise ValueError("Invalid runtime digest")
        if self.runtime_files.get("llama-server.exe") != self.runtime_sha256:
            raise ValueError("Runtime identity must match verified executable")
        return self


class OfflineSupport:
    def __init__(self, root: Path, application: Path) -> None:
        self.root = root
        self.application = application
        self.active = root / "active.json"
        self.runtime: ManagedLlama | None = None
        self.installing = False
        self.error: str | None = None
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.changed: Callable[[], None] = lambda: None

    def manifest(self) -> OfflineManifest:
        path = self.application / "offline-model.json"
        if not path.is_file():
            raise FileNotFoundError("This application has no approved offline bundle manifest")
        value = OfflineManifest.model_validate_json(path.read_text(encoding="utf-8"))
        for file in value.files:
            Asset(**file.model_dump()).validate()
        if value.weights not in {file.path for file in value.files}:
            raise ValueError("Offline manifest does not identify its verified weights")
        return value

    def verified_runtime(self, manifest: OfflineManifest) -> Path:
        directory = self.application / "llama"
        actual = {p.name for p in directory.iterdir() if p.suffix.lower() in {".exe", ".dll"}}
        if actual != set(manifest.runtime_files):
            raise ValueError("Offline runtime files differ from the approved bundle")
        for name, expected in manifest.runtime_files.items():
            path = directory / name
            if (
                path.is_symlink()
                or not path.resolve().is_relative_to(directory.resolve())
                or digest(path) != expected
            ):
                raise ValueError("Offline runtime integrity check failed; repair the application")
        return directory / "llama-server.exe"

    def load(self) -> tuple[ManagedLlama, str] | None:
        if not self.active.exists():
            return None
        manifest = self.manifest()
        if self.active.read_text(encoding="utf-8").strip() != manifest.revision:
            raise ValueError("Offline bundle requires repair for this application version")
        directory = self.root / manifest.revision
        for file in manifest.files:
            path = directory / file.path
            if (
                not path.resolve().is_relative_to(directory.resolve())
                or digest(path) != file.sha256
            ):
                raise ValueError("Offline model integrity check failed; repair offline support")
        executable = self.verified_runtime(manifest)
        if self.runtime is None:
            self.runtime = ManagedLlama(executable, directory / manifest.weights)
        identity = hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()
        return self.runtime, identity

    def add(self, *, offline: Path | None = None) -> None:
        manifest = self.manifest()
        executable = self.verified_runtime(manifest)

        def load_test(stage: Path) -> None:
            runtime = ManagedLlama(executable, stage / manifest.weights)
            try:
                with runtime.pin():
                    pass
            finally:
                runtime.close()

        install(
            self.root,
            manifest.revision,
            tuple(Asset(**file.model_dump()) for file in manifest.files),
            load_test,
            offline=offline,
            cancelled=self.cancelled.is_set,
        )
        staged = self.root / "active.tmp"
        staged.write_text(manifest.revision, encoding="utf-8")
        staged.replace(self.active)

    def status(self) -> dict[str, str | int]:
        if self.installing:
            return {"state": "Installing", "bytes": 0}
        if self.error:
            return {"state": "Needs attention", "bytes": 0, "detail": self.error}
        try:
            manifest = self.manifest()
            installed = self.active.exists()
            return {
                "state": "Ready" if installed and self.runtime else "Not installed",
                "bytes": sum(file.size for file in manifest.files),
                "revision": manifest.revision,
            }
        except OSError, ValueError:
            return {
                "state": "Needs attention",
                "bytes": 0,
                "detail": "Approved offline support is unavailable; repair the application",
            }

    def deactivate(self) -> None:
        with self.lock:
            if self.installing:
                raise RuntimeError("Offline support is being installed")
            if self.runtime:
                self.runtime.close()
                self.runtime = None
            manifest = self.manifest()
            directory = (self.root / manifest.revision).resolve()
            if (
                not directory.is_relative_to(self.root.resolve())
                or directory == self.root.resolve()
            ):
                raise ValueError("Invalid managed model directory")
            self.active.unlink(missing_ok=True)
            if directory.exists():
                shutil.rmtree(directory)

    def setup(self, *, repair: bool = False) -> None:
        """Background setup entry used by first installation and settings."""
        try:
            with self.lock:
                self.error = None
                if repair:
                    self.installing = False
                    self.deactivate()
                self.installing = True
            media = self.application / "offline-media"
            # Setup also runs after application upgrades. Revalidate an activated
            # immutable bundle instead of trying to publish the same revision again.
            if self.load() is None:
                self.add(offline=media if media.is_dir() else None)
                self.load()
            self.changed()
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            self.error = str(exc)
        finally:
            self.installing = False

    def settings_json(self) -> str:
        return json.dumps(self.status())
