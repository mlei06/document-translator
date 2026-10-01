"""Assemble the approved private desktop runtime resources, never print credentials."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from doctranslator_core import DAVY_ORDER
from doctranslator_server.desktop import restrict_data_root, windows_identity
from doctranslator_server.jobs.desktop_offline import OfflineManifest
from doctranslator_server.settings import ServerSettings, load_settings


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate-thumbprint")
    args = parser.parse_args()
    root = Path("data/desktop-build/resources")
    root.mkdir(parents=True, exist_ok=True)
    sid, _ = windows_identity()
    restrict_data_root(root.resolve(), sid)
    runtime = root / "llama"
    runtime.mkdir(exist_ok=True)
    for source in Path("data/tools/llama.cpp/vulkan").iterdir():
        if source.suffix == ".dll" or source.name in {"llama-server.exe", "LICENSE-LLVM-OpenMP"}:
            shutil.copy2(source, runtime / source.name)
    redist_root = Path(
        "C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Redist/MSVC"
    )
    redists = sorted(redist_root.glob("*/x64/Microsoft.VC143.CRT"))
    if not redists:
        raise FileNotFoundError(
            "The x64 Visual C++ redistributable application-local DLLs are required"
        )
    for binary in redists[-1].glob("*.dll"):
        shutil.copy2(binary, runtime / binary.name)
    if args.certificate_thumbprint:
        signer = Path("C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/signtool.exe")
        for binary in runtime.iterdir():
            if binary.suffix in {".dll", ".exe"}:
                subprocess.run(  # noqa: S603 - fixed Windows SDK signer, argument array
                    [
                        str(signer),
                        "sign",
                        "/sha1",
                        args.certificate_thumbprint,
                        "/fd",
                        "SHA256",
                        "/tr",
                        "http://timestamp.digicert.com",
                        "/td",
                        "SHA256",
                        str(binary),
                    ],
                    check=True,
                )
                subprocess.run(  # noqa: S603 - fixed Windows SDK signer
                    [str(signer), "verify", "/pa", str(binary)], check=True
                )
    files = {p.name: checksum(p) for p in runtime.iterdir() if p.suffix in {".dll", ".exe"}}
    model = Path("data/models/gguf/HY-MT1.5-1.8B-Q8_0.gguf")
    expected = "6789b06d0902f2f5312c0e1703d56ccbddfcfb6c653d22519b7c720f7db9a98e"
    if checksum(model) != expected:
        raise ValueError("Approved offline model digest mismatch")
    revision = "265b2e615a7dc9b06c435dc878829ad99a512ba2"
    manifest = OfflineManifest.model_validate(
        {
            "revision": "hy-mt15-q8-v1",
            "model_id": "HY-MT1.5-1.8B-Q8_0",
            "adapter_version": "hy-mt-v1",
            "runtime_sha256": files["llama-server.exe"],
            "runtime_files": files,
            "provenance": f"https://huggingface.co/tencent/HY-MT1.5-1.8B-GGUF/tree/{revision}",
            "license": "Tencent HY Community License https://github.com/Tencent-Hunyuan/HY-MT/blob/main/License.txt",
            "language_pairs": [
                f"{a}-{b}"
                for a in ("en", "zh", "ja", "es")
                for b in ("en", "zh", "ja", "es")
                if a != b
            ],
            "resource_guidance": (
                "Validated Intel Arc integrated Vulkan, four threads and four slots. "
                "Other hardware unvalidated; no CPU fallback. "
                "Weights 1.91GB plus runtime and working space."
            ),
            "weights": model.name,
            "files": [
                {
                    "path": model.name,
                    "url": f"https://huggingface.co/tencent/HY-MT1.5-1.8B-GGUF/resolve/{revision}/{model.name}",
                    "size": model.stat().st_size,
                    "sha256": expected,
                }
            ],
        }
    )
    (root / "offline-model.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    settings = load_settings()
    url = settings.davy_base_url or settings.llm_base_url
    key = settings.davy_api_key or settings.llm_api_key
    if not url or not key:
        raise ValueError("Release-provisioned Davy endpoint/key unavailable")
    models = [
        {"id": name, "label": name, "model": "gemma-4-31b-it" if name == "gemma" else name}
        for name in DAVY_ORDER
    ]
    payload = {
        "default_translator_id": "gemma",
        "davy_base_url": str(url),
        "davy_api_key": key.get_secret_value(),
        "davy_models": models,
    }
    try:
        ServerSettings.model_validate(payload)
    except ValueError:
        raise ValueError("Private translation provisioning configuration is invalid") from None
    (root / "provisioning.json").write_text(json.dumps(payload), encoding="utf-8")
    print("Private runtime resources prepared; credential values omitted")


if __name__ == "__main__":
    main()
