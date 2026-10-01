# D0 - Desktop Runtime and Packaging Contract

> Current authority: [Unified translator design](unified-translator-design.md) incorporates the surviving desktop runtime/installer requirements and supersedes all conflicting text below, including mode/model selectors, individual credential provisioning, old model order and deferred Explorer delivery. Desktop automatically uses the installer-provisioned shared Davy key and then installed HY-MT. Historical packaging evidence and separate I1 integration scope remain valid.

> Desktop amendment: [ADR-030](../decisions/ADR-030-desktop-online-offline-delivery.md) and [delivery contract](desktop-online-offline-delivery.md) supersede conflicting model-picker, local-first/no-fallback and deferred Explorer requirements below. Retain the packaged Python/process/loopback security contract. Add signed modern Explorer identity, direct Davy authentication independent of the website service and managed HY-MT offline runtime proof; the CLI probe does not complete D0.

> Translator configuration is governed by accepted [ADR-019](../decisions/ADR-019-configured-translators.md): selectable configured translator IDs, one default, explicit local/remote location and no automatic fallback. Desktop setup selects supported model downloads; hosted users select admin-enabled translators. Installer delivery remains D0/D1 work.


> Storage/identity revision, 2026-09-29: follow accepted [ADR-014](../decisions/ADR-014-storage-ownership-and-retranslation.md) and [the storage transition plan](P5-D2-storage-and-ownership.md). These supersede earlier global-cache, version-0, desktop-library and conflicting retention requirements in this plan. Human/service ownership, local fresh exports, hosted current results and immutable job downloads are the target; implementation is pending.


Status: Python packaging and real local translation demonstrated on branch `desktop/packaging`; full D0 remains open. The [experiment report](../experiments/desktop-packaging/README.md) records results, the baseline fit-wiring defect already being fixed in the other agent's working copy, and remaining acceptance. Production desktop work remains gated by the evidence below. Parent: [desktop delivery plan](Desktop-and-internal-app-delivery.md).

## Scope and ownership

Keep the translation core and hosted service in Python. A native desktop shell owns windows, file selection, installer/model setup and child-process lifecycle. Model inference remains replaceable independently. The desktop agent owns this boundary; model adapters belong to the model agent and document/service behavior to P2-P6. Do not modify those agents' production files in this experiment.

Tauri 2 with React/TypeScript is the proposed shell because it can reuse the web UI and use the platform WebView. It is not accepted as a tested installer until its Rust/MSVC build and Windows acceptance pass. The current laptop lacks both Rust/MSVC and a .NET SDK. Do not replace the core or select a different toolkit solely to bypass this build-machine limitation.

## Runtime artifact

- Build on Windows x64 for the initial Windows x64 target. ARM64 and other OS targets require their own native dependency and installer tests.
- Use a PyInstaller one-directory bundle for the Python executable and native/data dependencies. The shell installer must preserve that directory tree; copying the executable alone is invalid. Avoid one-file extraction on each startup.
- D0 freezes the existing CLI as a dependency/translation probe. It is explicitly not the future persistent local server. No fake queue/history implementation may be introduced to make D0 appear complete.
- The production installer carries a matched shell/runtime version; workers use the same packaged runtime. Models stay outside application binaries and are independently versioned. Python, uv, Node and build tools are not end-user prerequisites.
- Shipping artifacts must be signed; an unsigned development bundle is evidence only for local execution, not SmartScreen or managed-device deployment acceptance.

## Local host contract to implement with the P5 owner

The following is the proposed wire/bootstrap contract, not a currently available CLI/API:

1. Native shell enforces one instance per Windows user and starts its bundled server executable with a desktop profile and an OS-assigned loopback port. It never constructs a shell command from filenames.
2. Shell generates a fresh 256-bit session credential and sends it over the child's inherited stdin pipe. Never put it in arguments, URLs, logs or a persistent plaintext settings file. A bootstrap protocol version accompanies it.
3. Child derives the current Windows SID itself and maps it to a stable local owner. The caller cannot name an arbitrary owner. The profile refuses non-loopback binds and requires the credential for every API request.
4. On readiness the child emits one bounded JSON line on stdout: event, protocol version, API version, PID and loopback base URL. Logs go to stderr; readiness does not contain secrets or imply that a model is loaded. The shell confirms readiness with an authenticated health call and fails visibly on version mismatch/start timeout.
5. The desktop API client uses the existing versioned REST job endpoints. Keep the session token only in memory in the trusted app context. Restrict WebView navigation and CSP to packaged assets and the selected API; local server validates Host and configured Origin, with no wildcard CORS. Unrelated browser origins and other OS users must fail acceptance tests.
6. The shell manages its children in a Windows Job Object so abrupt shell termination cannot leave orphan local servers/workers. Graceful quit requests shutdown and observes a bounded deadline before terminating only its own job object. Durable job recovery remains P5's lease/retry behavior.
7. Window close with active work offers clearly explained background/tray behavior; explicit quit explains interruption. Reopening reconnects to the same running app. After a full restart the token/port rotate but owner and active recovery state remain stable; exported files remain in the chosen folder. There is no permanent local document library.

The desktop profile is file in, file out: it sets `DOCTRANSLATOR_PAGE_PREVIEWS=off` ([ADR-023](../decisions/ADR-023-page-rendering-for-previews.md)), so workers never render page previews or run a renderer thread, and LibreOffice is not part of the desktop runtime.

The service owner must implement and test this profile in the existing server executable. Desktop must not import server modules, maintain a second database queue, or fabricate completed jobs while that profile is unavailable.

Use a per-user application-data root resolved by the runtime through Windows known-folder APIs. Keep bounded job metadata, temporary working inputs/results, logs and installed model versions in distinct subdirectories with current-user access controls. Clean working copies after confirmed export; never delete user-exported files during cleanup. Exported results live in the user's chosen output folder. Upgrades preserve both sets of data; uninstall preserves user data unless the user explicitly selects removal. Never store documents beside installed executables. Load models on demand; unload only when no job uses them. The initial desktop idle-unload default is five minutes, configurable independently of durable job state and subject to the laptop acceptance measurements.

## Model installation boundary

The model agent supplies a reviewed catalog entry for each supported artifact. Required fields: stable model ID, immutable revision, backend ID, prompt/tokenizer adapter version, supported language pairs, compatible runtime version, license/provenance, per-file relative path/HTTPS URL/byte size/SHA-256, and measured resource guidance (or an explicit unknown). No arbitrary repository code is executable content in a model bundle.

The installer launches the same first-run setup used by in-app model settings. It displays choices and sizes, then downloads only the selected model into a per-user staging directory. Prefer plain per-file downloads to archive extraction. Reject absolute/traversing paths and executable payloads. Resume only with a matching remote object validator; otherwise restart that file. Verify every file, ask the runtime to load/validate the staged bundle, then atomically activate its immutable version. Never mark a partial download ready.

The backend resolves a selected installed model ID to validated immutable files and pins that identity on the job. Public remote API clients cannot provide arbitrary server file paths. Removing an active model waits for/rejects against active jobs. Model setup must not transfer document text to the asset host. Catalog hosting, signing keys and redistributable model URLs remain release inputs from the model/distribution owners, not invented values.

## Folder and output contract

Native file/folder selection produces a bounded stream of inputs for the existing per-file batch API. Do not follow reparse points by default. Exclude generated output roots and deduplicate repeated selected source paths. Preserve relative paths under distinct input roots. Every explicit run translates fresh. A destination collision receives an atomically reserved numbered name; never overwrite a source/result. Unreadable and unsupported files are counted individually and do not stop valid siblings. The UI shows enumerating, accepted, running and complete counts without inventing a percentage before enumeration finishes.

## Validation sequence and stopping rule

1. Build the Python bundle and run its metadata/help probe outside the repository with developer Python variables removed and a system-only PATH.
2. Run a real local SMALL-100 TXT translation, inspect target text/report and verify the input hash. Check a supported Office file separately for native-dependency coverage. Run a second fresh process to expose missing startup assets.
3. Record bundle/model size, fresh-process launch and translation elapsed time. State cache/load conditions; a run immediately after building is not a cold-cache benchmark. These are observations on this host, not a performance SLA or model benchmark.
4. Compile a minimal Tauri shell against that bundle on a build machine with Rust/MSVC. Prove child lifecycle and installer resource layout before adding product screens.
5. When P5 is ready, replace the CLI probe with the real local service and test authentication, no persistent translation cache, crash/export reconciliation and model readiness.
6. Verify installation on a clean supported Windows VM, including WebView2/VC runtime provisioning, offline inference after model install, signing and uninstall/data retention.

Steps 1-3 can close as a packaging feasibility result. D0 as a whole is not complete until steps 4-6 pass. Missing P5, compiler toolchain, signing material or clean VM must be reported separately; they are not evidence against Python or permission to weaken the desktop requirements.

## Handoff to the two implementation owners

**P2-P6 owner:** retain the shared Python service and its REST job contract. Read this proposed bootstrap contract before implementing the desktop profile. Implement local identity, authenticated loopback, process readiness and restart recovery in the existing service, with tests. Do not add a second queue or desktop-specific translation path. Coordinate any incompatible bootstrap change through this plan before desktop implementation.

**Model owner:** keep adapters independent of the desktop toolkit. Deliver a loadable immutable artifact, its exact runtime/native-library dependencies and the catalog metadata above. Test load and translation from a packaged runtime, including a path containing spaces/non-ASCII characters. Report whether runtime binaries and model files may be redistributed. Do not expose an arbitrary remote repository/code execution option as installer model selection.

**Desktop owner:** finish the packaging evidence, then compile the smallest shell/sidecar proof on a configured Windows build machine. Implement the agreed service profile when P5 is available, followed by clean-machine D0 acceptance. Only then proceed to D1/D2 product screens and installer delivery.

## Sources

- [Tauri external binaries](https://v2.tauri.app/develop/sidecar/)
- [Tauri Windows prerequisites](https://v2.tauri.app/start/prerequisites/)
- [Tauri Windows installers](https://v2.tauri.app/distribute/windows-installer/)
- [PyInstaller operating modes](https://pyinstaller.org/en/stable/operating-mode.html)
