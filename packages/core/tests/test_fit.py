"""Measurement, original-relative fit policy and fit through the pipeline (ADR-012).

Uses the synthetic "Test Sans" font (0.5 em Latin, 1 em CJK) so every expectation is arithmetic.
"""

from pathlib import Path

import pytest
from support.fakes import FakeTranslator, copy_fixture
from support.fonts import TEST_FONT, synthetic_font_manifest
from support.ooxml import NS, rewrite, xml

from doctranslator_core.config import DocumentLimits
from doctranslator_core.document import LayoutContainer, LayoutParagraph, LayoutRun
from doctranslator_core.fit.fitter import fit_container
from doctranslator_core.fit.fonts import FontLibrary
from doctranslator_core.fit.measure import measure
from doctranslator_core.pipeline import translate_document
from doctranslator_core.types import (
    DocumentTranslationOptions,
    FitOptions,
    FitStatus,
    FontManifest,
    Language,
)

A = f"{{{NS['a']}}}"


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> FontManifest:
    return synthetic_font_manifest(tmp_path_factory.mktemp("fonts"))


def box(
    text: str,
    *,
    width: float = 100,
    height: float | None = 12,
    size: float = 10,
    font: str = TEST_FONT,
) -> LayoutContainer:
    run = LayoutRun(text, size, font, font)
    return LayoutContainer(
        id="1",
        location="test",
        kind="shape",
        width_pt=width,
        height_pt=height,
        wrap=True,
        paragraphs=(LayoutParagraph(runs=(run,), end_run=LayoutRun("", size, font, font)),),
        line_metric="em",
    )


def test_latin_and_cjk_wrap(manifest: FontManifest) -> None:
    library = FontLibrary(manifest)
    latin = measure(box("aaaa " * 8), library)
    assert (latin.lines, latin.height_pt) == (2, pytest.approx(24.0))
    cjk = measure(box("汉" * 20), library)
    assert cjk.lines == 2
    closing = measure(box("汉" * 10 + "。"), library)  # the full stop hangs past the margin
    assert closing.lines == 1


def test_fitting_translation_is_unchanged(manifest: FontManifest) -> None:
    outcome = fit_container(box("汉字"), box("aaaa bbbb"), FitOptions(), FontLibrary(manifest))
    assert (outcome.status, outcome.sizes, outcome.entry) == ("unchanged", None, None)


def test_growth_is_shrunk_to_the_largest_fitting_size(manifest: FontManifest) -> None:
    outcome = fit_container(
        box("汉字"), box("aaaa bbbb cccc dddd eeee"), FitOptions(), FontLibrary(manifest)
    )
    assert outcome.status == "adjusted"
    assert outcome.sizes == [[8.0]]
    assert outcome.entry is not None and outcome.entry.reason == "shrunk_to_fit"


def test_growth_beyond_the_floor_is_unresolved_at_the_floor(manifest: FontManifest) -> None:
    outcome = fit_container(box("汉字"), box("aaaa " * 8), FitOptions(), FontLibrary(manifest))
    assert outcome.status == "unresolved"
    assert outcome.sizes == [[8.0]]  # max(8 pt, 70% of 10 pt)
    assert outcome.entry is not None and outcome.entry.reason == "overflow_at_floor"


def test_original_overflow_is_allowed_not_repaired(manifest: FontManifest) -> None:
    original = box("汉" * 20)  # two lines in a one-line box: the original already overflows
    outcome = fit_container(original, box("aaaa " * 8), FitOptions(), FontLibrary(manifest))
    assert outcome.status == "unchanged"


def test_small_runs_are_never_enlarged_or_shrunk(manifest: FontManifest) -> None:
    outcome = fit_container(
        box("汉字", size=6), box("aaaa " * 20, size=6), FitOptions(), FontLibrary(manifest)
    )
    assert outcome.status == "unresolved"
    assert outcome.sizes == [[6.0]]


def test_unmeasurable_containers_are_unresolved_and_untouched(manifest: FontManifest) -> None:
    missing = fit_container(
        box("汉字", font="Missing Font"),
        box("aaaa", font="Missing Font"),
        FitOptions(),
        FontLibrary(manifest),
    )
    assert (missing.status, missing.sizes) == ("unresolved", None)
    assert missing.entry is not None and missing.entry.reason == "font_unavailable"
    no_fonts = fit_container(box("汉字"), box("aaaa"), FitOptions(), None)
    assert no_fonts.entry is not None and no_fonts.entry.reason == "font_manifest_missing"
    unsupported = LayoutContainer(
        id="v",
        location="test",
        kind="shape",
        width_pt=100,
        height_pt=12,
        wrap=True,
        paragraphs=box("汉字").paragraphs,
        unsupported="vertical_text",
    )
    vertical = fit_container(unsupported, box("aaaa"), FitOptions(), FontLibrary(manifest))
    assert vertical.entry is not None and vertical.entry.reason == "vertical_text"
    assert vertical.sizes is None


def _deck_with_test_font(tmp_path: Path) -> Path:
    """The fixture deck with its slide-3 text box (220 x 80 pt) set in Test Sans 18 pt."""
    source = copy_fixture("pptx/deck.pptx", tmp_path)
    marker = "注意：数据截至九月底".encode()

    def use_test_font(data: bytes) -> bytes:
        end = data.index(marker)
        start = data.rindex(b"<a:rPr", 0, end)
        close = data.index(b">", start)
        properties = data[start:close]
        attributes = properties.rstrip(b"/")
        font = (f'<a:latin typeface="{TEST_FONT}"/><a:ea typeface="{TEST_FONT}"/>').encode()
        replacement = attributes + b' sz="1800">' + font + b"</a:rPr>"
        tail = data[close + 1 :]
        if not properties.endswith(b"/"):
            tail = tail[tail.index(b"</a:rPr>") + len(b"</a:rPr>") :]
        head = data[:start]
        # PowerPoint text boxes resize to fit by default; make this one a fixed-size container.
        autofit = head.rindex(b"<a:spAutoFit/>")
        head = head[:autofit] + b"<a:noAutofit/>" + head[autofit + len(b"<a:spAutoFit/>") :]
        return head + replacement + tail

    return rewrite(source, tmp_path / "fit.pptx", "ppt/slides/slide3.xml", use_test_font)


def _text_box_sizes(path: Path) -> list[str]:
    slide = xml(path, "ppt/slides/slide3.xml")
    for shape in slide.iter(f"{{{NS['p']}}}sp"):
        name = shape.find(f"{{{NS['p']}}}nvSpPr/{{{NS['p']}}}cNvPr")
        if (
            name is not None
            and name.get("name", "").startswith("TextBox")
            and shape.find(f".//{A}latin") is not None
        ):
            return [str(r.get("sz")) for r in shape.iter(f"{A}rPr")]
    raise AssertionError("text box not found")


def test_pipeline_adjusts_sizes_and_reports(tmp_path: Path, manifest: FontManifest) -> None:
    deck = _deck_with_test_font(tmp_path)
    long = "Note: this data covers everything up to the end of September. " * 2

    def engine(text: str, target: Language) -> str:
        return long if text.startswith("注意") else "EN"

    result = translate_document(
        FakeTranslator(engine),
        deck,
        tmp_path / "out.pptx",
        options=DocumentTranslationOptions(source=Language.ZH, target=Language.EN),
        fingerprint="f",
        limits=DocumentLimits(),
        fonts=manifest,
    )
    report = result.fit_report
    assert report.font_manifest == manifest.digest
    entries = [e for e in report.entries if e.location.startswith('slide 3 / shape "TextBox')]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.original_sizes_pt == [18.0]
    assert entry.final_sizes_pt[0] < 18.0
    assert f"{round(entry.final_sizes_pt[0] * 100)}" in _text_box_sizes(tmp_path / "out.pptx")
    assert report.status in (FitStatus.ADJUSTED, FitStatus.UNRESOLVED)
    assert report.inspected >= report.adjusted + report.unresolved + report.unchanged - 0


def test_pipeline_without_fonts_reports_unresolved_not_passed(tmp_path: Path) -> None:
    deck = copy_fixture("pptx/deck.pptx", tmp_path)
    result = translate_document(
        FakeTranslator(),
        deck,
        tmp_path / "out.pptx",
        options=DocumentTranslationOptions(source=Language.ZH, target=Language.EN),
        fingerprint="f",
        limits=DocumentLimits(),
    )
    assert result.fit_status is FitStatus.UNRESOLVED
    assert {e.reason for e in result.fit_report.entries} == {"font_manifest_missing"}


def test_translator_uses_its_font_manifest(
    tmp_path: Path, manifest: FontManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: Translator.translate_document must measure with the fonts it fingerprints."""
    from collections.abc import Sequence

    import doctranslator_core.translator as translator_module
    from doctranslator_core import MtEngineConfig, Translator
    from doctranslator_core.engines import TranslationEngine
    from doctranslator_core.types import EngineInfo, TranslationIdentity, TranslationMode

    class Engine(TranslationEngine):
        @property
        def info(self) -> EngineInfo:
            return EngineInfo(mode=TranslationMode.MT, model="fake", details={})

        @property
        def identity(self) -> TranslationIdentity:
            return TranslationIdentity(mode=TranslationMode.MT, model="fake", details={})

        def translate_batch(
            self,
            texts: Sequence[str],
            source: Language | None = None,
            target: Language | None = None,
        ) -> list[str]:
            return ["EN " + t for t in texts]

    def create_engine(config: object) -> TranslationEngine:
        return Engine()

    monkeypatch.setattr(translator_module, "create_engine", create_engine)
    deck = _deck_with_test_font(tmp_path)
    config = MtEngineConfig(model_dir=tmp_path, model_family="small100")
    with Translator(config, fonts=manifest) as translator:
        result = translator.translate_document(
            deck,
            tmp_path / "out.pptx",
            options=DocumentTranslationOptions(source=Language.ZH, target=Language.EN),
        )
    assert result.fit_report.font_manifest == manifest.digest
    assert "font_manifest_missing" not in {e.reason for e in result.fit_report.entries}
