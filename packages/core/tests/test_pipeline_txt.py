"""Document pipeline behavior exercised through TXT (the simplest adapter)."""

import hashlib
from pathlib import Path

import pytest
from support.fakes import FakeTranslator

from doctranslator_core.config import DocumentLimits
from doctranslator_core.pipeline import PIPELINE_BATCH, translate_document
from doctranslator_core.types import (
    DocumentFormat,
    DocumentLimitError,
    DocumentTranslationOptions,
    DocumentTranslationResult,
    EngineResponseError,
    FitStatus,
    InvalidDocumentError,
    Language,
    OutputPathError,
    ProgressPhase,
    SourceLanguageAmbiguousError,
    TranslationProgress,
    UnsupportedDocumentError,
)

ZH_TO_EN = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)


def run(
    translator: FakeTranslator,
    source: Path,
    options: DocumentTranslationOptions = ZH_TO_EN,
    **kwargs: object,
) -> DocumentTranslationResult:
    output = source.with_name("out" + source.suffix)
    return translate_document(
        translator,
        source,
        output,
        options=options,
        fingerprint="f",
        limits=kwargs.pop("limits", DocumentLimits()),  # type: ignore[arg-type]
        on_progress=kwargs.pop("on_progress", None),  # type: ignore[arg-type]
    )


def write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_line_structure_whitespace_and_endings_are_preserved(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", "  你好\r\n\r\n世界  \n\n最后一行".encode())
    before = digest(source)
    result = run(FakeTranslator(), source)
    assert (tmp_path / "out.txt").read_bytes() == b"  EN:xx\r\n\r\nEN:xx  \n\nEN:xxxx"
    assert digest(source) == before
    assert result.format is DocumentFormat.TXT
    assert result.fit_status is FitStatus.NOT_APPLICABLE
    assert result.counts.segments == 3


def test_bom_and_utf16_are_preserved(tmp_path: Path) -> None:
    utf8 = write(tmp_path / "in.txt", b"\xef\xbb\xbf" + "你好\n".encode())
    run(FakeTranslator(), utf8)
    assert (tmp_path / "out.txt").read_bytes() == b"\xef\xbb\xbfEN:xx\n"
    utf16 = write(tmp_path / "u16.txt", b"\xff\xfe" + "你好\n".encode("utf-16-le"))
    translate_document(
        FakeTranslator(),
        utf16,
        tmp_path / "u16-out.txt",
        options=ZH_TO_EN,
        fingerprint="f",
        limits=DocumentLimits(),
    )
    assert (tmp_path / "u16-out.txt").read_bytes() == b"\xff\xfe" + "EN:xx\n".encode("utf-16-le")


def test_invalid_utf8_requires_an_explicit_encoding(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", "你好".encode("gbk"))
    with pytest.raises(InvalidDocumentError, match="not valid utf-8"):
        run(FakeTranslator(), source)
    result = run(
        FakeTranslator(),
        source,
        DocumentTranslationOptions(source=Language.ZH, target=Language.EN, txt_encoding="gbk"),
    )
    assert (tmp_path / "out.txt").read_bytes() == b"EN:xx"
    assert result.counts.segments == 1


def test_repeated_lines_reach_the_engine_once_across_batches(tmp_path: Path) -> None:
    lines = [f"句子{i}" for i in range(PIPELINE_BATCH + 10)]
    content = "\n".join([*lines, "重复", *lines[:5], "重复"])
    source = write(tmp_path / "in.txt", content.encode())
    translator = FakeTranslator()
    result = run(translator, source)
    assert len(translator.batches) == 2
    assert len(translator.inputs) == len(set(translator.inputs)) == PIPELINE_BATCH + 11
    assert result.counts.unique_inputs == PIPELINE_BATCH + 11
    out = (tmp_path / "out.txt").read_text(encoding="utf-8").split("\n")
    assert out[PIPELINE_BATCH + 10] == out[-1] == "EN:xx"


def test_numbers_urls_and_other_script_lines_pass_through(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", "12,345.67\nhttps://example.com/a\nAPI v2\n中文\n".encode())
    translator = FakeTranslator()
    result = run(translator, source)
    assert translator.inputs == ["中文"]
    assert result.counts.passed_through == 3
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == (
        "12,345.67\nhttps://example.com/a\nAPI v2\nEN:xx\n"
    )


def test_protected_url_and_terms_inside_prose(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", "请访问 https://example.com/x 使用 Lenny 工具。".encode())
    translator = FakeTranslator()
    options = DocumentTranslationOptions(
        source=Language.ZH, target=Language.EN, protected_terms=("Lenny",)
    )
    run(translator, source, options)
    assert translator.inputs == ["请访问 <x1/> 使用 <x2/> 工具。"]
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == (
        "EN:xxx https://example.com/x xx Lenny xx。".replace("。", "x")
    )


def test_progress_is_reported_in_phase_order(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", "你好\n世界\n".encode())
    events: list[TranslationProgress] = []
    run(FakeTranslator(), source, on_progress=events.append)
    phases = [e.phase for e in events]
    assert phases == [
        ProgressPhase.EXTRACT,
        ProgressPhase.EXTRACT,
        ProgressPhase.TRANSLATE,
        ProgressPhase.TRANSLATE,
        ProgressPhase.APPLY,
        ProgressPhase.APPLY,
        ProgressPhase.WRITE,
        ProgressPhase.WRITE,
    ]  # TXT has no fixed-size containers, so there is no fit phase
    assert (events[3].done, events[3].total) == (2, 2)


@pytest.mark.parametrize(
    "phase",
    [ProgressPhase.EXTRACT, ProgressPhase.TRANSLATE, ProgressPhase.APPLY, ProgressPhase.WRITE],
)
def test_cancellation_leaves_no_output_or_temporary_files(
    tmp_path: Path, phase: ProgressPhase
) -> None:
    source = write(tmp_path / "in.txt", "你好\n".encode())

    class CancelledError(Exception):
        pass

    def cancel(event: TranslationProgress) -> None:
        if event.phase is phase and event.done == event.total:
            raise CancelledError

    with pytest.raises(CancelledError):
        run(FakeTranslator(), source, on_progress=cancel)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.txt"]


def test_output_path_rules(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", "你好".encode())
    existing = write(tmp_path / "exists.txt", b"keep")
    translator = FakeTranslator()
    for output in (existing, source, tmp_path / "missing-dir" / "out.txt"):
        with pytest.raises(OutputPathError):
            translate_document(
                translator,
                source,
                output,
                options=ZH_TO_EN,
                fingerprint="f",
                limits=DocumentLimits(),
            )
    assert existing.read_bytes() == b"keep"
    assert translator.batches == []


def test_source_detection_and_unchanged_copies(tmp_path: Path) -> None:
    zh = write(tmp_path / "zh.txt", "这是一个用于检测的中文句子，内容足够长。".encode())
    result = translate_document(
        FakeTranslator(),
        zh,
        tmp_path / "zh-out.txt",
        options=DocumentTranslationOptions(target=Language.EN),
        fingerprint="f",
        limits=DocumentLimits(),
    )
    assert result.source_resolved is Language.ZH
    assert result.source_requested == "auto"
    assert {d.code for d in result.diagnostics} == {"detected_without_kana"}

    ja = write(tmp_path / "ja.txt", "これは日本語の文章です。".encode())
    same = translate_document(
        FakeTranslator(),
        ja,
        tmp_path / "ja-out.txt",
        options=DocumentTranslationOptions(target=Language.JA),
        fingerprint="f",
        limits=DocumentLimits(),
    )
    assert same.source_resolved is Language.JA
    assert [d.code for d in same.diagnostics] == ["already_target_language"]
    assert (tmp_path / "ja-out.txt").read_bytes() == ja.read_bytes()

    numbers = write(tmp_path / "n.txt", b"123\n456\n")
    empty = translate_document(
        FakeTranslator(),
        numbers,
        tmp_path / "n-out.txt",
        options=DocumentTranslationOptions(target=Language.EN),
        fingerprint="f",
        limits=DocumentLimits(),
    )
    assert empty.source_resolved is None
    assert [d.code for d in empty.diagnostics] == ["no_translatable_text"]

    short = write(tmp_path / "s.txt", "你好".encode())
    with pytest.raises(SourceLanguageAmbiguousError):
        translate_document(
            FakeTranslator(),
            short,
            tmp_path / "s-out.txt",
            options=DocumentTranslationOptions(target=Language.EN),
            fingerprint="f",
            limits=DocumentLimits(),
        )


def test_explicit_source_equal_to_target_is_rejected(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", b"hello")
    with pytest.raises(ValueError, match="both"):
        run(
            FakeTranslator(),
            source,
            DocumentTranslationOptions(source=Language.EN, target=Language.EN),
        )


def test_empty_engine_output_fails_without_publishing(tmp_path: Path) -> None:
    source = write(tmp_path / "in.txt", "你好\n".encode())
    with pytest.raises(EngineResponseError):
        run(FakeTranslator(lambda text, target: " "), source)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.txt"]


def test_limits_and_unsupported_inputs(tmp_path: Path) -> None:
    big = write(tmp_path / "big.txt", "你好\n".encode() * 10)
    with pytest.raises(DocumentLimitError):
        run(FakeTranslator(), big, limits=DocumentLimits(max_text_bytes=10))
    many = write(tmp_path / "many.txt", "你好\n世界\n再见\n".encode())
    with pytest.raises(DocumentLimitError):
        run(FakeTranslator(), many, limits=DocumentLimits(max_segments=2))
    csv = write(tmp_path / "data.csv", b"a,b\n")
    with pytest.raises(UnsupportedDocumentError, match="extension"):
        run(FakeTranslator(), csv)
    ole = write(tmp_path / "old.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    with pytest.raises(UnsupportedDocumentError, match="legacy"):
        run(FakeTranslator(), ole)
    fake_pptx = write(tmp_path / "text.pptx", b"just text")
    with pytest.raises(InvalidDocumentError):
        run(FakeTranslator(), fake_pptx)
    pdf_as_txt = write(tmp_path / "x.txt", b"%PDF-1.7\n")
    with pytest.raises(UnsupportedDocumentError, match="PDF but the extension"):
        run(FakeTranslator(), pdf_as_txt)
