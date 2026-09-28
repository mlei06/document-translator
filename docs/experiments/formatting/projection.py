"""Span projection for tagged outputs that failed validation (P2.0 formatting gate).

Run after spike.py, from the repository root:

    uv run python docs/experiments/formatting/projection.py [--mt-model-dir DIR]

For every MT row whose XML-tagged output failed validation, translate the paragraph with only its
standalone <xN/> placeholders kept, translate each paired span's text on its own, and look for each
span translation in the paragraph translation (case-insensitive, whole occurrence, exactly once,
nesting respected). If every span is found, the spans are wrapped around those occurrences.
Records how many failures projection recovers and their outputs for inspection.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from doctranslator_core import MtEngineConfig, Translator
from doctranslator_core.types import Language

RESULTS = Path("data/experiments/formatting/results.json")
PAIRED = re.compile(r"</?g\d+>")
SPAN = re.compile(r"<g(\d+)>(.*?)</g\1>", re.DOTALL)


def innermost_first(text: str) -> list[tuple[str, str]]:
    """(id, inner text without paired tags) for every paired span."""
    spans: list[tuple[str, str]] = []
    for match in SPAN.finditer(text):
        spans.append((match.group(1), PAIRED.sub("", match.group(2))))
        spans.extend(innermost_first(match.group(2)))
    return spans


def project(plain: str, spans: dict[str, str], nesting: dict[str, str]) -> str | None:
    """Wrap each span translation's unique occurrence in ``plain``; None if any is ambiguous."""
    lowered = plain.lower()
    found: dict[str, tuple[int, int]] = {}
    for ident, translation in spans.items():
        needle = translation.strip().rstrip(".。").lower()
        if not needle:
            return None
        starts = [m.start() for m in re.finditer(re.escape(needle), lowered)]
        if len(starts) != 1:
            return None
        found[ident] = (starts[0], starts[0] + len(needle))
    for ident, parent in nesting.items():
        if parent:
            (s, e), (ps, pe) = found[ident], found[parent]
            if not (ps <= s and e <= pe):
                return None
    ranges = sorted(found.values())
    for (_, e1), (s2, _) in zip(ranges, ranges[1:], strict=False):
        if s2 < e1 and not any(
            found[a][0] <= s2 and found[b][1] <= found[a][1]
            for a in found
            for b in found
            if a != b
        ):
            return None
    inserts: list[tuple[int, int, str]] = []
    for ident, (s, e) in found.items():
        inserts.append((s, 1, f"<g{ident}>"))
        inserts.append((e, 0, f"</g{ident}>"))
    out = plain
    for pos, _, tag in sorted(inserts, key=lambda t: (t[0], t[1]), reverse=True):
        out = out[:pos] + tag + out[pos:]
    return out


def parents(text: str) -> dict[str, str]:
    stack: list[str] = []
    result: dict[str, str] = {}
    for match in re.finditer(r"<(/?)g(\d+)>", text):
        if match.group(1):
            stack.pop()
        else:
            result[match.group(2)] = stack[-1] if stack else ""
            stack.append(match.group(2))
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    parser = argparse.ArgumentParser()
    parser.add_argument("--mt-model-dir", default="data/models/alirezamsh--small100-ct2-int8")
    args = parser.parse_args()
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    failed = [r for r in data["rows"] if r["engine"] == "mt" and r["xml_failure"]]
    config = MtEngineConfig(
        model_dir=Path(args.mt_model_dir), model_family="small100", compute_type="int8"
    )
    recovered: list[dict[str, str]] = []
    with Translator(config) as translator:
        for row in failed:
            source, target = (Language(x) for x in row["direction"].split("-"))
            text = row["source"]
            spans = innermost_first(text)
            outputs = translator.translate_texts(
                [PAIRED.sub("", text), *[inner for _, inner in spans]],
                source=source,
                target=target,
            )
            plain, span_out = outputs[0], dict(
                zip([i for i, _ in spans], outputs[1:], strict=True)
            )
            result = project(plain, span_out, parents(text))
            if result is not None:
                recovered.append({"direction": row["direction"], "case": row["case"],
                                  "source": text, "projected": result})
    summary = {"failed": len(failed), "recovered": len(recovered)}
    data["projection"] = {"summary": summary, "recovered": recovered}
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    for item in recovered:
        print(item["direction"], item["case"], "|", item["projected"])


if __name__ == "__main__":
    main()
