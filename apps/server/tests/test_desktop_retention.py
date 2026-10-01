"""Installed offline corruption remains visible while online capability stays usable."""

import hashlib
import json
from pathlib import Path

import pytest
from support.server import server_settings

from doctranslator_server.jobs.desktop_config import configure
from doctranslator_server.jobs.desktop_offline import OfflineSupport


def installed_bundle(tmp_path: Path) -> tuple[OfflineSupport, Path, Path]:
    application = tmp_path / "application"
    (application / "llama").mkdir(parents=True)
    runtime = application / "llama/llama-server.exe"
    runtime.write_bytes(b"synthetic runtime, never executed")
    root = tmp_path / "models"
    (root / "v1").mkdir(parents=True)
    weights = root / "v1/model.gguf"
    weights.write_bytes(b"synthetic model, never loaded")
    (root / "active.json").write_text("v1")
    manifest = dict(
        revision="v1",
        model_id="HY-MT1.5-1.8B-Q8_0",
        adapter_version="hy-mt-v1",
        runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
        runtime_files={"llama-server.exe": hashlib.sha256(runtime.read_bytes()).hexdigest()},
        provenance="https://approved.example/model",
        license="Synthetic test license",
        language_pairs=[
            f"{a}-{b}" for a in ("en", "zh", "ja", "es") for b in ("en", "zh", "ja", "es") if a != b
        ],
        resource_guidance="Synthetic validation fixture",
        weights="model.gguf",
        files=[
            dict(
                path="model.gguf",
                url="https://approved.example/model",
                size=weights.stat().st_size,
                sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),
            )
        ],
    )
    (application / "offline-model.json").write_text(json.dumps(manifest))
    return OfflineSupport(root, application), weights, runtime


def test_repeated_setup_verifies_and_reuses_the_installed_bundle(tmp_path: Path) -> None:
    offline, weights, runtime = installed_bundle(tmp_path)
    before = (weights.read_bytes(), runtime.read_bytes(), offline.active.read_bytes())
    try:
        for _ in range(2):
            offline.setup()
            assert offline.status()["state"] == "Ready"
            assert not offline.installing
            assert (
                weights.read_bytes(),
                runtime.read_bytes(),
                offline.active.read_bytes(),
            ) == before
        weights.write_bytes(b"damaged after installation")
        offline.setup()
        assert offline.status()["state"] == "Needs attention"
        assert weights.read_bytes() == b"damaged after installation"
    finally:
        if offline.runtime is not None:
            offline.runtime.close()


@pytest.mark.parametrize("corruption", ["weights", "runtime", "revision"])
def test_corrupt_installed_offline_support_reports_needs_attention(
    tmp_path: Path, corruption: str
) -> None:
    offline, weights, runtime = installed_bundle(tmp_path)
    if corruption == "weights":
        weights.write_bytes(b"damaged")
    elif corruption == "runtime":
        runtime.write_bytes(b"damaged")
    else:
        offline.active.write_text("obsolete")
    configured = configure(server_settings(tmp_path), offline)
    status = offline.status()
    assert status["state"] == "Needs attention"
    assert "repair" in str(status["detail"]).lower()
    assert str(tmp_path) not in str(status["detail"])
    assert offline.runtime is None
    assert all(entry.id != "hy-mt-local" for entry in configured.configured_translators())
    assert weights.exists() and runtime.exists()
