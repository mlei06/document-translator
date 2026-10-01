"""Bounded format-neutral Office candidates and explicit target font selection."""

from collections.abc import Callable
from dataclasses import replace
from time import perf_counter

from doctranslator_core.document import LayoutContainer, LayoutPatch, LayoutRun
from doctranslator_core.fit.fitter import FitOutcome, fit_container
from doctranslator_core.fit.fonts import FontLibrary
from doctranslator_core.fit.measure import is_east_asian
from doctranslator_core.types import FitEntry, FitOptions

FALLBACKS = (
    "Microsoft YaHei",
    "Yu Gothic",
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Noto Sans",
    "Arial",
    "Liberation Sans",
)


def target_fonts(container: LayoutContainer, library: FontLibrary) -> LayoutContainer:
    """Select one covering face per script slot; never guess source rendering."""

    style_unknown = False

    def resolve(run: LayoutRun) -> LayoutRun:
        nonlocal style_unknown
        slots = {}
        for east, slot in ((False, "latin_font"), (True, "east_asian_font")):
            chars = {ord(c) for c in run.text if not c.isspace() and is_east_asian(c) == east}
            if not chars:
                continue
            declared = getattr(run, slot)
            names = (declared, *run.fallback_fonts, *FALLBACKS)
            unmatched_style = False
            selected = False
            for name in names:
                if not name:
                    continue
                font = library.resolve(name, bold=run.bold, italic=run.italic)
                if (
                    font
                    and chars <= font.codepoints
                    and (font.face.bold != run.bold or font.face.italic != run.italic)
                ):
                    unmatched_style = True
                if (
                    font
                    and chars <= font.codepoints
                    and font.face.bold == run.bold
                    and font.face.italic == run.italic
                ):
                    # Even theme/metric aliases are serialized to the actual measured face.
                    if name != declared or not font.exact:
                        slots[slot] = font.face.family
                    selected = True
                    break
            if unmatched_style and not selected:
                style_unknown = True
        return replace(run, **slots)

    paragraphs = tuple(
        replace(p, runs=tuple(resolve(r) for r in p.runs)) for p in container.paragraphs
    )
    return replace(
        container,
        paragraphs=paragraphs,
        unsupported=container.unsupported
        or ("target_font_style_unavailable" if style_unknown else None),
    )


def fit_office_container(
    original: LayoutContainer,
    translated: LayoutContainer,
    options: FitOptions,
    library: FontLibrary | None,
    apply_patch: Callable[[LayoutPatch], None],
    refresh_context: Callable[[], list[LayoutContainer]],
    should_stop: Callable[[], bool] | None = None,
) -> FitOutcome:
    started = perf_counter()
    stop = should_stop or (lambda: False)
    current = translated
    if library is not None and not stop():
        resolved = target_fonts(current, library)
        font_patch = replace(resolved, unsupported=current.unsupported)
        if font_patch != current:
            apply_patch(LayoutPatch(current, font_patch, "fonts"))
            current = next(c for c in refresh_context() if c.id == current.id)
        if resolved.unsupported != current.unsupported:
            current = replace(current, unsupported=resolved.unsupported)
    fonts_finished = perf_counter()
    profiles = [current]
    if current.growth_bounds_pt and current.bounds_pt and current.content_bounds_pt:
        b, g, c = current.bounds_pt, current.growth_bounds_pt, current.content_bounds_pt
        dw, dh = g[2] - b[2], g[3] - b[3]
        profiles.append(
            replace(
                current,
                bounds_pt=g,
                content_bounds_pt=(c[0], c[1], c[2] + dw, c[3] + dh),
                width_pt=(current.width_pt + dw if current.width_pt is not None else None),
                height_pt=(current.height_pt + dh if current.height_pt is not None else None),
            )
        )
    grown = profiles[-1]
    for fraction in (0.75, 0.5) if current.spacing_supported else ():
        candidate = replace(
            grown,
            paragraphs=tuple(
                replace(
                    p,
                    space_before_pt=p.space_before_pt * fraction,
                    space_after_pt=p.space_after_pt * fraction,
                )
                for p in grown.paragraphs
            ),
        )
        if candidate != grown:
            profiles.append(candidate)
    best = None
    for index, profile in enumerate(profiles[:4]):
        # A repair's nominal bounds become available, but an unknown source remains unknown.
        baseline = original
        outcome = fit_container(baseline, profile, options, library, stop, independent_source=True)
        if outcome.status == "skipped":
            return outcome
        fits = outcome.status in ("unchanged", "adjusted") or (
            outcome.entry is not None and outcome.entry.reason == "source_measurement_unknown"
        )
        sizes = outcome.sizes or [[r.size_pt for r in p.runs] for p in profile.paragraphs]
        score = (not fits, -sum(s for p in sizes for s in p), index)
        if best is None or score < best[0]:
            best = (score, profile, outcome)
    if best is None:
        raise RuntimeError("no fit candidate")
    _, selected, outcome = best
    repair_started = perf_counter()
    if stop():
        return FitOutcome("skipped", None, None)
    if selected.bounds_pt != current.bounds_pt:
        geometry = replace(
            current,
            bounds_pt=selected.bounds_pt,
            content_bounds_pt=selected.content_bounds_pt,
            width_pt=selected.width_pt,
            height_pt=selected.height_pt,
        )
        apply_patch(LayoutPatch(current, geometry, "geometry"))
        current = next(c for c in refresh_context() if c.id == current.id)
    if selected.paragraphs != current.paragraphs:
        apply_patch(
            LayoutPatch(current, replace(current, paragraphs=selected.paragraphs), "spacing")
        )
    if selected != translated and outcome.status == "unchanged":
        sizes = [r.size_pt for p in current.paragraphs for r in p.runs]
        entry = FitEntry(
            location=current.location,
            kind=current.kind,
            status="adjusted",
            reason="layout_repaired",
            original_sizes_pt=sizes,
            final_sizes_pt=sizes,
            allowed=None,
            original_extent=None,
            translated_extent=None,
            final_extent=None,
        )
        outcome = FitOutcome("adjusted", outcome.sizes, entry)
    if outcome.entry is not None:
        fonts_before = tuple(
            (r.latin_font, r.east_asian_font) for p in translated.paragraphs for r in p.runs
        )
        fonts_after = tuple(
            (r.latin_font, r.east_asian_font) for p in selected.paragraphs for r in p.runs
        )
        spacing_before = tuple((p.space_before_pt, p.space_after_pt) for p in translated.paragraphs)
        spacing_after = tuple((p.space_before_pt, p.space_after_pt) for p in selected.paragraphs)
        operations = tuple(
            name
            for name, changed in (
                ("fonts", fonts_before != fonts_after),
                ("geometry", translated.bounds_pt != selected.bounds_pt),
                ("paragraph_spacing", spacing_before != spacing_after),
                ("font_sizes", outcome.sizes is not None),
            )
            if changed
        )
        entry = outcome.entry.model_copy(
            update={
                "operations": operations,
                "original_bounds_pt": translated.bounds_pt,
                "final_bounds_pt": selected.bounds_pt,
                "original_fonts": fonts_before,
                "final_fonts": fonts_after,
                "original_spacing_pt": spacing_before,
                "final_spacing_pt": spacing_after,
                "timings_s": {
                    "font_resolution": fonts_finished - started,
                    "measurement": repair_started - fonts_finished,
                    "repair": perf_counter() - repair_started,
                },
            }
        )
        outcome = replace(outcome, entry=entry)
    return outcome
