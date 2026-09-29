# D0 Python runtime packaging experiment

This is a bounded packaging probe on Windows x64, based on commit `0d6efed`. It freezes the existing CLI and its core/native dependencies into a directory that can later be installed beside a desktop shell. It does not implement the desktop service, installer, persistent jobs, model downloader or UI.

The language boundary remains a native desktop shell, a shared Python backend, and independently replaceable inference. See the [D0 integration contract](../../plans/D0-desktop-runtime-contract.md) for proposed interfaces and the [desktop delivery plan](../../plans/Desktop-and-internal-app-delivery.md) for full acceptance.

## Reproduce the build

Run in a disposable Windows x64 checkout with Python 3.14 available to uv:

```powershell
uv sync --all-packages
uv pip install --python .venv/Scripts/python.exe pyinstaller==6.22.0
./docs/experiments/desktop-packaging/build.ps1
```

The build tool is an experiment dependency, not a production application dependency. The generated executable is `data/experiments/desktop-packaging/dist/doctranslator-runtime/doctranslator-runtime.exe`. Preserve its entire containing directory, including `_internal`. Model files are not embedded. Build output, logs, measurements and translated samples belong under ignored `data/`, never in Git.

Use `--packaging-probe` for packaged Python/distribution metadata and `--help` for the real CLI. For translation, set `DOCTRANSLATOR_MT_MODEL_DIR` to an already converted, validated SMALL-100 directory; use CPU/int8 settings and an explicit source/target language. Example, from a temporary directory outside the checkout:

```powershell
$env:DOCTRANSLATOR_MT_MODEL_DIR = 'C:/Models/alirezamsh--small100-ct2-int8'
$env:DOCTRANSLATOR_MT_DEVICE = 'cpu'
$env:DOCTRANSLATOR_MT_COMPUTE_TYPE = 'int8'
$env:DOCTRANSLATOR_MT_CPU_THREADS = '2'
& $runtimeExe translate ./source.txt --from zh --to en --mode mt -o ./translated.txt --json
```

Here `$runtimeExe` is the absolute path to the generated executable. Use new output names because the CLI intentionally refuses to overwrite files. Keep source hashes, output files and JSON fit reports when recording an acceptance run.

To repeat the isolated-environment probe, help, TXT translation and PPTX translation in fresh child processes:

```powershell
.venv/Scripts/python.exe -X utf8 docs/experiments/desktop-packaging/smoke.py `
  data/experiments/desktop-packaging/dist/doctranslator-runtime `
  C:/Models/alirezamsh--small100-ct2-int8 tests/fixtures/pptx/deck.pptx
```

The script prints its temporary working directory, which includes spaces and non-ASCII characters. It removes Python and application configuration variables from the child environment, supplies only the selected local model settings and a system-only PATH, records exit codes/timings, verifies unchanged input hashes and checks output/report existence and PPTX ZIP integrity. Inspect translated wording and report diagnostics separately; these mechanical checks do not establish translation quality or rendered fit. Its Python parent is only the test driver, not a prerequisite of the frozen child.

## Evidence and limits

**2026-09-28 result:** the one-directory executable starts and performs real local SMALL-100 translation outside the checkout with a system-only PATH and no Python environment variables. No production files were changed. This establishes Python packaging feasibility, not completed D0 or a shippable installer.

Environment: Windows 11 x64, build 26200; Python 3.14.7; PyInstaller 6.22.0 with hooks 2026.7; locked CTranslate2 4.8.2 and SentencePiece 0.2.2. Model: existing `alirezamsh--small100-ct2-int8`, CPU/int8, two inference threads. `model.bin` SHA-256: `8c849117d6331c07d1c6b601fc7436113c4ed1c75d79cff49aabfa31ab32e8c3`.

| Check | Observed result |
|---|---|
| Frozen metadata | `frozen: true`, Python 3.14.7, core/CLI 0.1.0; executable path is the bundle |
| CLI help | Exit 0 |
| TXT Chinese -> English | One translated input; output `This is a test. Please save the file.`; fit `not_applicable` |
| PPTX Chinese -> English | 16 translated inputs; one formatting fallback; ZIP integrity passed; source hash unchanged |
| PPTX fit | 14 inspected, one unchanged, 13 unresolved with `font_manifest_missing`; see baseline defect below |
| Uncompressed runtime | 464,700,415 bytes, excluding model and desktop shell |
| Separate model directory | 347,934,466 bytes |
| Largest runtime component | Lingua language detector: 304,664,064 bytes; CTranslate2 DLL: 59,296,256 bytes |

Final successful smoke execution is retained locally under `data/experiments/desktop-packaging/evidence-translation-2026-09-28/`, including inputs, outputs, reports, stdout/stderr and `evidence.json`. Build log: `data/experiments/desktop-packaging-build.log`. Final elapsed times were 38.472 s for metadata startup, 12.643 s for help, 19.875 s for TXT and 22.493 s for PPTX, each in a fresh process. Other probes varied substantially, with startup as low as 10.955 s. These are observations on a busy development laptop, not cold-cache benchmarks or acceptable desktop latency targets. Profile the persistent host on an idle target laptop before setting a startup budget. The app should keep the host/model ready across a batch rather than launch a CLI process for every file.

**Baseline fit defect:** in `0d6efed`, `Translator.translate_document()` includes the font manifest in output identity but omits `fonts=self._fonts` when calling the pipeline. The normal per-user CLI font cache contained 392 font faces after the run, yet the pipeline received no manifest. This probe reused that cache; it does not establish clean-machine font discovery. The resulting unresolved report is honest, but this run does not validate actual fit measurement. Inspection of the other agent's uncommitted main checkout on 2026-09-28 showed that it already forwards fonts and a reusable font library. Do not copy or overwrite that work. Once committed, update the packaging branch and repeat the Office run, requiring a non-null report font-manifest digest and investigating any remaining unresolved reasons. Do not treat the current baseline defect as a packaging or font-availability failure.

**Translation quality is not accepted by this probe.** Inspecting the actual PPTX text exposed SMALL-100 errors, including `华东` becoming `Watson` and `1,250 万元` becoming `1,250 million`. Give these cases to the model owner as terminology/quantity-unit evaluation inputs. Chart/SmartArt exclusions and the inline-formatting fallback are explicitly reported. No visual/native PowerPoint acceptance, DOCX/XLSX/PDF packaging acceptance, protected-term guarantee or model-quality threshold was established here.

All six required repository checks passed: workspace sync, formatting, lint, Pyright, import contracts and 178 tests (two integration tests deselected by the default command). The experiment Python files also passed explicit Ruff checks. Real MT evidence above came from the packaged executable, separately from the default test suite.

A developer-laptop run does not prove a clean-machine install or air-gap operation. The network was not disabled. The test selected the local MT engine without configuring a remote inference endpoint. Before release, also build from a production-dependency environment and review unnecessary bundled conversion/test dependencies; reduce measured footprint before considering a language rewrite. The detector data is the largest observed size contributor.

The current laptop has no detected Rust/MSVC build tools or .NET SDK. Tauri 2 remains the proposed shell, pending compilation and lifecycle/installer testing on a configured Windows build machine. The P5 server in this checkout is still scaffold, so durable local history and authenticated host startup cannot be proved by freezing this CLI. Full D0 also requires a clean supported Windows VM, signed installer/update artifacts, selected-model installation and real offline translation followed by restart with intact history.
