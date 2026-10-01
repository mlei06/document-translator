"""Serial real-model acceptance using repository fixtures; never emits configuration secrets."""

import json
import time
from pathlib import Path

import pymupdf

from doctranslator_core import (
    AutomaticTranslationPolicy,
    LlmEngineConfig,
    Translator,
    build_font_manifest,
)
from doctranslator_core.types import DocumentTranslationOptions, Language
from doctranslator_server.settings import load_settings


def main() -> None:
    settings = load_settings()
    endpoint = settings.davy_base_url or settings.llm_base_url
    credential = settings.davy_api_key or settings.llm_api_key
    if endpoint is None or credential is None:
        raise RuntimeError("approved endpoint/credential is not configured")
    root = Path("data/experiments/unified-runtime") / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
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
    fonts = build_font_manifest(settings.font_directories())
    files = [
        txt,
        Path("tests/fixtures/docx/report.docx"),
        Path("tests/fixtures/pptx/deck.pptx"),
        Path("tests/fixtures/xlsx/features-shared.xlsx"),
        pdf,
    ]
    evidence: list[dict[str, object]] = []
    for identifier in AutomaticTranslationPolicy().davy_order:
        model = "gemma-4-31b-it" if identifier == "gemma" else identifier
        config = LlmEngineConfig(
            base_url=endpoint,
            api_key=credential,
            model=model,
            timeout_s=45,
            max_retries=2,
            deployment_revision="acceptance-2026-09-30",
            response_model_aliases=("gpt-oss-120b",)
            if identifier == "gpt-oss-120b-thinking"
            else (),
        )
        translator = Translator(config, fonts=fonts)
        try:
            for source in files:
                started = time.monotonic()
                output = root / f"{identifier}-{source.stem}.en{source.suffix}"
                record: dict[str, object] = {"model": identifier, "format": source.suffix[1:]}
                try:
                    result = translator.translate_document(
                        source, output, options=DocumentTranslationOptions(target=Language.EN)
                    )
                    record.update(
                        status="succeeded",
                        fit=result.fit_status.value,
                        output_bytes=output.stat().st_size,
                    )
                except Exception as exc:
                    record.update(status="failed", error_type=type(exc).__name__)
                record["seconds"] = round(time.monotonic() - started, 2)
                evidence.append(record)
                (root / "evidence.json").write_text(
                    json.dumps(evidence, indent=2), encoding="utf-8"
                )
                print(json.dumps(record), flush=True)
        finally:
            translator.close()


if __name__ == "__main__":
    main()
