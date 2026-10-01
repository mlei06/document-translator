"""Cooperative fit skip (ADR-012 owner amendment) and the progress phases around it."""

import unicodedata
from pathlib import Path

import pytest
from support.fakes import FakeTranslator, copy_fixture
from support.fonts import TEST_FONT, synthetic_font_manifest
from support.ooxml import rewrite
from support.pdf import page_text, write_mixed

from doctranslator_core.config import DocumentLimits
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import (
    DocumentTranslationOptions,
    DocumentTranslationResult,
    FitStatus,
    FontManifest,
    Language,
    LayoutUnresolvableError,
    ProgressPhase,
    TranslationProgress,
)

OPTIONS = DocumentTranslationOptions(source=Language.ZH, target=Language.EN)
LONG = "a much longer English translation that will certainly overflow the small cell"


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> FontManifest:
    return synthetic_font_manifest(tmp_path_factory.mktemp("fonts"))


def _workbook(tmp_path: Path) -> Path:
    source = copy_fixture("xlsx/labels.xlsx", tmp_path)
    return rewrite(
        source,
        tmp_path / "fit.xlsx",
        "xl/styles.xml",
        lambda d: d.replace(b'<name val="Aptos Narrow"/>', f'<name val="{TEST_FONT}"/>'.encode()),
    )


def _run(
    path: Path,
    manifest: FontManifest | None,
    skip: object = None,
    progress: list[TranslationProgress] | None = None,
    target_text: str = LONG,
) -> DocumentTranslationResult:
    return translate_document(
        FakeTranslator(lambda text, _: target_text),
        path,
        path.with_name("out" + path.suffix),
        options=OPTIONS,
        fingerprint="f",
        limits=DocumentLimits(),
        fonts=manifest,
        on_progress=progress.append if progress is not None else None,
        should_skip_fit=skip,  # type: ignore[arg-type]
    )


def test_without_skip_fit_runs_normally(tmp_path: Path, manifest: FontManifest) -> None:
    result = _run(_workbook(tmp_path), manifest)
    assert result.fit_status is not FitStatus.SKIPPED
    assert result.fit_report.inspected > 0


def test_skip_before_fit_keeps_translation_and_records_skipped(
    tmp_path: Path, manifest: FontManifest
) -> None:
    result = _run(_workbook(tmp_path), manifest, skip=lambda: True)
    assert result.fit_status is FitStatus.SKIPPED
    assert result.fit_report.inspected == 0
    assert result.fit_report.entries == []
    assert result.output_path.is_file()
    assert result.counts.unique_inputs > 0


def test_skip_mid_fit_keeps_earlier_adjustments(tmp_path: Path, manifest: FontManifest) -> None:
    progress: list[TranslationProgress] = []

    def after_first_container() -> bool:
        return any(p.phase is ProgressPhase.FIT and p.done >= 1 for p in progress)

    (tmp_path / "full").mkdir()
    full = _run(_workbook(tmp_path / "full"), manifest)
    result = _run(_workbook(tmp_path), manifest, skip=after_first_container, progress=progress)
    assert result.fit_status is FitStatus.SKIPPED
    assert result.fit_report.inspected == 1 < full.fit_report.inspected
    assert all(e.status in ("adjusted", "unresolved") for e in result.fit_report.entries)


def test_txt_has_no_fit_to_skip(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("这是一个足够长的中文段落，用于测试跳过布局检查。\n", encoding="utf-8")
    result = _run(source, None, skip=lambda: True)
    assert result.fit_status is FitStatus.NOT_APPLICABLE


def test_pdf_skip_still_places_every_translation(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    result = _run(source, None, skip=lambda: True, target_text="Translated")
    assert result.fit_status is FitStatus.SKIPPED
    text = "".join(unicodedata.normalize("NFKC", page_text(result.output_path)).split())
    assert text.count("Translated") >= 9  # every translated unit is on the page


def test_pdf_skip_does_not_authorize_overlapping_placement(tmp_path: Path) -> None:
    source = write_mixed(tmp_path / "mixed.pdf")
    with pytest.raises(LayoutUnresolvableError):
        _run(source, None, skip=lambda: True)
    assert not (tmp_path / "out.pdf").exists()


def test_phases_include_apply_between_translate_and_fit(
    tmp_path: Path, manifest: FontManifest
) -> None:
    progress: list[TranslationProgress] = []
    _run(_workbook(tmp_path), manifest, progress=progress)
    phases = [p.phase for p in progress]
    assert phases[0] is ProgressPhase.EXTRACT and progress[0].done == 0
    first = {phase: phases.index(phase) for phase in dict.fromkeys(phases)}
    assert first[ProgressPhase.TRANSLATE] < first[ProgressPhase.APPLY] < first[ProgressPhase.FIT]
    assert first[ProgressPhase.FIT] < first[ProgressPhase.WRITE]
