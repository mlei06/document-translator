# Source-Language Detection Experiment

Completed 2026-09-28 for the P2.0 detection gate. Evidence for [ADR-011](../../decisions/ADR-011-document-translation-contract.md).

## Method

```powershell
uv run docs/experiments/detection/spike.py
```

Needs the FLORES+ devtest files downloaded by the eval app. Compares lingua-language-detector 2.2.0 (restricted to Chinese, English, Japanese and Spanish; offline, models inside the wheel) with a script rule (kana => Japanese, Han => Chinese, Latin => lingua English/Spanish) on four sample kinds: full sentences (1,012 per language), short prefixes (first 3 words for Latin, first 12 characters for CJK), document-sized samples (5 consecutive sentences, 808) and Japanese sentences with all kana removed (1,011, the hard zh/ja case). Output: `data/experiments/detection/results.json`.

## Results

| Sample | lingua | Script rule |
|--------|--------|-------------|
| Sentences (4,048) | 99.95% (1 zh->en, 1 ja->en) | 99.80% (8 zh->en, Chinese sentences dominated by Latin names) |
| Short prefixes (4,048) | 98.47% (50 en/es confusions, 8 ja->zh) | 97.92% |
| Documents (808) | 100% | 100% |
| Japanese without kana (1,011) | 0% (1,010 ja->zh) | 0% (1,003 ja->zh) |

Lingua loaded in 0.01 s and took 0.1-1.7 ms per sample.

## Interpretation

Document-sized samples are reliably detected. Very short samples confuse English and Spanish and occasionally Japanese and Chinese, so the production rule requires a minimum amount of text and a confidence margin, and otherwise asks for an explicit source. Kana-free Japanese cannot be distinguished from Chinese by either method; real Japanese prose contains kana, so the rule is: kana share >= 10% means Japanese, Han without kana means Chinese with an info diagnostic, and very little Han text is ambiguous. An earlier run of this script reported 99.9% on kana-free Japanese; that was a bug (the kana ranges were corrupted by an encoding round-trip, so nothing was stripped) and is superseded by the numbers above.
