# ADR-006: MT Model Selection

> ADR-019 supersedes the single installed/configured MT model restriction. SMALL-100 remains the validated initial local choice; additional model adapters and catalog entries require their own compatibility, quality and distribution evidence.


## Status

Accepted (2026-09-27). Quality sanity check (COMET on the bake-off set) pending; see [Evidence](#evidence).

## Context

MT mode is the local translation mode: it runs on the host without the internal LLM server. Its role is speed and availability; LLM mode covers the highest quality ([README](../../README.md)). The model must:

- cover all 12 directions between Chinese (Simplified), English, Japanese, and Spanish;
- allow commercial use without territorial restrictions;
- run fast enough on the current host, a laptop with an Intel Core Ultra 7 155H (6 performance, 8 efficiency, 2 low-power cores), 64 GB RAM, integrated Intel Arc graphics, and no discrete GPU. A GPU laptop replaces it later.

[ADR-005](ADR-005-translation-quality-evaluation.md) and the P1 plan intended to choose by full benchmark. The owner chose to decide on the evidence below instead and keep the full benchmark for baselines and regressions.

## Options Considered

| Model | Size | License | zh/en/ja/es | Outcome |
|-------|------|---------|-------------|---------|
| **SMALL-100** (`alirezamsh/small100`) | 0.33B | MIT | All | **Chosen** |
| M2M100 418M | 0.42B | MIT | All | Too slow with beam search on CPU |
| M2M100 1.2B | 1.2B | MIT | All | Too slow on CPU |
| MADLAD-400 3B | 3B | Apache 2.0 | All | Far too slow on CPU |
| HY-MT1.5 1.8B (Tencent) | 1.8B | Tencent HY Community License | All | License excludes the EU, UK, and South Korea |
| TranslateGemma 4B (Google) | 4B | Gemma Terms of Use | All | Sanity-check comparison only |
| NLLB-200, SeamlessM4T, North-Small-Translate | various | CC BY-NC | All | Non-commercial license |
| OPUS-MT | per pair | Apache 2.0 / CC BY | 7 of 12 directions | Coverage gaps; the en->ja model is Bible-domain |

## Evidence

Bake-off on 2026-09-27: first 100 sentences of FLORES+ devtest (revision `5fec6c1`), zh->en, on the host above. CTranslate2 4.8.2, int8, 16 intra-op threads, batch 32; llama.cpp b11222 with 4 parallel slots and temperature 0.

| Model | Decoding | Throughput (segments/s) |
|-------|----------|-------------------------|
| SMALL-100 | beam 4 | 2.05 |
| SMALL-100 | greedy | 3.42 |
| M2M100 418M | beam 4 | 0.73 |
| M2M100 418M | greedy | 1.82 |
| M2M100 1.2B | beam 4 | 0.27 |
| MADLAD-400 3B | beam 4 | < 0.03 (stopped after 60 minutes)* |

\* transformers 5.17 warned of an incorrect tokenizer regex when loading MADLAD's tokenizer, so this run may have generated degenerate output up to the length limit. The exclusion holds regardless: at about 7 times M2M100 418M's parameters, MADLAD would run near 0.1 segments/s even when tokenized correctly.

The P1 selection bar was at least 2 segments/s on zh-en (a ~500-segment deck in about 4 minutes). SMALL-100 is the only candidate that meets it with beam search.

Throughput numbers are a lower bound: 16 threads spread one computation across performance and efficiency cores, which may slow it. A run pinned to performance cores is pending and sets the `cpu_threads` default.

**Pending:** COMET and chrF for every bake-off candidate, including HY-MT1.5 and TranslateGemma on CPU and on the Arc GPU (llama.cpp Vulkan). These are recorded here when complete. This decision is revisited only if SMALL-100 is dramatically worse than a candidate that is also fast enough and acceptably licensed.

## Decision

MT mode uses **SMALL-100** (`alirezamsh/small100`), converted to CTranslate2 int8.

- **Tokenizer.** SMALL-100's `sentencepiece.bpe.model` and `vocab.json` are byte-identical to `facebook/m2m100_418M`'s (verified by hash). The engine uses that SentencePiece model directly. The repository's custom `tokenization_small100.py` is not used, and no code shipped with a model is ever executed.
- **Language convention.** SMALL-100 conditions on the target language only: the source tokens are `__<target>__`, then the SentencePiece pieces, then `</s>`; there is no target prefix. `MtEngineConfig.model_family` is `"small100"`.
- **Conversion.** `ct2-transformers-converter` from SMALL-100's weights and config, with M2M100's tokenizer files placed alongside so the conversion never loads the custom tokenizer.
- **Decoding.** Beam 4 by default. Greedy is a configuration change (`beam_size = 1`) worth about 1.7 times the throughput; switch only if the MT baseline shows the quality cost is acceptable.

## Consequences

- MT mode meets the throughput bar on today's CPU-only host, with an MIT license and no territorial restrictions.
- MT mode targets lower-cost local translation, with expected lower quality than LLM mode. Full comparative quality has not yet been established by committed baselines. The owner deferred those runs until before the first prompt/model change; [P1.1](../plans/P1.1-baseline-capture.md) will record SMALL-100's scores across all 12 directions. The throughput evidence above does not substitute for quality scores.
- The MT engine supports one model family. Adding another model later means adding a family, not changing this one.
- On the GPU laptop, larger or LLM-based translation models become practical. Re-run the comparison there before assuming SMALL-100 is still the right tradeoff; HY-MT1.5 additionally needs a legal review of its territorial exclusion first.
- SMALL-100 is a single-author research release, last updated in 2024. Conversion records the Hugging Face revision SHA, and the converted model in the data directory does not depend on the repository staying online.
