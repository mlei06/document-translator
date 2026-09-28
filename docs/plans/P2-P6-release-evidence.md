# P2-P6 Release Evidence

Evidence for the [P2-P6 delivery handoff](P2-P6-delivery-handoff.md). Every row records the tested commit, the command or test, engine/runtime/application/font versions, the outcome and where artifacts live. Rows are filled only from real runs; an empty outcome means not yet tested. Generated documents and outputs stay under gitignored `data/` and are never committed.

## Progress

Branch: `release/p2-p6` (baseline commit `57a7671`, "Add P2-P6 release plans and design material").

**Current phase and step:** Step 0 - baseline review and P1.1 baseline capture; P2.0 design validation next.

**Done**

- Read AGENTS.md, README, Architecture, Structure, all ADRs, roadmap, handoff and every phase plan; inspected existing code (P1 engines/eval implemented; document, pipeline, formats, fit, render, CLI and server are empty scaffolds).
- Baseline checks on `57a7671`: all six root checks pass (87 passed, 2 integration deselected). Real-backend integration tests pass: LLM (`gemma-4-31b-it` over VPN) and MT (SMALL-100 CT2 int8), 2 passed.
- Environment inventory: Windows 11 Pro 26200, Python 3.14.7, uv 0.12.6, Node 24.19.0, npm 11.17.0, Microsoft Office 16 (Word, Excel, PowerPoint) for native evidence, Edge and Chrome for browser runs, Azure DevOps CLI authenticated.

**Next**

- P1.1 full FLORES+ runs for both engines from an isolated worktree of `57a7671` (running in the background).
- P2.0 design gates: formatting strategy experiment (both engines, 12 directions), OOXML writer evidence, XLSX recalculation in native Excel, detector selection, identity/fingerprint contract.

**Open blockers**

| Blocker | Missing item | Rows blocked |
|---------|--------------|--------------|
| CI | Pipelines run only on `main` and pull requests; this branch has not been pushed (the owner asked for no push/PR). | CI evidence for every row and phase closure |
| Second machine | No second internal machine available to this session | R14 |

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
