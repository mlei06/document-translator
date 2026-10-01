# ruff: noqa: RUF001
"""Real HY-MT adapter acceptance through the public document/text API, with profiling."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench import ROOT, HyRuntime, baseline_module, request
from profiling import ResourceProfiler
from pydantic import HttpUrl, SecretStr

from doctranslator_core import (
    LlmEngineConfig,
    Translator,
    document_text,
    inspect_document,
    render_pages,
)
from doctranslator_core.types import (
    DocumentFormat,
    DocumentTranslationOptions,
    FontManifest,
    Language,
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=["hy-cpu", "hy-vulkan"], default="hy-vulkan")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--out", type=Path, default=ROOT / "data/experiments/laptop-mt/acceptance")
    args = parser.parse_args()
    if min(args.threads, args.concurrency) < 1:
        parser.error("threads and concurrency must be positive")
    os.chdir(ROOT)
    destination = args.out.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    inputs = destination / "inputs"
    outputs = destination / "outputs"
    inputs.mkdir(exist_ok=True)
    outputs.mkdir(exist_ok=True)
    fixtures = [
        ROOT / "tests/fixtures/pptx/deck.pptx",
        ROOT / "tests/fixtures/docx/report.docx",
        ROOT / "tests/fixtures/xlsx/features-shared.xlsx",
        ROOT / "data/acceptance/p4/local/text-zh.pdf",
    ]
    original_hashes = {str(path): digest(path) for path in fixtures}
    sources: list[Path] = []
    for fixture in fixtures:
        copied = inputs / fixture.name
        shutil.copyfile(fixture, copied)
        sources.append(copied)
    txt = inputs / "report.txt"
    txt.write_text(
        "季度业务回顾\n本季度营业收入增长12%。\n请在周五之前提交预算草案。\n", encoding="utf-8"
    )
    sources.append(txt)
    fonts = FontManifest.model_validate_json(
        (ROOT / "data/experiments/openvino-small100/font-manifest.json").read_text("utf-8")
    )
    if os.name == "nt":
        baseline_module().no_power_throttling()
    args.threads_batch = args.threads
    args.model = ROOT / "data/models/gguf/HY-MT1.5-1.8B-Q8_0.gguf"
    args.out = destination / "acceptance.json"
    runtime = HyRuntime(args)
    report: dict[str, Any] = {
        "started_utc": datetime.now(UTC).isoformat(),
        "settings": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "original_sha256": original_hashes,
        "runs": [],
        "smoke": [],
    }
    translator: Translator | None = None
    try:
        with ResourceProfiler() as profile:
            runtime.start()
            model = request(runtime.port, "/v1/models")["data"][0]["id"]
            config = LlmEngineConfig(
                base_url=HttpUrl(f"http://127.0.0.1:{runtime.port}/v1"),
                api_key=SecretStr("local-acceptance"),
                model=model,
                protocol="hy-mt",
                execution_location="server",
                json_mode=False,
                max_concurrency=args.concurrency,
                batch_size=1,
                max_output_tokens=2048,
                max_retries=0,
                timeout_s=180,
                deployment_revision=f"HY-MT1.5-Q8_0-{args.runtime}-t{args.threads}-slots{args.concurrency}",
            )
            translator = Translator(config, fonts=fonts)
        report["load_profile"] = profile.result()
        report["runtime"] = runtime.props
        report["engine"] = translator.engine_info.model_dump(mode="json")
        for source, target, texts in [
            (
                Language.ZH,
                Language.EN,
                ["本季度营业收入增长12%。", "<g0>重要提示</g0>：请查看<x0/>。"],
            ),
            (
                Language.EN,
                Language.ZH,
                ["Please submit the budget by Friday.", "<g0>Important</g0>: see <x0/>."],
            ),
        ]:
            row: dict[str, Any] = {"source": source.value, "target": target.value, "inputs": texts}
            try:
                with ResourceProfiler() as profile:
                    row["outputs"] = translator.translate_texts(texts, source=source, target=target)
                row["markers_preserved"] = all(
                    sorted(re.findall(r"</?g\d+>|<x\d+/>", before))
                    == sorted(re.findall(r"</?g\d+>|<x\d+/>", after))
                    for before, after in zip(texts, row["outputs"], strict=True)
                )
                row["ok"] = bool(
                    row["markers_preserved"] and all(text.strip() for text in row["outputs"])
                )
            except Exception as exc:
                row.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            row["profile"] = profile.result()
            report["smoke"].append(row)
        for source_path in sources:
            print(f"acceptance: {source_path.name}", flush=True)
            target_path = outputs / f"{source_path.stem}.en{source_path.suffix}"
            target_path.unlink(missing_ok=True)
            row = {
                "source": str(source_path),
                "output": str(target_path),
                "input_sha256": digest(source_path),
            }
            started = time.perf_counter()
            try:
                with ResourceProfiler() as profile:
                    row["input_text"] = [unit.model_dump() for unit in document_text(source_path)]
                    result = translator.translate_document(
                        source_path,
                        target_path,
                        options=DocumentTranslationOptions(source=Language.ZH, target=Language.EN),
                    )
                    row["result"] = result.model_dump(mode="json")
                    row["reopened_format"] = inspect_document(target_path).value
                    row["output_text"] = [unit.model_dump() for unit in document_text(target_path)]
                row["input_segments"] = len(row["input_text"])
                row["output_segments"] = len(row["output_text"])
                row["input_unchanged"] = digest(source_path) == row["input_sha256"]
                row["ok"] = bool(row["input_unchanged"] and row["output_text"])
                row["output_sha256"] = digest(target_path)
                # Preview generation is outside the measured translation profile.
                if result.format != DocumentFormat.TXT:
                    try:
                        previews = render_pages(target_path, result.format, max_pages=3)
                        preview_paths: list[str] = []
                        for index, page in enumerate(previews):
                            preview = outputs / f"{source_path.stem}-page-{index + 1}.jpg"
                            preview.write_bytes(page.jpeg)
                            preview_paths.append(str(preview))
                        row["previews"] = preview_paths
                    except Exception as exc:
                        row["preview_error"] = f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                row.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            row["profile"] = profile.result()
            row["total_wall_s_including_preview"] = time.perf_counter() - started
            report["runs"].append(row)
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["original_inputs_unchanged"] = all(
            digest(Path(path)) == sha for path, sha in original_hashes.items()
        )
        report["ok"] = report["original_inputs_unchanged"] and all(
            row["ok"] for row in report["runs"] + report["smoke"]
        )
    except Exception as exc:
        report.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if translator is not None:
            translator.close()
        runtime.close()
        report["finished_utc"] = datetime.now(UTC).isoformat()
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["ok"]:
        raise SystemExit("Acceptance had failures; inspect acceptance.json")


if __name__ == "__main__":
    main()
