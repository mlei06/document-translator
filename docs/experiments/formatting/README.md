# Formatted Translation Experiment

Completed 2026-09-28 for the P2.0 formatting gate. Evidence for [ADR-011](../../decisions/ADR-011-document-translation-contract.md); not production code.

## Question and Method

Can inline formatting spans survive translation by Gemma and SMALL-100 in all 12 directions, and how does that compare with translating each formatted span separately?

```powershell
uv run python docs/experiments/formatting/spike.py          # both engines; needs LLM settings (.env) and the SMALL-100 model
uv run python docs/experiments/formatting/projection.py     # MT projection on the failed cases
```

Twelve synthetic parallel paragraphs per language (emphasis at start, middle and end; two and three spans; nesting; a link span; a URL placeholder; a line break placeholder; moved emphasis; a literal `<`; formatted numbers), each translated into the three other languages: 144 cases per engine. For each case the script records the plain translation (formatting removed), the tagged translation in two markups (`<g1>..</g1>`/`<x1/>` and `[g1]..[/g1]`/`[x1]`), and the per-span translation. A tagged output is valid when it has the same tag inventory, well-formed nesting, the same parent for every tag and no emptied span. Meaning is measured separately as chrF of the tag-stripped output against the same engine's plain translation: a proxy for how much the markup or splitting disturbs the translation, not a quality score against references. Results and every output are in `data/experiments/formatting/results.json`.

Engines: Gemma `gemma-4-31b-it` through the internal server, prompt `llm-translate-v1`, temperature 0; SMALL-100 CTranslate2 int8, beam 4, CPU.

## Results

| Engine | XML valid | chrF vs plain (valid) | Bracket valid | chrF vs plain (bracket valid) | Per-span chrF vs plain |
|--------|-----------|-----------------------|---------------|-------------------------------|------------------------|
| Gemma | 144/144 | 92.5 | 144/144 | 92.8 | 81.2 |
| SMALL-100 | 89/144 | 73.9 | 43/144 | 76.9 | 57.9 |

SMALL-100 XML failures: 42 changed inventory (almost always a lost opening tag), 13 emptied spans. Valid SMALL-100 outputs often put a space after an opening tag (`<g1> sales</g1>`); that is normalized. One valid nested case wrapped the wrong words: validation proves structure, not alignment. Gemma put the emphasis on the right words in every inspected case, including moved emphasis (`我们<g1>昨天</g1>在上海签署了合同。` -> `We signed the contract in Shanghai <g1>yesterday</g1>.`).

Projection for the 55 SMALL-100 failures (translate the paragraph without paired tags and each span separately, then wrap each span translation's unique occurrence): 29 recovered, all with the span on the correct words on inspection. Combined, 118/144 (82%) of SMALL-100 paragraphs keep formatting through tags or projection; the remaining 18% need the per-span fallback.

## Interpretation and Limits

XML-style tags are the markup for both engines; brackets are worse for SMALL-100. The chosen pipeline is tags, then projection, then the per-span fallback with a visible diagnostic (ADR-011). Twelve synthetic paragraphs cannot establish formatting correspondence for arbitrary documents; the document-level release evidence (R02) exercises formatted fixtures through the full pipeline. The meaning proxy compares against each engine's own plain output and says nothing about absolute quality, which the P1.1 baselines measure.
