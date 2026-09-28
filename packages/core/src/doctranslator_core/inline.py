"""Format-neutral inline structure: encode paragraphs for engines and map translations back.

A paragraph is a sequence of inline nodes produced by a format adapter:

- ``Text``: translatable text in one adapter style (the adapter owns what a style id means);
- ``Keep``: text that is never translated (protected terms, URLs, literal tag-like text);
- ``Obj``: a non-text object (break, tab, field, image, bookmark), never translated;
- ``Wrap``: a structural wrapper around other nodes (hyperlink, content control).

``encode`` turns a paragraph into the engine input: the text of the paragraph's dominant style is
plain, every other style run and every wrapper is a paired ``<gN>...</gN>`` tag, and every
``Keep``/``Obj`` is a standalone ``<xN/>`` tag. Tag ids are local to the paragraph and numbered in
encounter order, so identical paragraphs produce identical engine inputs.

``decode`` maps a validated translation back to inline nodes with the source's styles, wrappers and
objects (ADR-011). ``project`` and ``segmented_pieces``/``join_segmented`` implement the two
fallbacks used when an engine's tagged output does not validate. Formatting is never flattened.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from doctranslator_core.types import Language

__all__ = [
    "Encoded",
    "Inline",
    "Keep",
    "Obj",
    "Text",
    "Wrap",
    "decode",
    "encode",
    "join_segmented",
    "normalize_tag_whitespace",
    "plain_text",
    "project",
    "segmented_pieces",
    "strip_paired_tags",
    "validate",
]


@dataclass(frozen=True, slots=True)
class Text:
    text: str
    style: int


@dataclass(frozen=True, slots=True)
class Keep:
    text: str
    style: int


@dataclass(frozen=True, slots=True)
class Obj:
    key: int


@dataclass(frozen=True, slots=True)
class Wrap:
    key: int
    children: tuple[Inline, ...]


type Inline = Text | Keep | Obj | Wrap

TAG = re.compile(r"<(/?)g(\d+)>|<x(\d+)/>")
_TAG_LIKE = re.compile(r"</?\s*[gx]\s*\d+\s*/?\s*>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Group:
    """What a paired tag stands for: a style run (``wrap`` is None) or a wrapper."""

    style: int | None
    wrap: int | None


@dataclass(frozen=True)
class Encoded:
    """A paragraph's engine input plus what is needed to map a translation back."""

    text: str
    base_style: int
    groups: dict[int, _Group] = field(default_factory=dict[int, _Group])
    objects: dict[int, Keep | Obj] = field(default_factory=dict[int, Keep | Obj])
    parents: dict[str, str] = field(default_factory=dict[str, str])
    """Parent tag of every tag (``"g1"``/``"x2"`` -> ``"g1"`` or ``""`` at top level)."""

    @property
    def has_tags(self) -> bool:
        return bool(self.groups or self.objects)


def plain_text(nodes: Sequence[Inline]) -> str:
    """The paragraph's visible text, including kept text, without objects."""
    parts: list[str] = []
    for node in nodes:
        match node:
            case Text(text=t) | Keep(text=t):
                parts.append(t)
            case Wrap(children=children):
                parts.append(plain_text(children))
            case Obj():
                pass
    return "".join(parts)


def _dominant_style(nodes: Sequence[Inline]) -> int | None:
    weights: Counter[int] = Counter()

    def visit(items: Sequence[Inline]) -> None:
        for node in items:
            match node:
                case Text(text=t, style=s):
                    weights[s] += len(t.strip()) or 0
                case Wrap(children=children):
                    visit(children)
                case _:
                    pass

    visit(nodes)
    if not weights:
        return None
    best = max(weights.values())
    for node_style in _styles_in_order(nodes):
        if weights[node_style] == best:
            return node_style
    return None


def _styles_in_order(nodes: Sequence[Inline]) -> list[int]:
    order: list[int] = []
    for node in nodes:
        match node:
            case Text(style=s):
                order.append(s)
            case Wrap(children=children):
                order.extend(_styles_in_order(children))
            case _:
                pass
    return order


def _normalize(nodes: Sequence[Inline]) -> list[Inline]:
    """Merge adjacent same-style text and absorb whitespace-only style changes.

    A whitespace-only ``Text`` between two runs of one style takes that style, and otherwise
    the style of its predecessor, so an invisible style change does not become a tag.
    """
    items: list[Inline] = []
    for node in nodes:
        if isinstance(node, Wrap):
            items.append(Wrap(node.key, tuple(_normalize(node.children))))
        elif isinstance(node, Text) and not node.text:
            continue
        else:
            items.append(node)
    for index, node in enumerate(items):
        if isinstance(node, Text) and not node.text.strip():
            before = items[index - 1] if index > 0 else None
            after = items[index + 1] if index + 1 < len(items) else None
            if isinstance(before, Text):
                items[index] = Text(node.text, before.style)
            elif isinstance(after, Text):
                items[index] = Text(node.text, after.style)
    merged: list[Inline] = []
    for node in items:
        last = merged[-1] if merged else None
        if isinstance(node, Text) and isinstance(last, Text) and last.style == node.style:
            merged[-1] = Text(last.text + node.text, node.style)
        else:
            merged.append(node)
    return merged


def encode(nodes: Sequence[Inline]) -> Encoded:
    """Encode a paragraph as engine input with local, encounter-ordered tag ids."""
    normalized = _normalize(nodes)
    base = _dominant_style(normalized)
    base_style = base if base is not None else 0
    groups: dict[int, _Group] = {}
    objects: dict[int, Keep | Obj] = {}
    parents: dict[str, str] = {}
    out: list[str] = []

    def emit(items: Sequence[Inline], parent: str, inherited: int) -> None:
        for node in items:
            match node:
                case Text(text=t, style=s):
                    if s == inherited:
                        out.append(t)
                    else:
                        ident = len(groups) + 1
                        groups[ident] = _Group(style=s, wrap=None)
                        parents[f"g{ident}"] = parent
                        out.append(f"<g{ident}>{t}</g{ident}>")
                case Keep() | Obj():
                    ident = len(objects) + 1
                    objects[ident] = node
                    parents[f"x{ident}"] = parent
                    out.append(f"<x{ident}/>")
                case Wrap(key=k, children=children):
                    ident = len(groups) + 1
                    groups[ident] = _Group(style=None, wrap=k)
                    parents[f"g{ident}"] = parent
                    out.append(f"<g{ident}>")
                    emit(children, f"g{ident}", inherited)
                    out.append(f"</g{ident}>")

    emit(normalized, "", base_style)
    return Encoded("".join(out), base_style, groups, objects, parents)


def protect_tag_like(nodes: Sequence[Inline]) -> list[Inline]:
    """Turn literal text that looks like an engine tag into ``Keep`` so it cannot be confused."""
    result: list[Inline] = []
    for node in nodes:
        match node:
            case Text(text=t, style=s) if _TAG_LIKE.search(t):
                last = 0
                for match in _TAG_LIKE.finditer(t):
                    if match.start() > last:
                        result.append(Text(t[last : match.start()], s))
                    result.append(Keep(match.group(0), s))
                    last = match.end()
                if last < len(t):
                    result.append(Text(t[last:], s))
            case Wrap(key=k, children=children):
                result.append(Wrap(k, tuple(protect_tag_like(children))))
            case _:
                result.append(node)
    return result


def _structure(text: str) -> tuple[Counter[str], dict[str, str], bool, dict[str, str]]:
    """Tag inventory, parents, well-formedness and the text inside each paired tag."""
    inventory: Counter[str] = Counter()
    parents: dict[str, str] = {}
    inner: dict[str, list[str]] = {}
    stack: list[str] = []
    ok = True
    last = 0
    for match in TAG.finditer(text):
        chunk = text[last : match.start()]
        for open_tag in stack:
            inner.setdefault(open_tag, []).append(chunk)
        last = match.end()
        closing, g_id, x_id = match.groups()
        if x_id:
            inventory[f"x{x_id}"] += 1
            parents[f"x{x_id}"] = stack[-1] if stack else ""
        elif closing:
            inventory[f"/g{g_id}"] += 1
            if stack and stack[-1] == f"g{g_id}":
                stack.pop()
            else:
                ok = False
        else:
            inventory[f"g{g_id}"] += 1
            parents[f"g{g_id}"] = stack[-1] if stack else ""
            stack.append(f"g{g_id}")
    if stack:
        ok = False
    return inventory, parents, ok, {k: "".join(v) for k, v in inner.items()}


def validate(encoded: Encoded, output: str) -> str | None:
    """``None`` if ``output``'s tags correspond to ``encoded``; otherwise the failure reason."""
    expected = Counter(
        [f"g{i}" for i in encoded.groups]
        + [f"/g{i}" for i in encoded.groups]
        + [f"x{i}" for i in encoded.objects]
    )
    inventory, parents, well_formed, inner = _structure(output)
    if inventory != expected:
        return "tag_inventory"
    if not well_formed:
        return "tag_nesting"
    if parents != encoded.parents:
        return "tag_parent"
    for ident, group in encoded.groups.items():
        if group.style is not None and not inner.get(f"g{ident}", "").strip():
            return "empty_span"
    if not TAG.sub("", output).strip() and TAG.sub("", encoded.text).strip():
        return "empty_output"
    return None


_OPEN_WS = re.compile(r"(<g\d+>)(\s+)")
_CLOSE_WS = re.compile(r"(\s+)(</g\d+>)")


def normalize_tag_whitespace(output: str) -> str:
    """Move whitespace just inside paired tags to outside them, then collapse doubled spaces."""
    previous = None
    text = output
    while previous != text:
        previous = text
        text = _OPEN_WS.sub(lambda m: m.group(2) + m.group(1), text)
        text = _CLOSE_WS.sub(lambda m: m.group(2) + m.group(1), text)
    text = re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)
    return text


def decode(encoded: Encoded, output: str) -> list[Inline]:
    """Map a validated translation back to inline nodes."""
    result: list[Inline] = []
    stack: list[tuple[int, list[Inline], int]] = []  # (tag id, collected nodes, style)
    current: list[Inline] = result
    style = encoded.base_style
    last = 0
    for match in TAG.finditer(output):
        chunk = output[last : match.start()]
        if chunk:
            current.append(Text(chunk, style))
        last = match.end()
        closing, g_id, x_id = match.groups()
        if x_id:
            current.append(encoded.objects[int(x_id)])
        elif not closing:
            group = encoded.groups[int(g_id)]
            stack.append((int(g_id), current, style))
            current = []
            if group.style is not None:
                style = group.style
        else:
            ident, parent_nodes, parent_style = stack.pop()
            group = encoded.groups[ident]
            if group.wrap is not None:
                parent_nodes.append(Wrap(group.wrap, tuple(current)))
            else:
                parent_nodes.extend(current)
            current = parent_nodes
            style = parent_style
    tail = output[last:]
    if tail:
        current.append(Text(tail, style))
    return _normalize(result)


def strip_paired_tags(encoded_text: str) -> str:
    """The engine input without its paired tags; standalone ``<xN/>`` tags stay."""
    return re.sub(r"</?g\d+>", "", encoded_text)


def span_texts(encoded: Encoded) -> dict[int, str]:
    """Text inside each paired tag with all tags removed, for projection."""
    _, _, _, inner = _structure(encoded.text)
    return {int(k[1:]): TAG.sub("", v) for k, v in inner.items()}


def project(encoded: Encoded, plain_output: str, span_outputs: dict[int, str]) -> str | None:
    """Rebuild a tagged translation from the paragraph's plain translation.

    ``plain_output`` is the translation of ``strip_paired_tags(encoded.text)``; ``span_outputs``
    maps each paired tag id to the separate translation of its text. Every span translation must
    occur exactly once in the plain translation (case-insensitively), nested spans inside their
    parents and sibling spans disjoint. Returns ``None`` when that does not hold.
    """
    x_only = Encoded(
        strip_paired_tags(encoded.text),
        encoded.base_style,
        {},
        encoded.objects,
        {k: "" for k in encoded.parents if k.startswith("x")},
    )
    if validate(x_only, plain_output) not in (None, "tag_parent"):
        return None
    lowered = plain_output.lower()
    found: dict[int, tuple[int, int]] = {}
    for ident in encoded.groups:
        needle = span_outputs.get(ident, "").strip().rstrip(_FINAL_STOPS).lower()
        if not needle:
            return None
        starts = [m.start() for m in re.finditer(re.escape(needle), lowered)]
        if len(starts) != 1:
            return None
        found[ident] = (starts[0], starts[0] + len(needle))
    for ident in encoded.groups:
        parent = encoded.parents[f"g{ident}"]
        start, end = found[ident]
        if parent:
            p_start, p_end = found[int(parent[1:])]
            if not (p_start <= start and end <= p_end):
                return None
        for other, (o_start, o_end) in found.items():
            if other == ident:
                continue
            nested = encoded.parents[f"g{other}"] == f"g{ident}" or parent == f"g{other}"
            overlap = start < o_end and o_start < end
            if overlap and not nested and not _is_ancestor(encoded, ident, other):
                return None
    inserts: list[tuple[int, int, int, str]] = []
    for ident, (start, end) in found.items():
        depth = _depth(encoded, ident)
        inserts.append((start, 1, depth, f"<g{ident}>"))
        inserts.append((end, 0, -depth, f"</g{ident}>"))
    out = plain_output
    for position, _, _, tag in sorted(inserts, reverse=True):
        out = out[:position] + tag + out[position:]
    if validate(encoded, out) is not None:
        return None
    return out


_FINAL_STOPS = "." + chr(0x3002) + chr(0xFF0E)


def _depth(encoded: Encoded, ident: int) -> int:
    depth = 0
    parent = encoded.parents[f"g{ident}"]
    while parent:
        depth += 1
        parent = encoded.parents[parent]
    return depth


def _is_ancestor(encoded: Encoded, a: int, b: int) -> bool:
    for child, ancestor in ((a, b), (b, a)):
        parent = encoded.parents[f"g{child}"]
        while parent:
            if parent == f"g{ancestor}":
                return True
            parent = encoded.parents[parent]
    return False


def segmented_pieces(nodes: Sequence[Inline]) -> list[str]:
    """Texts to translate separately for the per-span fallback, in paragraph order."""
    pieces: list[str] = []
    for node in _normalize(nodes):
        match node:
            case Text(text=t):
                pieces.append(t)
            case Wrap(children=children):
                pieces.extend(segmented_pieces(children))
            case _:
                pass
    return pieces


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x3040 <= o <= 0x30FF
        or 0x3400 <= o <= 0x4DBF
        or 0x4E00 <= o <= 0x9FFF
        or 0xF900 <= o <= 0xFAFF
        or 0xFF00 <= o <= 0xFFEF
        or 0x3000 <= o <= 0x303F
    )


def join_segmented(
    nodes: Sequence[Inline], translations: dict[str, str], target: Language
) -> list[Inline]:
    """Rebuild a paragraph from separately translated pieces, keeping every node's formatting.

    ``translations`` maps each piece from ``segmented_pieces`` to its translation. At a boundary
    between two text leaves (translated or kept), English/Spanish targets get one space when neither
    side has whitespace and both sides are letters or digits; for Chinese/Japanese targets
    whitespace between two CJK characters is removed. Objects (tabs, breaks) are boundaries that
    are never padded.
    """
    normalized = _normalize(nodes)
    leaves: list[str | None] = []  # translated text per Text/Keep leaf; None for objects

    def collect(items: Sequence[Inline]) -> None:
        for node in items:
            match node:
                case Text(text=t):
                    leaves.append(translations.get(t, t))
                case Keep(text=t):
                    leaves.append(t)
                case Obj():
                    leaves.append(None)
                case Wrap(children=children):
                    collect(children)

    collect(normalized)
    latin_target = target in (Language.EN, Language.ES)
    kept = _kept_leaf_indexes(normalized)
    for i in range(len(leaves) - 1):
        a, b = leaves[i], leaves[i + 1]
        if not a or not b:
            continue
        if latin_target:
            if not a[-1].isspace() and not b[0].isspace() and a[-1].isalnum() and b[0].isalnum():
                if i in kept and i + 1 not in kept:
                    leaves[i + 1] = " " + b
                else:
                    leaves[i] = a + " "
        else:
            left, right = a.rstrip(), b.lstrip()
            if left and right and _is_cjk(left[-1]) and _is_cjk(right[0]):
                if i not in kept:
                    leaves[i] = left
                if i + 1 not in kept:
                    leaves[i + 1] = right

    values = iter(leaves)

    def rebuild(items: Sequence[Inline]) -> list[Inline]:
        out: list[Inline] = []
        for node in items:
            match node:
                case Text(style=s):
                    out.append(Text(next(values) or "", s))
                case Keep() | Obj():
                    next(values)
                    out.append(node)
                case Wrap(key=k, children=children):
                    out.append(Wrap(k, tuple(rebuild(children))))
        return out

    return _normalize(rebuild(normalized))


def _kept_leaf_indexes(nodes: Sequence[Inline]) -> set[int]:
    kept: set[int] = set()
    counter = 0

    def visit(items: Sequence[Inline]) -> None:
        nonlocal counter
        for node in items:
            match node:
                case Wrap(children=children):
                    visit(children)
                case Keep():
                    kept.add(counter)
                    counter += 1
                case _:
                    counter += 1

    visit(nodes)
    return kept
