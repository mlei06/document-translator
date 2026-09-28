# P2-P6 Release Evidence

Evidence for the [P2-P6 delivery handoff](P2-P6-delivery-handoff.md). Every row records the tested commit, the command or test, engine/runtime/application/font versions, the outcome and where artifacts live. Rows are filled only from real runs; an empty outcome means not yet tested. Generated documents and outputs stay under gitignored `data/` and are never committed.

## Progress

Branch: `release/p2-p6` (baseline commit `57a7671`, "Add P2-P6 release plans and design material").

**Current phase and step:** P3.0 - fit measurement/font design (font module drafted in `fit/fonts.py`, not yet committed or wired). P2 is implemented; its closure waits on P3 (fit) because `fit_status=not_run` is a P2-interim value only.

**Done**

- Read all governing documents; inspected existing code (P1 engines/eval implemented; everything else scaffolds).
- Baseline checks on `57a7671`: six root checks pass (87 passed); real LLM and MT integration tests pass.
- P2.0 complete: formatting, PPTX/DOCX writer, XLSX recalculation and detection experiments under `docs/experiments/`; ADR-011 and ADR-009 accepted; Document API in Architecture (`ea17aae`).
- P2 implemented (`6c46841`, `68c67d6`): document API, detection, protection, tags/projection/per-span fallback, targeted OOXML adapters for PPTX/DOCX/XLSX, TXT adapter, local `doctranslator translate` CLI; 165 tests; six checks pass.
- P2 real-engine local acceptance (`scripts/acceptance_local.py`, `data/acceptance/p2/local/summary.json`): all four formats x both engines exit 0, inputs unchanged, only reported out-of-scope parts keep source text; all six Office outputs open natively (Office 16 build 20326, `data/acceptance/p2/local/native.jsonl`). Two MT visual defects found in PowerPoint renders were fixed with regression tests.

**Next**

- P3.0: measurement module (HarfBuzz + fontTools), PPTX/DOCX/XLSX layout descriptions, native comparison against PowerPoint/Word/Excel, ADR-012, then P3 implementation.
- P1.1: MT run translated (`data/eval/runs/20260928T055619Z-mt-...`); COMET scoring and the LLM run are running as a detached process (log `scratchpad/baselines3.log`, see blockers). The first LLM run failed with HTTP 429 while the formatting experiment used the same server.

**Open blockers and environment limits**

| Blocker | Missing item | Rows blocked |
|---------|--------------|--------------|
| CI | Pipelines run only on `main` and pull requests; this branch has not been pushed (the owner asked for no push/PR). | CI evidence for every row and phase closure |
| Second machine | No second internal machine available to this session | R14 |
| Word save/export | Word on this host opens documents but hangs on any save or PDF export (a hidden prompt, likely a policy such as mandatory sensitivity labels; this session has no interactive desktop). PowerPoint and Excel export fine. | DOCX visual renders (native open works and is recorded) |

Notes for a fresh session: background shells die with the session, so long jobs are started with `Start-Process` (detached). `scripts/native_office_check.ps1` needs one Office app at a time; Office automation takes about a minute per application start here.

## Environment

| Item | Version |
|------|---------|
| OS | Windows 11 Pro 10.0.26200 |
| Python / uv | 3.14.7 / 0.12.6 |
| Node / npm | 24.19.0 / 11.17.0 |
| Office | Microsoft Office 16 (Word, Excel, PowerPoint), exact build recorded per native row |
| LLM | Internal OpenAI-compatible server, model `gemma-4-31b-it` |
| MT | SMALL-100, CTranslate2 int8 (`data/models/alirezamsh--small100-ct2-int8`) |

## Backend Release Matrix (R01-R14)

| ID | Tested commit | Command / test | Versions | Outcome | Artifacts |
|----|---------------|----------------|----------|---------|-----------|
| R01 | | | | Not yet tested | |
| R02 | | | | Not yet tested | |
| R03 | | | | Not yet tested | |
| R04 | | | | Not yet tested | |
| R05 | | | | Not yet tested | |
| R06 | | | | Not yet tested | |
| R07 | | | | Not yet tested | |
| R08 | | | | Not yet tested | |
| R09 | | | | Not yet tested | |
| R10 | | | | Not yet tested | |
| R11 | | | | Not yet tested | |
| R12 | | | | Not yet tested | |
| R13 | | | | Not yet tested | |
| R14 | | | | Blocked: no second machine | |

## Browser Acceptance Matrix (W01-W08)

| ID | Tested commit | Command / test | Versions | Outcome | Artifacts |
|----|---------------|----------------|----------|---------|-----------|
| W01 | | | | Not yet tested | |
| W02 | | | | Not yet tested | |
| W03 | | | | Not yet tested | |
| W04 | | | | Not yet tested | |
| W05 | | | | Not yet tested | |
| W06 | | | | Not yet tested | |
| W07 | | | | Not yet tested | |
| W08 | | | | Not yet tested | |

## Checks and CI

| Commit | Six root checks | Frontend checks | CI run |
|--------|-----------------|-----------------|--------|
| `57a7671` | Pass (87 passed, 2 deselected) | n/a | Not run (branch not pushed) |
