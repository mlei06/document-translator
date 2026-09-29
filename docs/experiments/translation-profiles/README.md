# Local TranslateGemma and HY-MT2

Optional profiles added at the owner's request on 2026-09-28. These use the
existing `llm` mode with a self-hosted endpoint. They do not change the default
SMALL-100 or generic internal-LLM behavior. See [P1.2](../../plans/P1.2-specialized-translation-models.md).

## Prepared host and artifacts

Test host: Windows, NVIDIA RTX 5090, 32607 MiB VRAM, driver 616.92.
HY-MT2 Q4/Q8 use llama.cpp `b11146` (`7fe450e19`), defaulting to its CPU backend. GPU runs below are historical experiments, not a stability endorsement.
TranslateGemma uses build `b11236` with GPU offload disabled on this host.

| Local name | Artifact | Publisher revision |
|---|---|---|
| `hy-mt2-q4` | Official `tencent/Hy-MT2-1.8B-GGUF`, `Hy-MT2-1.8B-Q4_K_M.gguf` | `a0c709d9fac510f2c807aa3af52872340dc37a4a` |
| `hy-mt2-q8` | Official `tencent/Hy-MT2-1.8B-GGUF`, `Hy-MT2-1.8B-Q8_0.gguf` | same |
| `translategemma-q4` | Community `mradermacher/translategemma-4b-it-GGUF`, `translategemma-4b-it.Q4_K_M.gguf` | `35a7486e128b19642cdc72d7b91b21ba388aaf42` |

Every download was SHA-256 checked against the publisher's artifact metadata.
The launcher contains and rechecks the exact model hashes. TranslateGemma's
quantization is a community conversion, not an independently rebuilt or
Google-published GGUF. Its translation prompt matches the official Google template
at `10042cb0e6e7fdce748996a71dc3dc432a4e0c89`. Text-only inference needs no
vision projector. The tested model sizes are 1.8B and 4B; larger family members
have not been validated here.

Artifacts are local, ignored files under `data/models/hy-mt2/`,
`data/models/translategemma/`, and `data/runtime/llama-b11146/` (HY-MT2) or
`data/runtime/llama-b11236-cuda/` (TranslateGemma). Provenance is saved
beside the models. A fresh clone does not contain them. Obtain the exact files
above using Hugging Face's downloader with the pinned revision and place them in
these directories. Extract the following two official release archives into the
runtime directory:

- [llama CUDA binary](https://github.com/ggml-org/llama.cpp/releases/download/b11146/llama-b11146-bin-win-cuda-13.4-x64.zip), SHA-256 `b1866c0ce76bc7bfb0c24b33e9a37e9669f1be18539b12c74ce361f81c41f047`
- [CUDA runtime libraries](https://github.com/ggml-org/llama.cpp/releases/download/b11146/cudart-llama-bin-win-cuda-13.4-x64.zip), SHA-256 `738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668`

## Start, translate, stop

From the repository root in PowerShell, with `uv` available:

```powershell
.\scripts\local_translation_model.ps1 -Model hy-mt2-q8
uv run doctranslator translate INPUT.docx --from zh --to en --config data/local-models/hy-mt2-q8.env
.\scripts\local_translation_model.ps1 -Model hy-mt2-q8 -Stop
```

Substitute `translategemma-q4` or `hy-mt2-q4` to test another variant. The fixed
loopback ports are 8093, 8091 and 8092 respectively. Only one active server is
needed for translation; stop unused servers to release VRAM. The launcher refuses
occupied ports and never kills an unrelated process. It generates a local API key,
keeps configuration under ignored `data/local-models/`, and disables the web UI.
The key in these local configs is **not** a Hugging Face token.

The launcher defaults to CPU, one request slot, 8192 context tokens and disabled
context shifting. HY-MT2 defaults to Tencent's 1.8B recipe: temperature 0.7,
top-p 0.6, top-k 20, repetition penalty 1.05 and max output 4096 tokens.
It uses full target language names, a user-only prompt, and the model's Jinja
chat template. Min-p is disabled to avoid an additional sampling filter.
Use `-Preset greedy` for the earlier deterministic decoding experiment.
Q4/Q8 alone support experimental `-Device gpu` (eight slots); wider GPU testing
crashed on this host, so this is not a recommended deployment path.
TranslateGemma remains greedy on CPU, with full sliding-window cache and prompt
caching disabled. An overlong input fails instead of silently dropping text;
length-limited responses are rejected. Formatting uses the existing document
pipeline's tag validation and fallback, not guessed structured-prompt routing.

TranslateGemma is sent as a raw completion with its official rendered text
template. The llama.cpp chat parser cannot infer this structured template, so the
launcher uses `--no-jinja --chat-template gemma` only to initialize the otherwise
unused chat interface. Translation itself still uses the pinned official prompt,
not a generic Gemma chat prompt.

## Tuning and measurement

Both apps expose profile, backend, deployment revision, concurrency, output limit,
temperature, top-p, top-k, repetition penalty and seed through
`DOCTRANSLATOR_LLM_*` settings; see `.env.example`. The local configs select
`SERVER_BACKEND=llamacpp`. HY-MT2's vendor sampling recipe
is now the launcher default; the historical GPU timings below used greedy generation.

Download the project's pinned FLORES files with the existing evaluation app:

```powershell
uv run doctranslator-eval download-flores
uv run python docs/experiments/translation-profiles/benchmark.py --config data/local-models/hy-mt2-q8.env --output data/experiments/translation-profiles/new-run.json --limit 100 --repeats 2 --concurrency 1,4,8
```

The experiment records every hypothesis, dataset revision, model identity,
concurrency, wall-clock throughput, and chrF. Warm-up is outside the measured
prefix. It refuses to overwrite an existing result. `--directions all` checks all
12 directions. The output is a separate experiment file, never an accepted
baseline. Server startup is excluded. Warm prompt caching, GPU batching and other
machine activity can affect timing and even greedy outputs; inspect repeated
measurements rather than treating a single run as a guarantee.

For full COMET/FLORES evaluation, supply the same profile settings to
`doctranslator-eval run --mode llm --directions all`. The eval app reads environment
variables and the root `.env`, while the document CLI additionally supports
`--config`. Do not copy the local API key into benchmark reports. The current-model
baselines in P1.1 and full quality comparisons remain required before changing
production defaults. Subset chrF does not establish semantic quality superiority.

## Sources

- [HY-MT2 model card and language coverage](https://huggingface.co/tencent/Hy-MT2-1.8B)
- [Official HY-MT2 GGUFs](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF)
- [TranslateGemma model card and template contract](https://huggingface.co/google/translategemma-4b-it)
- [Community TranslateGemma GGUF](https://huggingface.co/mradermacher/translategemma-4b-it-GGUF)

HY-MT2's current card lists Apache 2.0; the older HY-MT1.5 restrictions in ADR-006
do not describe this new release. TranslateGemma remains under the Gemma terms.

## Initial host results (2026-09-28)

HY-MT2: first 100 Chinese-to-English FLORES+ devtest segments, two warm timing
passes per concurrency level, temperature 0. Values below are medians of two
passes, not confidence intervals. For CPU operation, the 1.8B Q8 variant remains the conservative
starting point; a small chrF difference is not evidence that Q4 is generally better.

| Variant | Concurrent requests | Segments/s | chrF |
|---|---:|---:|---:|
| HY-MT2 1.8B Q4 | 1 | 7.46 | 58.82 |
| HY-MT2 1.8B Q4 | 4 | 9.00 | 59.00 |
| HY-MT2 1.8B Q4 | 8 | 11.35 | 59.06 |
| HY-MT2 1.8B Q8 | 1 | 6.12 | 57.95 |
| HY-MT2 1.8B Q8 | 4 | 8.15 | 57.97 |
| HY-MT2 1.8B Q8 | 8 | 10.74 | 58.06 |

Eight concurrent requests improved median Q8 throughput about 1.75x on this
workload. Run-to-run variation was material: Q8 concurrency 8 ranged 9.94–11.54
segments/s; Q4 concurrency 8 ranged 10.72–11.97. Repeat on representative documents
before capacity planning. No COMET, significance test, full baseline or default
model replacement is claimed. Raw runs are `data/experiments/translation-profiles/hy-q4.json`
and `hy-q8.json`.

TranslateGemma GPU compatibility remains unresolved on this driver/runtime/model
combination. CUDA b11146 and b11236 failed with illegal-instruction/runtime errors;
Flash Attention off and CUDA-graph disabling did not resolve it. A b11236 Vulkan
attempt stalled. Do not interpret these failures as model-quality results. The
launcher uses a CPU fallback so the integration can be tested without claiming
GPU stability. A future investigation should separate runtime/driver kernels from
the community quantization using the official full-precision weights.

For the CPU fallback, additionally extract
[CUDA build b11236](https://github.com/ggml-org/llama.cpp/releases/download/b11236/llama-b11236-bin-win-cuda-13.4-x64.zip)
into `data/runtime/llama-b11236-cuda/` and add the same CUDA runtime archive above.
SHA-256: `472e5fe0317bc61743f160992aa9a38b57cf52a318b3c30b7872f586fa5cd1f1`.
It is the executable's CPU backend that runs; `--device none --no-kv-offload -ngl 0`
prevents model inference on the GPU.

## GPU stability and CPU document smoke

A subsequent Q8 GPU test across language directions crashed with CUDA illegal
memory access after Chinese-to-English completed. Therefore the earlier 100-row
GPU throughput runs do **not** establish stability across all 12 directions.
The interrupted `hy-q8-all-directions.json` is incomplete, not a passing run.

Q8 CPU/vendor settings completed the first 10 Chinese-to-English FLORES+ rows
in two passes: median 0.43 segments/s and chrF 58.13. Compilation activity may
have affected timing. The corpus is too small for model selection or speed claims.
The Word fixture translated 14 unique inputs with zero formatting fallbacks;
its text-box fit remained unresolved (`font_manifest_missing`). Comments,
deletions and field results stay unchanged according to the existing pipeline.
TranslateGemma CPU earlier completed 10 FLORES rows at 0.35 segments/s, chrF52.53,
with a 384-token cap. Its settings differ, so this is only a smoke test.

## AngelSlim verification

Both official low-bit files were downloaded, hash-verified and tested without
editing their GGUF headers. These are experimental native formats; installing
AngelSlim's Python package or stock llama.cpp alone does not supply the kernels.

| Local name | HF revision | SHA-256 | File bytes |
|---|---|---|---:|
| `hy-mt2-1.25bit` | `9df5c824a00a744fb0512a29c640466f4d97dfb0` | `cc497fe8f033b52b3b8b00a7669e9661435432f9d4cd43f7ed24400c01507a93` | 461860800 |
| `hy-mt2-2bit` | `b630487d19ab7f336664a15b07c638d0d1071471` | `dcc33bbae9b28d923c8c76a64f6157840841d26f8774f3dfd770d5fabeeb1cd7` | 600534880 |

The 2-bit runtime is `chaxu01/llama.cpp@2af64dd00a6689a7bfaf69b4768a944d0ec6bade`,
CPU-only Windows x64, KleidiAI disabled (ARM-specific). The model's Q2_0C=40
tensors match this source. It requires `--jinja`: a legacy chat-template attempt
was incoherent; the native template correctly translated the full-sentence smoke.
Runtime binaries, build configuration, hashes and provenance are under
`data/runtime/llama-int2-2af64dd/`.

The current STQ branch `1e411d8` cannot load the published 1.25-bit file: runtime
format identifier42 now means Q2_0, whereas the model uses it for STQ1_0. This
causes a tensor-offset mismatch. The model is intact; do not rewrite its header.
Historical `sjl623/llama.cpp@7ef6976b218cfce6158165f4c63a094acb70e707` retains the
matching STQ format. Runtime build/inference validation is recorded below.

Sources: [1.25-bit card](https://huggingface.co/tencent/Hy-MT2-1.8B-1.25Bit-GGUF),
[2-bit card](https://huggingface.co/tencent/Hy-MT2-1.8B-2Bit-GGUF),
[STQ PR](https://github.com/ggml-org/llama.cpp/pull/22836),
[INT2 PR](https://github.com/ggml-org/llama.cpp/pull/19357).
Tencent's 1.5x on-device speed claim is not assumed to apply to this Windows CPU.

### AngelSlim test results

The historical STQ runtime compiled for this Windows x64 CPU and loaded the
original 1.25-bit file. One portability-only source fix added `<algorithm>` to
`common/ngram-mod.cpp`; the diff and build provenance are saved with the runtime.
No model bytes or inference kernels were modified.

It failed inference: the vendor-settings one-sentence request generated 2087
tokens before being stopped. A second diagnostic with only the output cap reduced
to128 returned HTTP500 and multilingual gibberish. Thus the 1.25-bit option is
explicitly experimental and not recommended. Evidence:
`data/experiments/angelslim-stq-smoke-7ef6976-capped128/` and the sibling full-cap run.
The launcher uses `data/runtime/llama-stq-7ef6976/`; it was tested for startup/stop.

The 2-bit model completed two10-row Chinese-to-English FLORES+ passes with vendor
settings: median chrF57.29, measured0.47segments/s. Q8CPU on the same prefix had
chrF58.13 and0.43segments/s. Compilation activity overlapped some measurements;
these are execution/quality smoke results, not a controlled speed comparison.
No statistical or quality superiority follows from these tiny samples.

Both2-bit and Q8CPU translated14unique inputs in the Word fixture with zero
formatting fallbacks. All package entries and XML remained valid, only the expected
body/header/footer/footnote XML changed, and other package parts were byte-identical.
The text-box fit warning remains unresolved because the font manifest was absent.

TranslateGemma CPU also completed the Word fixture (14 unique inputs); four
paragraphs required the existing per-span formatting fallback, which may reduce
fluency. Its package/XML validation passed with only body/header/footer/footnote
XML changed. Text-box fit remained unresolved for the same missing font manifest.
All local test servers were stopped after verification.

Validation: dependency sync, formatter, linter, type checker and all13 import
contracts passed; pytest242passed with2external integration tests deselected.

A same-host SMALL-100 comparison is documented in
[SMALL100-COMPARISON.md](SMALL100-COMPARISON.md). Its100-row CPU results supersede
cross-machine speed comparisons with the historical laptop bake-off and the
10-row initial smoke measurements. All existing raw results are retained.
