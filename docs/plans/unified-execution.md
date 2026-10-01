# Unified implementation execution

Authority: the owner's unified specification and clean-slate authorization supersede conflicting older plans. Existing uncommitted work is preserved. No production deployment or publication is authorized.

## Checklist

- [x] Inspect specification, repository instructions, existing source and dirty tree.
- [x] Install workspace dependencies and start baseline checks.
- [x] Target-only core, common routing policy, bounded retries and native standard fit.
- [x] Verified staged uploads, shared slots/work and private History grants.
- [x] Durable fallback attempts, cancellation and fenced current publication.
- [x] Storage reservations, cleanup, expiry, eviction and recovery.
- [x] Independent API upload/status/cancel/download acceptance.
- [x] Desktop authenticated runtime, process lifecycle and safe fresh exports.
- [x] Desktop shell, installer, offline support and available Explorer acceptance. External visual/signing gates remain below.
- [x] Immediate website batch submission and direct private History downloads.
- [x] Shared visual treatment and browser acceptance.
- [x] Required repository checks, available runtime acceptance and evidence review.

## Consequential decisions

- Retain internal applications' explicit saved/temporary API contracts where the final specification explicitly preserves them. Website cached requests use separate explicit selection and download semantics.
- Existing database queue is the only execution queue. Shared website work extends that queue; private jobs represent waiters. Desktop uses the same queue with fresh temporary processing.
- Signing, real hardware, credentials and clean-machine acceptance will be reported separately from deterministic implementation tests. Missing prerequisites never count as successful acceptance.
- Source detection runs at ingestion and is carried as optional metadata through every inference rung. Unknown/Mixed status is valid API metadata. It does not enter prompt or cache identities.
- The approved GPT-OSS Thinking endpoint reports `gpt-oss-120b` in response metadata. Its configured alias is explicit and fingerprinted. Other unexpected response identities fail instead of being attributed to the requested model.
- A single bounded leading thinking envelope is accepted before the strict structured translation response. It is not published or logged; malformed JSON, count mismatches and trailing content still fail.
- Desktop exported bytes become user-owned. After durable export journaling, app-managed output/report copies are released; terminal automatic jobs release their staged originals. Explicit internal-app temporary retention promises remain intact.
- Windows cleanup rejects junctions/symlinks and checks resolved parent directories before recursive removal of managed work/staging folders.
- A deleted or expired History grant is replaced with a fresh identity after another verified upload. Old History/job URLs stay revoked. Expired private metadata and unowned empty slots are pruned after the configured metadata grace.
- The known-upload admission sweep protects that source/target's current output, so pressure cannot erase the fallback to fund an optional upgrade. Unrelated eligible slots remain subject to ordinary eviction.

## Baseline

Initial dependency synchronization, Ruff formatting/lint, Pyright and all 14 import contracts passed. The initial full pytest run overlapped implementation edits and is not treated as a stable baseline. The original service published preview packages and used owner-specific saved translations, which differed from the approved unified website contract.

The first complete post-implementation Python run passed 433 tests (3 integration tests deselected), in 975.62 seconds. Additional recovery and desktop acceptance tests were added afterward and are tracked in the component evidence. Later final results are recorded below.

Subsequent checks passed: 70 API/shared/storage cases, four optional-upgrade/expiry cases including blob pressure, and 26 desktop asset/lifecycle cases including secure redirects and concurrent submission replay. Full Ruff lint, formatting and Pyright pass at this checkpoint; all 14 import contracts pass. Later full-suite and installed validation results are recorded below.

The final full Python suite passed 478 tests (3 integration tests deselected) in 706.62 seconds. The later desktop recovery/offline-corruption/journal-isolation suite passed 14 tests. Full Pyright is clean. Native installer assembly and local lifecycle checks subsequently completed; these results do not substitute for signed installer acceptance.

Final desktop setup cancellation regressions passed nine cases, and the subsequent full Pyright check reported zero errors. The native activity fixture additionally verifies direct Open file/Show in folder commands, keyboard focus across polling, both themes and narrow layouts. Actual native shell activation translated a Unicode filename, preserved its source and exported successfully; explicit shutdown removed its owned descendants. The final frozen runtime also passed real Davy translation, authenticated-host/origin checks and export replay. Offline local acceptance includes all five formats, all twelve language directions and verified bundled installation/removal with active-model protection. Final matched installers and installed lifecycle evidence are tracked in the desktop record.

With the Python sources settled, the complete repository suite passed **495 tests**, with three external integration cases deselected by the default configuration, in 603.84 seconds. This run includes the final journal, retention, asset and immediate-cancellation regressions. The remaining native folder-selection correction does not change Python code.

Installed acceptance subsequently found that the offline idle guard counted completed, undismissed jobs as active. After reproducing the defect in the native UI and two REST regressions, the guard was corrected to count unfinished work. The final full suite now passes **497 tests**, with three integration cases deselected, in 339.30 seconds. All 14 import contracts, full Pyright, Ruff lint and formatting pass. The rebuilt frozen host completed real translation/export replay and reached offline Ready through the authenticated setup API without dismissing completed activity.

The last installer-lifecycle correction makes repeated setup verify and reuse an activated immutable model rather than fail on its existing directory. Corruption still fails verification without overwriting assets. The final full suite passed **498 tests**, with three integration cases deselected, in **499.60 seconds**. The rebuilt frozen executable also passed real translation/export replay and reached offline Ready against the already-installed model. Native file actions additionally share balanced COM initialization following the Windows shell API contract; final Open file visual verification is blocked by the locked desktop.

## Runtime evidence

- Real Davy matrix: 30/30 successful document translations across all six approved remote rungs and TXT, DOCX, PPTX, XLSX and PDF. Latest measured outputs and per-model timing are in `data/experiments/unified-runtime/20260930T041601Z/evidence.json`. Run with `uv run python scripts/acceptance_unified_runtime.py` using existing approved credentials; the script never prints them.
- Native Office: all 18 corresponding DOCX/PPTX/XLSX outputs opened without repair in Office 16 build 20326. Excel preserved both formula expressions and recalculated expected values 295 and 120. Evidence: `native-office.jsonl` beside that matrix.
- Translation success does not certify perfect layout. Standard fit honestly reported unresolved constraints on DOCX/XLSX fixtures and one Nemotron PPTX. PDF placement validation passed for every model. No renderer was installed or invoked by translation.
- Independent HTTP client: queued cancellation, five cold format submissions, authorized verified downloads and five warm shared-cache hits passed against real loopback service/worker/Davy. Evidence: `data/experiments/unified-api/ba6c31342ed949489b6fafe8d3c3c903`. Cold ready times were 2.4-8.0 seconds; warm times 0.5-1.3 seconds on these fixtures. These are cold/warm observations, not a claimed before/after speedup.
- The final HTTP rerun after ingestion metadata and cleanup changes also passed all ten cold/warm submissions and cancellation: `data/experiments/unified-api/e0cd7728fa914e2d8a2521eefa7de5b4`. Warm job fit diagnostics now agree with the reused report.
- Existing real integration tests were run with the actual Gemma endpoint and installed SMALL-100 model: 2 passed. Missing environment variables in the default integration invocation were supplied from existing local configuration without disclosing values.
- See [core evidence](unified-core-evidence.md), [website evidence](unified-web-evidence.md) and [desktop evidence](unified-desktop-evidence.md) for deterministic cases, browser screenshots, measured contrast and native artifacts. Native desktop builds and available final repository checks passed; signed clean-machine release is not implied by these results.

Both final private unsigned installers built successfully. Online installation and full-offline upgrade returned exit 0; installed artifacts matched payload hashes and all five baseline originals/exports were preserved. The final installed runtime passed real translation, export replay, authenticated-host checks and repeated offline setup returning Ready. Graceful shutdown and the installed path guard passed. Artifact identities and lifecycle evidence are in the desktop report. All six required repository commands passed; the final Python result is 498 passed, three integration cases deselected. Web validation passed 35 unit tests, seven browser E2E tests, lint, typecheck, formatting and build. No artifacts were published.

## External release gates

- Supply an approved publisher certificate and matching publisher identity, then build with release signing enabled and verify the signed shell, runtime, Explorer identity and installers. Exercise the actual modern Windows 11 menu and independently delivered signed credential update. Unsigned COM invocation is local implementation evidence, not proof of trusted registration.
- Supply an isolated clean Windows 11 x64 test machine with supported Vulkan hardware. Verify installation without development tools, direct Davy use on the approved network, full offline installation/inference with the network disabled, upgrade and uninstall, preserving originals and exports. The development host's installed/runtime checks cannot substitute for this environment.
- Unlock the desktop to complete the final native Open file visual check, including Unicode and long paths. Show in folder was verified; successful file-processing/API checks do not prove the external application opened. Windows UI automation stopped on the locked desktop as required by the computer-use skill.
- Approve redistribution of the model, bundled runtime, Microsoft redistributable DLLs and font assets under their recorded licenses before distributing any installer. Private local artifacts have not been published or deployed.
