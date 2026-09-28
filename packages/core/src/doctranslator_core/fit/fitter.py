"""Original-relative fit policy (README visual-quality layer 1, ADR-012, ``fit-v1``).

For each container: measure the original text, allow the larger of the container bounds and the
original extent on each constrained axis, measure the translation at its original sizes, and if it
exceeds the allowance shrink every run by a common scale in fixed steps down to each run's floor.
A run's floor is ``max(min_size_pt, min_scale * original)``, but never above its original size.
If the floor still does not fit, the floor sizes are kept and the container is unresolved. A
container that cannot be measured keeps its sizes and is unresolved. Formats never see this code;
they only describe containers and apply sizes.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from doctranslator_core.document import LayoutContainer
from doctranslator_core.fit.fonts import FontLibrary
from doctranslator_core.fit.measure import Measured, Unmeasurable, measure
from doctranslator_core.types import Extent, FitEntry, FitOptions

__all__ = ["SCALE_STEP", "SIZE_QUANTUM_PT", "TOLERANCE_PT", "FitOutcome", "fit_container"]

SCALE_STEP = 0.025
"""Common scale decrement per search step."""
SIZE_QUANTUM_PT = 0.5
"""Chosen sizes are rounded down to this quantum (Word stores half-points)."""
TOLERANCE_PT = 1.0
"""Measurement tolerance: extents within this many points of the allowance fit (ADR-012)."""
MAX_CANDIDATES = 40
"""Most shrink candidates measured for one container (ADR-012)."""


@dataclass(frozen=True)
class FitOutcome:
    status: Literal["unchanged", "adjusted", "unresolved"]
    sizes: list[list[float]] | None
    """Sizes to apply (per paragraph, per run), or ``None`` to leave the container as it is."""
    entry: FitEntry | None
    """Report entry for adjusted and unresolved containers."""


def fit_container(
    original: LayoutContainer,
    translated: LayoutContainer,
    options: FitOptions,
    library: FontLibrary | None,
) -> FitOutcome:
    base_sizes = [[r.size_pt for r in p.runs] for p in translated.paragraphs]
    flat = [s for sizes in base_sizes for s in sizes]
    if library is None:
        return _unresolved(translated, "font_manifest_missing", flat, None, None, None)
    try:
        source = measure(original, library)
        allowed = Extent(
            width_pt=_allow(
                original.width_pt, source.width_pt, horizontal=True, wrap=original.wrap
            ),
            height_pt=_allow(
                original.height_pt, source.height_pt, horizontal=False, wrap=original.wrap
            ),
        )
        current = measure(translated, library)
    except Unmeasurable as exc:
        return _unresolved(translated, exc.reason, flat, None, None, None)
    if _fits(current, allowed):
        return FitOutcome("unchanged", None, None)
    floors = [[_floor(s, options) for s in sizes] for sizes in base_sizes]
    scale = 1.0 - SCALE_STEP
    last: list[list[float]] | None = None
    final: Measured | None = None
    measured = 0
    while measured < MAX_CANDIDATES:
        candidate = [
            [max(floor, _quantize(size * scale)) for size, floor in zip(sizes, fl, strict=True)]
            for sizes, fl in zip(base_sizes, floors, strict=True)
        ]
        if candidate != last:
            try:
                final = measure(translated, library, candidate)
            except Unmeasurable as exc:
                return _unresolved(
                    translated, exc.reason, flat, allowed, _extent(source), _extent(current)
                )
            last = candidate
            measured += 1
            if _fits(final, allowed):
                return FitOutcome(
                    "adjusted",
                    candidate,
                    _entry(
                        translated,
                        "adjusted",
                        "shrunk_to_fit",
                        flat,
                        candidate,
                        allowed,
                        source,
                        current,
                        final,
                    ),
                )
        if candidate == floors:
            break
        scale -= SCALE_STEP
    return FitOutcome(
        "unresolved",
        floors,
        _entry(
            translated,
            "unresolved",
            "overflow_at_floor",
            flat,
            floors,
            allowed,
            source,
            current,
            final,
        ),
    )


def _allow(bound: float | None, extent: float, *, horizontal: bool, wrap: bool) -> float | None:
    """Allowed extent on one axis: the larger of the bound and the original's extent.

    A wrapping container's width is where lines break, so width is only constrained when the
    text does not wrap.
    """
    if bound is None or (horizontal and wrap):
        return None
    return max(bound, extent)


def _fits(measured: Measured, allowed: Extent) -> bool:
    if allowed.width_pt is not None and measured.width_pt > allowed.width_pt + TOLERANCE_PT:
        return False
    return not (
        allowed.height_pt is not None and measured.height_pt > allowed.height_pt + TOLERANCE_PT
    )


def _floor(size: float, options: FitOptions) -> float:
    if size <= options.min_size_pt:
        return size
    return max(options.min_size_pt, _quantize_up(size * options.min_scale))


def _quantize(size: float) -> float:
    return math.floor(size / SIZE_QUANTUM_PT + 1e-9) * SIZE_QUANTUM_PT


def _quantize_up(size: float) -> float:
    return math.ceil(size / SIZE_QUANTUM_PT - 1e-9) * SIZE_QUANTUM_PT


def _extent(measured: Measured | None) -> Extent | None:
    if measured is None:
        return None
    return Extent(width_pt=round(measured.width_pt, 2), height_pt=round(measured.height_pt, 2))


def _entry(
    container: LayoutContainer,
    status: Literal["adjusted", "unresolved"],
    reason: str,
    original_sizes: Sequence[float],
    final_sizes: Sequence[Sequence[float]] | None,
    allowed: Extent | None,
    source: Measured | None,
    translated: Measured | None,
    final: Measured | None,
) -> FitEntry:
    return FitEntry(
        location=container.location,
        kind=container.kind,
        status=status,
        reason=reason,
        original_sizes_pt=list(original_sizes),
        final_sizes_pt=[s for sizes in final_sizes for s in sizes]
        if final_sizes
        else list(original_sizes),
        allowed=allowed,
        original_extent=_extent(source),
        translated_extent=_extent(translated),
        final_extent=_extent(final) if final_sizes else _extent(translated),
    )


def _unresolved(
    container: LayoutContainer,
    reason: str,
    sizes: Sequence[float],
    allowed: Extent | None,
    source: Extent | None,
    translated: Extent | None,
) -> FitOutcome:
    entry = FitEntry(
        location=container.location,
        kind=container.kind,
        status="unresolved",
        reason=reason,
        original_sizes_pt=list(sizes),
        final_sizes_pt=list(sizes),
        allowed=allowed,
        original_extent=source,
        translated_extent=translated,
        final_extent=translated,
    )
    return FitOutcome("unresolved", None, entry)
