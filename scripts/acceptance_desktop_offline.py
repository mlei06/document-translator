"""Real managed HY-MT all-format acceptance, reusing one authenticated runtime."""

import json
import time
from pathlib import Path

import pymupdf

from doctranslator_core import LlmEngineConfig, Translator, build_font_manifest
from doctranslator_core.types import DocumentTranslationOptions, Language
from doctranslator_server.jobs.desktop_files import digest
from doctranslator_server.jobs.desktop_runtime import ManagedLlama
from doctranslator_server.settings import load_settings


def main() -> None:
    root = Path("data/experiments/unified-desktop") / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    root.mkdir(parents=True, exist_ok=True)
    txt = root / "source.txt"
    txt.write_text(
        "项目报告\n请在星期五之前提交报告。\nAlready English passage.\n", encoding="utf-8"
    )
    pdf = root / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "项目报告", fontname="china-s", fontsize=18)  # pyright: ignore[reportUnknownMemberType]
    page.insert_text((72, 145), "请在星期五之前提交报告。", fontname="china-s", fontsize=12)  # pyright: ignore[reportUnknownMemberType]
    doc.save(pdf)  # pyright: ignore[reportUnknownMemberType]
    doc.close()
    sources = [
        txt,
        Path("tests/fixtures/docx/report.docx"),
        Path("tests/fixtures/pptx/deck.pptx"),
        Path("tests/fixtures/xlsx/features-shared.xlsx"),
        pdf,
    ]
    executable = Path("data/tools/llama.cpp/vulkan/llama-server.exe").resolve()
    model = Path("data/models/gguf/HY-MT1.5-1.8B-Q8_0.gguf").resolve()
    runtime = ManagedLlama(executable, model)
    revision = digest(model)
    config = LlmEngineConfig.model_validate(
        {
            "base_url": runtime.base_url,
            "api_key": runtime.token,
            "model": "hy-mt",
            "protocol": "hy-mt",
            "execution_location": "server",
            "managed_runtime_identity": revision,
            "deployment_revision": "llama-b11222-vulkan-t4-tb4-slots4",
            "max_concurrency": 4,
        }
    )
    records: list[dict[str, object]] = []
    try:
        with (
            runtime.pin(),
            Translator(
                config, fonts=build_font_manifest(load_settings().font_directories())
            ) as translator,
        ):
            for source in sources:
                started = time.monotonic()
                before = digest(source)
                record: dict[str, object] = {
                    "format": source.suffix[1:],
                    "runtime_sha256": digest(executable),
                    "model_sha256": revision,
                }
                output = root / f"hy-mt-{source.stem}.en{source.suffix}"
                try:
                    result = translator.translate_document(
                        source, output, options=DocumentTranslationOptions(target=Language.EN)
                    )
                    record.update(
                        status="succeeded",
                        fit=result.fit_status.value,
                        bytes=output.stat().st_size,
                        output_sha256=digest(output),
                        source_unchanged=before == digest(source),
                    )
                except Exception as exc:
                    record.update(status="failed", error_type=type(exc).__name__)
                record["seconds"] = round(time.monotonic() - started, 2)
                records.append(record)
                (root / "evidence.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
                print(json.dumps(record), flush=True)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
