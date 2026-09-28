# /// script
# requires-python = ">=3.14"
# dependencies = ["lingua-language-detector==2.2.0"]
# ///
"""Source-language detection experiment for P2.0, not production code.

Run from the repository root (needs the FLORES+ devtest files the eval app downloads):

    uv run docs/experiments/detection/spike.py

Compares two offline strategies restricted to zh/en/ja/es:
- lingua: lingua-language-detector with only those four languages loaded;
- rule: script counting first (kana => ja, Han without kana => zh, Latin => lingua en/es).

Samples: full FLORES+ sentences, short prefixes (first 12 characters for CJK, first 3 words for
Latin), kana-free Japanese (sentences whose kana were removed, the hard zh/ja case), and
document-sized samples (5 concatenated sentences). Writes data/experiments/detection/results.json.
"""

import json
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

from lingua import Language as L
from lingua import LanguageDetectorBuilder

FLORES = Path(
    "data/benchmarks/flores_plus/5fec6c13f9e5a4db2f745d4ec0d7c9721ddc4f06/devtest"
)
FILES = {"zh": "cmn_Hans", "en": "eng_Latn", "ja": "jpn_Jpan", "es": "spa_Latn"}
TO_CODE = {L.CHINESE: "zh", L.ENGLISH: "en", L.JAPANESE: "ja", L.SPANISH: "es"}
OUT = Path("data/experiments/detection")


def load(code: str) -> list[str]:
    rows = (FLORES / f"{FILES[code]}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(r)["text"] for r in rows]


def is_kana(ch: str) -> bool:
    o = ord(ch)
    return 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9D


def is_han(ch: str) -> bool:
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF


def is_latin(ch: str) -> bool:
    return ch.isalpha() and "LATIN" in unicodedata.name(ch, "")


def rule(text: str, detector: object) -> tuple[str | None, float]:
    kana = sum(is_kana(c) for c in text)
    han = sum(is_han(c) for c in text)
    latin = sum(is_latin(c) for c in text)
    if kana + han >= latin and kana + han > 0:
        if kana > 0:
            return "ja", 1.0
        return "zh", 1.0
    if latin == 0:
        return None, 0.0
    values = detector.compute_language_confidence_values(text)  # type: ignore[attr-defined]
    scores = {TO_CODE[v.language]: v.value for v in values}
    en, es = scores.get("en", 0.0), scores.get("es", 0.0)
    best = "en" if en >= es else "es"
    return best, abs(en - es)


def lingua_only(text: str, detector: object) -> tuple[str | None, float]:
    values = detector.compute_language_confidence_values(text)  # type: ignore[attr-defined]
    ordered = sorted(values, key=lambda v: -v.value)
    if not ordered:
        return None, 0.0
    margin = ordered[0].value - (ordered[1].value if len(ordered) > 1 else 0.0)
    return TO_CODE[ordered[0].language], margin


def samples() -> dict[str, list[tuple[str, str]]]:
    data = {code: load(code) for code in FILES}
    result: dict[str, list[tuple[str, str]]] = {"sentence": [], "short": [], "document": []}
    for code, sents in data.items():
        for s in sents:
            result["sentence"].append((code, s))
            short = s[:12] if code in ("zh", "ja") else " ".join(s.split()[:3])
            result["short"].append((code, short))
        for i in range(0, len(sents) - 5, 5):
            result["document"].append((code, " ".join(sents[i : i + 5])))
    result["ja_without_kana"] = [
        ("ja", stripped)
        for s in data["ja"]
        if len(stripped := "".join(c for c in s if not is_kana(c)).strip()) >= 4
    ]
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    started = time.perf_counter()
    detector = LanguageDetectorBuilder.from_languages(*TO_CODE).with_preloaded_language_models().build()
    load_s = time.perf_counter() - started
    summary: dict[str, object] = {"load_s": round(load_s, 2)}
    errors: list[dict[str, str]] = []
    for kind, items in samples().items():
        for name, method in (("lingua", lingua_only), ("rule", rule)):
            t0 = time.perf_counter()
            wrong: Counter[str] = Counter()
            for expected, text in items:
                got, _ = method(text, detector)
                if got != expected:
                    wrong[f"{expected}->{got}"] += 1
                    if len(errors) < 200:
                        errors.append({"kind": kind, "method": name, "expected": expected,
                                       "got": str(got), "text": text[:80]})
            summary[f"{kind}/{name}"] = {
                "n": len(items),
                "accuracy": round(1 - sum(wrong.values()) / len(items), 4),
                "errors": dict(wrong),
                "ms_per_item": round((time.perf_counter() - t0) * 1000 / len(items), 3),
            }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(
        json.dumps({"summary": summary, "errors": errors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
