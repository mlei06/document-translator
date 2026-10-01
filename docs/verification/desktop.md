# Unified desktop implementation evidence

Status: the baseline runtime/installer has recorded local acceptance below. Later main-window UI and Downloads-export amendments are implemented and tested in source but have not replaced the running installation. Read those dated amendments before applying older installed-package claims. Signed clean-machine release and the remaining native checks are still outstanding.

## Implemented boundaries

- Tauri 2 shell owns one frozen shared Python runtime in a Windows kill-on-close Job Object. Bootstrap bearer is delivered through stdin, readiness validates protocol/API/PID/random loopback port, and every route rejects missing credentials, wrong Host, and browser Origin. Credentials stay in native memory, never WebView JavaScript.
- Stable Windows SID owner and known-folder per-user data root with explicit ACL. Bundled Davy configuration is protected with DPAPI after first use; a shared packaged credential is recoverable by a sufficiently privileged client user. No contrary secrecy claim is made.
- Shared JobService/Worker/EngineCatalog handles automatic policy, admission, progress, cancellation and all five formats. Desktop has no translation implementation or completed-result cache.
- Streaming folder discovery excludes reparse points, deduplicates overlaps, reports unsupported siblings, preserves relative output trees and supports cancellation. Explorer uses compiled IExplorerCommand and per-user structured activation files, not document filenames in shell commands.
- Export uses verified temporary bytes plus atomic no-overwrite publication and numbered collisions. Durable local journal allows crash replay and calls shared release_desktop_result only after publication. Explicit failed export recovery retains the shared result until it is saved.
- One exact HY-MT1.5 Q8 bundle, all twelve language pairs, pinned adapter/runtime/model hashes. Verified HTTPS download with persistent validator-bound partial ranges, full content verification and a real runtime load test before activation. Offline add/remove/repair refreshes idle catalog; active changes are refused. No CPU/Q4 substitution.
- Native settings manage ordered/empty Explorer shortcuts and offline install/cancel/repair/remove. Main window close keeps accepted work running; explicit Quit/shutdown exits boundedly.
- Separate Explorer activity surface tracks files/errors/actual job status and cancellation without opening the main window.

## Completed local checks

- Eight desktop boundary/export/DPAPI/Windows identity tests pass.
- Twelve additional asset regressions pass: interrupted HTTP resume, validator/range changes, oversized or wrong-hash payloads, cancellation, load failure, case-insensitive duplicates and actual Windows junction rejection.
- Four initial lifecycle tests pass: active refresh rejects, idle refresh changes only new work, durable export/replay frees managed originals/output/report while preserving user files, failed/cancelled jobs free reservations and managed originals.
- Shared desktop source CLI host and PyInstaller frozen host both completed real Davy TXT admission/status/export/replay. Anonymous health and unrelated browser origin rejected. These runs used the development host and are not clean-machine installer evidence.
- Managed HY translated TXT/DOCX/PPTX/XLSX/PDF serially under one runtime pin. All sources unchanged. TXT not_applicable, PPTX/PDF fit passed, DOCX/XLSX fit unresolved and reported honestly. Evidence: data/experiments/unified-desktop.
- MSVC 14.44, Windows SDK 10.0.26100, Rust 1.98.1 and NSIS 3.12 installed. Native Explorer DLL compiled successfully. Tauri cargo check, debug and optimized release builds passed. The final shared-COM file-action revision compiled successfully in 4m 24s; formatting passed.
- Main/activity HTML interaction fixtures passed keyboard-focus preservation, light/dark,375px overflow, explicit Retry/Dismiss, queue-full same-ID retry, cancellation and pinned target. Screenshots under apps/web/verification/screenshots/desktop-*. These are frontend bridge fixtures, not native shell screenshots.

## Additional native and offline evidence

- Actual native Tauri main window and separate Explorer activity window inspected through Windows Computer Use. Second-instance structured activation translated a Chinese TXT under a Unicode/space path. Activity showed 1 accepted/1 translated/0 active/0 errors, and the sibling English output contained "Please save the file." The original was unchanged. This is an actual native bridge/runtime result, not an HTML fixture.
- Native --shutdown returned and both owned shell/Python runtime processes exited. No external inference services were stopped.
- Compiled Explorer DLL COM factory/enum/unload smoke passed. Registry-configured Japanese/English/Spanish ordering produced three corresponding commands; empty shortcuts produced zero. Original registry preferences restored after the test.
- Real bundled offline installation verified 1,908,528,288 model bytes and every runtime hash, passed actual runtime load, refused removal while a document pin was held, and removed idle managed model data while preserving the existing source GGUF.
- Actual HY-MT simple TXT translation completed all twelve directed pairs among English/Chinese/Japanese/Spanish. The evidence is under data/experiments/unified-desktop/pairs-*. This verifies operational pair coverage for synthetic sentences, not a full quality benchmark.
- Managed runtime integration passed in 46.72 seconds after requiring logs to prove Vulkan and 33/33 GPU layers. Verbosity 4 is necessary for the pinned runtime to emit the startup evidence. A missing observation fails closed; there is no CPU fallback claim.
- Both final unsigned NSIS installers compiled successfully. Final artifact identities are recorded below. Credential-bearing resources, payload and installer output root have verified current-SID-only ACLs; artifacts are private and unpublished.
- Current focused lifecycle regression coverage includes retained internal promises, corrupt offline model/runtime/revision status, journal expiry preserving user exports, malformed-journal isolation, completed-activity admission and repeated setup. The final full Python suite passed 498 tests; three external integration tests were deselected by its default configuration.

## Artifact provenance and decisions

- Tencent upstream immutable model revision 265b2e615a7dc9b06c435dc878829ad99a512ba2 reports Q8 file SHA256 6789b06d0902f2f5312c0e1703d56ccbddfcfb6c653d22519b7c720f7db9a98e and 1,908,528,288 bytes, matching the existing local asset.
- Source: https://huggingface.co/tencent/HY-MT1.5-1.8B-GGUF/tree/265b2e615a7dc9b06c435dc878829ad99a512ba2 . License: Tencent HY Community License, https://github.com/Tencent-Hunyuan/HY-MT/blob/main/License.txt . Redistribution/legal review remains a release-owner responsibility, not inferred from local inference success.
- Runtime executable SHA256 11b1a4aea38359202647a40bb04a8c2300d856a1d5a4521c7806bd0c39003bde; installer manifest pins each runtime DLL as well. Actual tested GPU Intel Arc integrated Vulkan. Other hardware is unvalidated; startup must prove Vulkan and full GPU offload.
- Private packaging resources and any credential-bearing provisioning file live only below ignored data/desktop-build. No publishing or deployment performed.

## Release checks still pending

- Supply an approved signing certificate and matching publisher identity. Build with `apps/desktop/build-package.ps1 -Release -CertificateThumbprint <thumbprint> -Publisher <identity>`, then verify trusted modern Explorer registration and independently delivered signed credential updates. All current private artifacts report `NotSigned`; trust settings were not weakened.
- Provide an isolated Windows 11 x64 machine with supported Vulkan hardware. Verify setup without development tools, then full offline setup/inference with network disabled, upgrade and uninstall. Developer-host evidence does not substitute for this gate.
- Unlock the desktop to finish native Open file visual acceptance, including Unicode/long-path output. Windows UI automation stopped when the desktop locked. The final source uses normalized shell paths and balanced COM initialization, but a successful API dispatch is not proof of the associated application's visible result.
- Before distribution, confirm the model, runtime, font and Microsoft redistributable licensing decisions. No installer has been published or deployed to another machine.


### Final-build preparation notes

- The optimized release shell's first full build passed in28m54s; final incremental native build includes direct activity export actions. Python frozen host rebuilt from the final source and passed actual Davy smoke, including durable export replay. Frozen module inspection confirms immediate cancellation is not cleared by background setup.
- A concrete NSIS build failure occurred because an in-progress compiler read its script while it was edited. Packaging now copies an immutable setup.nsi snapshot before invoking either installer compiler; no successful full-offline artifact is claimed from that aborted build.
- Explorer uses /MT and dumpbin confirms no MSVCP/VCRUNTIME import dependency. llama-server-impl.dll requires MSVCP140/VCRUNTIME140/VCRUNTIME140_1. Private resource preparation adds the Microsoft redistributable app-local DLLs from installed Visual Studio2022 Build Tools, VC Redist14.44.35112 x64/Microsoft.VC143.CRT, then signs (when material supplied) and hashes them with the rest of the runtime. Redistribution must follow the Microsoft Visual Studio license and redistributable list; the release owner must approve that distribution.
- The private installer output and provisioning file ACLs were inspected and expose only the current Windows user. No credential values were emitted and no artifact has been published.


### Host and final native action regression

The developer host is Windows 11 Pro 10.0.26200 x64, Intel Core Ultra 7 155H, 63.5 GiB physical RAM and integrated Intel Arc Vulkan. Startup evidence showed 33/33 layers offloaded, 1,815.26 MiB Vulkan model buffer, 1,024 MiB KV cache and 48.01 MiB compute buffer (plus host buffers). These measurements do not establish support on untested hardware.

Actual compiled IExplorerCommand::Invoke was exercised with a real Windows shell item for a filename containing ampersand and Chinese characters. It launched the optimized shell through the structured activation file, translated successfully and published the expected sibling English output without changing the source. The compact activity displayed saved status and both direct actions. Clicking Show in folder revealed that explorer.exe command-line parsing opened Documents for the canonical Windows path. The fix uses SHParseDisplayName/SHOpenFolderAndSelectItems with balanced COM initialization/PIDL release and normalizes the path for both native file actions. The corrected Show in folder action subsequently passed its native UI retest and the final shell was repackaged. Open file visual acceptance remains blocked as recorded below.

### Final installed lifecycle follow-up

The corrected native Show in folder action selected the Unicode/ampersand export in the actual Explorer folder during the unlocked native test. The final shell additionally normalizes the file-opening path. Its final Open file visual outcome remains unverified: the desktop locked during follow-up, and Windows UI automation stopped. Resume that visual check on an unlocked desktop; no success is inferred from a successful shell dispatch alone.

Review of Microsoft's [ShellExecuteW requirements](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecutew) identified that file associations may use COM shell extensions. The balanced COM initialization previously used only for folder selection now covers both actions, with STA and disabled legacy OLE1 DDE. This addresses the documented precondition, not a claim that the unobserved file-opening outcome has been proven fixed.

The initial per-user Online install and subsequent full Offline upgrade completed with exit 0. All five recorded test originals/exports kept their hashes. The installed process/path guard returned exit 1 while the installed application ran, then exit 0 after bounded shutdown. Installed HY inference also succeeded with PATH restricted to Windows System32, proving the packaged app-local runtime DLLs do not depend on the developer PATH.

The full upgrade exposed a concrete idle-check bug: completed, undismissed activity was treated as active work, preventing offline capability setup. The native UI reproduced the failure and both succeeded/cancelled REST regressions failed before the fix. Capability admission now asks the shared service for unfinished jobs only. All 22 focused desktop tests pass. The rebuilt frozen runtime completed actual Davy translation, verified unchanged source/export replay, then installed the bundled offline capability through its authenticated API and reached Ready while completed activity remained. Both final installers include this correction. Existing activity is preserved rather than dismissed or deleted to bypass the defect.

Silent uninstall removed the application directory and uninstall registration, preserving all five baseline originals/exports, the installed model, DPAPI configuration and recent metadata. The evidence is `data/desktop-build/uninstall-evidence.json`. A subsequent reinstall exposed repeated offline setup attempting to republish its already-installed immutable revision. The actual frozen-host API run reproduced Needs attention. Setup now revalidates/reuses an activated bundle, while a regression checks that subsequent corruption still fails and leaves the files untouched. All 26 focused desktop tests pass after this correction; both final installers were successfully rebuilt from these sources.

The corrected frozen executable then passed actual Davy translation/export replay and repeated setup against the existing model, returning offline Ready. Packaged-host acceptance additionally translated all five formats with its working directory set to the installed runtime directory, all `DOCTRANSLATOR_*` environment variables removed and PATH restricted to Windows System32. All originals stayed unchanged; outputs passed ZIP/PDF integrity checks. TXT fit was not applicable, DOCX/XLSX unresolved, PPTX adjusted and PDF passed. Evidence: `data/desktop-build/packaged-formats-1790785420685205600/evidence.json`. This verifies packaged runtime behavior without the repository working directory, not an isolated clean-machine or network-disabled claim.

Packaged translation/export replay also passed for a 367-character source path containing Unicode. `scripts/desktop_host_smoke.py <installed-runtime> --long-path` reproduces this check. Original bytes remained unchanged. This tests file processing and publication, not the external application opening that path.

## Final private build artifacts

Both variants contain the same final optimized shell and frozen runtime. These local files deliberately contain the owner-authorized recoverable Davy provisioning credential and remain under the restricted, ignored `data/desktop-build` directory.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `Lenny-Translator-Online-Setup.exe` | 297570134 | `C5F3810C5ADA6658359858B5AA90FF4D1F4638DD74AD7D25F93004E8CDEAE69F` |
| `Lenny-Translator-Offline-Setup.exe` | 2131154827 | `4BA921F2ABD959F1A8482C6F8AFCBAC26139894D5636B64E869C94D013CA411A` |
| `payload/lenny-desktop.exe` | 10995200 | `26D6195755B79410800BB76F2E4A90056694CC2B51531B77F6522DEA051F040C` |
| `payload/lenny-explorer.dll` | 210944 | `31400F01255B4E262D9D00F29E9455D57AE860ED37191C49CD6792855A8E32BD` |
| `payload/runtime/doctranslator-server.exe` | 23492298 | `AD8B76284BA437CB9E439F1E27AA05F14579C0707F236A80BFA2BBD44DEAFF06` |
| `payload/Lenny.Identity.msix` | 11951 | `2A6CEACA920644E449E77C37B342834D4D6C8D01699C8658EE65A7C870A4E7D5` |

The machine-readable manifest is `data/desktop-build/artifact-hashes.json`. All six signatures were checked and report `NotSigned`. The final online installer completed with exit 0, and its installed shell/runtime hashes matched this payload. The final full-offline upgrade also completed with exit 0. Installed shell, Explorer DLL, frozen runtime, identity package and offline model hashes matched the final payload. All five baseline originals/exports remained unchanged. The installed frozen host then passed actual Davy translation, anonymous/origin rejection, unchanged-source verification, durable export replay and repeated offline setup returning Ready. Graceful shutdown left no owned installed processes; the installed path guard passed. Evidence: `data/desktop-build/final-install-evidence.json`.

## Main-window UI refinement, 2026-09-30

Implemented the owner-requested desktop design in `apps/desktop/ui`: visible native drag feedback, named draft rows with Office/PDF/text icons and removal, direct-file validation, resettable output destination, neutral language actions, compact activity, real translation-unit progress and contextual export recovery. The native `inspect_paths` command checks selected-root metadata off the UI thread without folder enumeration. No mascot or website default-language behavior is introduced.

Verification for this change:

- Reproduced missing drag feedback with the browser/native-bridge fixture before implementation.
- `node --test apps/desktop/tests/ui.test.cjs`: 6 passed. Covers drag state, file/folder identification, unsupported input, removal, picker cancellation, destination reset, independent pinned batches, real progress rendering, save retry without resubmission, action-menu focus across changed polling snapshots, 375px dark layout, 200% scaling, clearing an in-flight path check, deduplication, and four selected files with language actions visible at 980 x 720.
- Inspected final `data/desktop-ui-verification/selected.png`, `activity.png` and `narrow-dark.png`. These are rendered desktop assets with simulated native responses, not native application acceptance screenshots.
- `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked -j 2`: 1 passed, including dotted folders, extensionless files and missing paths. Cargo formatting check and the final debug shell build passed.
- Targeted JavaScript lint and Prettier checks passed.
- All six root checks passed: dependency sync, Ruff format, Ruff lint, Pyright (0 errors), import contracts (14 kept), and pytest (498 passed, 3 integration tests deselected).

The existing installed application was inspected through Windows Computer Use and still contained an unsubmitted user selection. It was left running unchanged to preserve that selection. The updated executable is built at `apps/desktop/src-tauri/target/debug/lenny-desktop.exe`; this change has not replaced the installed executable or rebuilt signed installers. Actual Explorer-to-updated-window drag/drop, native picker/export/open checks and installed light/dark/scaling acceptance remain outstanding. Existing backend/installer evidence above is not presented as verification of the updated UI.

## Downloads export amendment, 2026-09-30

The owner replaced source-folder exports with Downloads or a user-chosen output folder. Main-window and Explorer submissions now resolve Windows' Downloads known folder through the native bridge and pin an explicit absolute destination. The UI offers Change folder and Use Downloads. Outputs are placed directly in the chosen folder rather than reproducing source-relative directories. New desktop API submissions without a destination are rejected instead of silently using the original folder. Previously accepted journal records retain their existing destination semantics.

Export no longer takes a source-path argument, and successful publication clears the source path from the export journal. Source paths remain temporary ingestion/failed-job retry metadata. The accepted working copy supports export even if the original is moved or removed. Files already in the chosen destination are no longer incorrectly excluded from discovery.

Verification:

- First reproduced the old Original folders default with a failing browser interaction test.
- Updated UI suite: 7 passed, including a redirected Downloads path, folder-picker cancellation, reset and pinned batch destinations. The submission carries no source-relative output hierarchy.
- Desktop lifecycle suite: 14 passed. The new real API/job/worker/export test uses a fake inference backend and proves that a file already in Downloads is admitted, exports directly to the requested folder after its original is removed, clears the source path, and replays export without producing another copy.
- Native Rust test, debug shell build, Cargo formatting, JavaScript lint and frontend formatting passed.

The installed application remains unchanged. Rollout must rebuild both native shell and Python runtime before replacing the installed package; the existing frozen runtime must not be reused with `-SkipRuntimeBuild` for this change. New installed-app drag/drop/export acceptance is not claimed by the simulated bridge tests.

Final repository checks for the Downloads amendment: `uv sync --all-packages`, Ruff format/check, Pyright (0 errors), import contracts (14 kept), and `uv run pytest` all passed. The full suite completed with 499 passed and 3 integration tests deselected.
