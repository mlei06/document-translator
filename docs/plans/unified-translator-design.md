# Unified translator product and delivery specification

Status: Owner-requested delivery contract, 2026-09-30. Implementation and acceptance evidence are tracked in [unified execution](unified-execution.md). This is the single current delivery specification for website automatic translation, shared storage/private History, standard fit/direct downloads, desktop installation/application and the subtle Lenovo-inspired visual treatment.

## 1. Authority, scope and implementation baseline

The latest owner instructions take precedence over earlier drafts: both products use the new ordered ladder; desktop calls Davy directly with the same Davy API key used by the website deployment, provisioned in the installer; no desktop operating-mode selector remains. Installation chooses whether offline assets are present, not how each translation is routed. No website translation-service dependency is allowed for desktop.

Earlier routing, storage, fit, desktop and visual proposals are consolidated here. Historical phase plans are retained in [the archive](../archive/README.md); ADR-027/028/029/030 retain decision history and amendments. Architecture.md remains the canonical component architecture. This specification supplies the current product and delivery contract.

The original design baseline included selectable translators, previews and a packaging probe. Those are historical context. Current source behavior is documented in [Architecture](../Architecture.md) and measured acceptance in [verification](../verification/README.md); this specification itself is not proof of deployment or release readiness.

Reuse the Python core, five document adapters (TXT, DOCX, PPTX, XLSX, PDF), server executable, database queue, leases, typed adapters and existing React components. No separate routing service, cache service, queue, identity service or speculative model fan-out. Preserve unrelated working-tree changes and existing import contracts. No language expansion, new fonts, replacement meadow, OEM commitment or framework rewrite is part of this scope.

### Clean-slate implementation authorization

There are no real users or production records to preserve. The owner authorizes destructive resets of this project's app-managed development databases, uploads, translations, History, jobs, previews and caches. This overrides every legacy-preservation/backfill/compatibility requirement elsewhere in this document or older plans. Prefer a clean schema and coherent target API; update repository callers together. Do not build conversion workflows, legacy download guarantees, preview tombstones, migration backups or rollback tooling for existing development records. Existing saved/temporary behavior is retained only if justified by a continuing product need.

Verify deletion targets stay inside intended app-managed data directories. Preserve source code, unrelated uncommitted work, credentials, model assets and user-owned originals/exports outside those directories. Ongoing safe publication, recovery, cleanup and future-user backup behavior remain required. Documentation changes do not themselves reset data.

## 2. Product experience and common translation policy

Website: sign in, select/drop files, choose target language, Translate, see progress and download. Source language is automatically detected during initial file ingestion solely for read-only display/data; only target language is user-specified. No model, connection mode, generation, terms, dictionary, fit/skip, forced recompute or advanced translation controls. Presentation preferences remain.

Desktop: install, select/right-click/drop files, choose target/destination when needed, Translate, then Open file or Show in folder. No Automatic/Online/Offline selector, model selector or connection-mode setting, including hidden routing controls in Advanced. Internal route names belong in diagnostics only. Existing advanced personal translation settings may remain for terminology or compatible generation settings, stored locally and pinned per request; they cannot bypass the mandatory ladder, introduce a model picker or restore thorough fit/previews. If a custom setting cannot be honored across eligible backends, reject it clearly before execution rather than silently changing its meaning during fallback. Website never accepts these custom settings.

### 2.0 Batch submission and Explorer language shortcuts

Locked owner interaction: **drag in a batch, click a target language immediately, and wait.** The target-language action submits the batch; no additional Translate click or confirmation. Uploading, language detection and folder enumeration never disable target selection. This replaces any older wording that separates target choice from a required Translate action.

Website workflow:
1. Dropping files starts bounded uploads immediately, before target selection.
2. Clicking a target atomically submits that batch with its fixed target, including files still uploading or waiting for an upload slot.
3. Each file becomes eligible for shared-cache lookup/translation as soon as its own upload and validation finish. No batch-wide upload barrier; processing still respects normal bounded queue/capacity admission.
4. Show Uploading -> Queued/Translating -> Saving -> Ready to download as applicable. Cache hits may go directly to Ready after verified admission. Do not display fictitious intermediate phases.
5. Direct per-file downloads and private History use the current shared result. Detection metadata appears when available without confirmation or delaying submission. Upload failure affects only that file; Retry preserves the submitted target and does not resubmit successful siblings.

Desktop workflow:
1. Drop files or folders and click a target to submit immediately.
2. Read/extract locally and use the automatic Davy ladder, then ready installed HY-MT. There is no website upload stage.
3. Folder enumeration may continue after submission. Files discovered within the submitted folder roots inherit that batch's fixed target and enter the existing bounded per-file queue.
4. Completion offers Open file and Show in folder. Enumeration/read errors remain per-item; show honest activity/counts without requiring the main window for Explorer activation.

Batch membership and race handling: the target click atomically fixes the submitted file set or folder-root set and target. Files dropped afterward belong to a new draft batch; later target choices cannot change accepted work. Guard repeated clicks/idempotent submissions so upload-completion races do not create duplicate jobs. Uploads completed before target choice remain bounded unsubmitted staging, not translation jobs; discard on explicit removal/cancel and expire abandoned staging under cleanup policy. Do not begin inference until a target is chosen. Cancelling a submitted folder batch also stops further enumeration/admission for it.

Desktop Settings includes **Explorer shortcuts**: default English; add/remove supported target languages and reorder them, without duplicate entries. Expose one **Translate** submenu, for example:

- Translate to English
- Translate to Chinese

Each submenu action immediately submits all selected files with that action's target, without another language screen, confirmation or main-window interaction. It uses the same queue, automatic ladder, compact progress and collision-safe export behavior. Shortcut preferences only configure target languages, never models/modes. Changes apply to future activations; accepted batches retain their pinned target. If all shortcuts are removed, omit the submenu until a language is enabled. Persist stable language identifiers rather than relying on localized labels.

### 2.0 Target-only language contract

Both website and desktop accept files and a target language, with no source-language picker, confirmation, manual override or Advanced source setting. Explorer uses the target of the activated configured shortcut. New internal-app requests likewise need no source language for the automatic ladder.

Detect language once from extracted document text during initial upload/ingestion (local ingestion on desktop). This is best-effort metadata for the upload card, progress and History, not an inference requirement. Store an optional detected language and confidence/status, including Unknown or Mixed when appropriate; do not invent a supported-language value. Do not add an inference call solely for language detection.

Low confidence, mixed/unknown language, detector failure or a detected language outside the old SMALL-100 enum must not reject an otherwise valid document, request manual input, change routing, or require a source-specific prompt. Detection remains bounded and must not hold translation waiting for a reliable answer. Invalid/corrupt/encrypted documents and extraction failures remain real errors.

Do not reject or automatically skip an entire document merely because detected language equals the target: mixed-language content may still need translation. Let the target-only model process the content, preserving already-target-language passages appropriately. Display Unknown -> target or Mixed -> target without presenting these as model configuration.

All approved Davy and HY-MT prompts are target-only. Remove required source-language arguments and source-dependent prompt branches from their public pipeline/adapter contracts. Do not pass a guessed language just to satisfy the SMALL-100 interface. Isolate any retained SMALL-100 support outside the automatic product path rather than allowing it to constrain this design.

HY-MT base instruction:

```text
Translate the following text into {target_lang}. Note that you should only output the translated result without any additional explanation:

{text}
```

Use the target language's display name, not Markdown/backticks as required prompt syntax. Use the same base wording regardless of detected source; retain necessary exact formatting-tag/placeholder preservation instructions for structured content. “Only output the translated result” excludes commentary, not the required tags. Davy structured-batch prompts retain their response-schema and preservation constraints, but do not specify or require a source language.

Bump output-affecting prompt/profile versions and test rendered payloads for all automatic adapters. Detector version/value/confidence are metadata and must not enter output compatibility or cause inference/retranslation; source-file bytes/hash still define document identity. Target-dependent fonts/writing direction and actual content/structure handling remain valid.

Current inspected code differs: HY-MT user_prompt(text, source, target) branches on whether source or target is Chinese; LlmEngine passes source to system_prompt; Translator rejects source == target. Implementers must remove these dependencies, not just the UI picker. This is a design change, not a claim those code paths have been updated.

### 2.1 One ordered ladder

| Rank | Product name | Configured translator ID |
|---|---|---|
| 1 | Gemma | gemma, bound to gemma-4-31b-it |
| 2 | Nemotron 3 Ultra | nemotron-3-ultra |
| 3 | Nemotron 3 Super | nemotron-3-super-120b |
| 4 | GPT-OSS Thinking | gpt-oss-120b-thinking |
| 5 | GPT-OSS | gpt-oss-120b |
| 6 | Laguna | laguna-s-2.1 |
| 7 | HY-MT Q8_0, when available | hy-mt-local |

Website rank 7 runs on the server. Desktop rank 7 runs on the device only if offline support is installed and ready. Desktop never calls the website service or its server HY-MT. No SMALL-100 rung. Ordering is owner preference, not a certified quality ranking.

Use a shared policy implementation/configuration schema, with ordered IDs and immutable candidate fingerprints. The website deployment config is DOCTRANSLATOR_WEB_TRANSLATION_POLICY, with revision web-auto-v2, davy_order matching ranks 1-6, and local_translator_id hy-mt-local. Ship the same remote order in desktop configuration; no runtime website lookup is required. Reject duplicate/unapproved IDs, wrong Gemma binding, empty revision or incompatible local endpoint. Do not rank arbitrary discovered models. Policy digest includes ordered IDs, candidate fingerprints and schema version. Pin it and effective settings when accepting work; changes require new work/restart as appropriate.

Website requires configured local fallback; its temporary runtime failure is an execution failure, not permission to restore a picker. Desktop installation without local support is valid and has only ranks 1-6. Missing/invalid policy is a clear configuration error. Explicit legacy API jobs remain independent.

### 2.2 Execution, fallback and errors

Verify input and limits before inference. Refresh approved Davy availability through authenticated discovery using the existing 60-second cache and five-second refresh floor. A top-ranked compatible website cache hit skips discovery entirely. A common Davy endpoint outage skips redundant remote calls. Missing approved models skip only their rung.

Each candidate starts from the immutable input and a fresh output workspace. Never combine completed segments from different producers. First successful whole-document translation proceeds through standard fit, saved-file verification and atomic publication. Inference failure advances; bad input, fit/writer/content validation, storage/database errors, cancellation and lost lease do not consume another model. Loaded identity mismatch fails explicitly.

Model-specific timeout, overload, 429/5xx or unavailable inference advances after bounded transport attempts. Invalid response/refusal/context failure advances after bounded existing repair/splitting. Shared endpoint authentication/connectivity/discovery failure skips the remote tier and uses ready local fallback automatically. Deterministic invalid configuration and explicit policy denial are actionable errors, not generic transient model faults. Never weaken TLS. Differentiate transient 429 overload from an explicit hard policy/quota denial. A bad bundled credential can leave local translation available, while diagnostics report the credential issue.

Cap existing transport retries at three attempts per inference request and total retry backoff at 60 seconds, respecting finite request timeouts and capping Retry-After. This is not a document-duration limit. Persist current rung, failure category and attempt fence; worker infrastructure recovery resumes rather than restarting exhausted rungs. A crash inside a rung can repeat inference; exactly-once external calls are not promised.

Desktop owns the durable document job. Davy receives inference requests; do not assume hosted document IDs, status/cancel endpoints or idempotency. Cancel outstanding calls when supported, invalidate old attempts, discard late responses and fence final export. Restoring connectivity does not interrupt a local attempt to upgrade it. Online-only installation with exhausted Davy displays a concise connection/translation error with Retry and Install offline support. An installed but broken local runtime offers repair. No mode choice is required.

### 2.3 HY-MT runtime

Website uses HY-MT1.5-1.8B Q8_0 through llama.cpp Vulkan: four generation threads, four prompt threads, four concurrent slots. Preserve tested flags -ngl 99 -t 4 -tb 4 -c 16384 -np 4 --no-context-shift --cache-ram 0 and the HY-MT adapter with max_concurrency=4. Four slots share one server, not four model copies or four guaranteed document workers. Bound worker admission; do not add a distributed semaphore. Pin GGUF digest/runtime build/backend/settings; operationally verify Vulkan and actual loaded parameters. No silent CPU/Q4/SMALL-100 substitution.

Use the same HY-MT Q8_0 bundle as the desktop release target. Package/manage llama.cpp with the app. Pilot Vulkan/four-thread/four-slot tuning is the initial test profile, not proof for all hardware; validate supported resource limits before release. Any alternate CPU execution profile must be validated with the same model and documented, not silently introduced. Unsupported hardware receives a truthful compatibility outcome. One offline model, no catalog picker.

## 3. Website shared cache and private History

### 3.1 Identity and authorization

One current translated output plus minimal report per (deployment/security namespace, exact original SHA-256, target language). The key excludes owner, model and personal settings. Detected source language is optional display metadata, never a cache-key or execution input. Different names with identical bytes share; identical names with changed bytes do not. Profile identity includes core/format/dictionary/font/fit compatibility ; producer revision is separate from rank.

Receive full upload bytes, compute the hash server-side and validate document limits before granting access. No hash-only lookup/attachment endpoint. Each private History row holds owner, their filename, source digest, optional detected-source metadata and target, first/latest submission and private status/historical producer. Unique per owner/source/target; repeat submissions refresh that user's name/time. A retained verified grant can access a slot recreated after eviction. Never expose other users' names, timestamps, jobs, membership or errors.

Use neutral worker filenames and reports without added uploader/account metadata. Preserve document-internal content. Derive download names from the requesting user's record. Legacy custom output cannot seed a standard shared slot by assumption.

### 3.2 Reuse and ranked replacement

1. Pin common profile and current policy order. Never merge account translation preferences.
2. Verify current blob integrity and compatible input digest, target, output-affecting profile and producer revision. A changed producer revision is incompatible unless an explicit compatibility migration approves it. Reordering alone does not invalidate compatible bytes.
3. Compatible Gemma returns immediately. For a lower result, try only candidates currently ranked above its producer, subject to availability/cooldown.
4. At the saved producer's rung, return the saved output. Never rerun it or anything below it. First higher complete validated success atomically replaces the slot.
5. If no compatible result exists, use the full ladder. New profile compatibility may require a lower-ranked new result to replace an incompatible old result. Failed work preserves old downloadable bytes but does not claim success for the incompatible new request.
6. Release original staging/workspaces at terminal completion; cache hits discard inputs as soon as no upgrade needs them.

One persistent 15-minute failed-upgrade cooldown per shared slot/profile/candidate revision, across users. Reordering alone does not reset it; changed profile/candidate identity does. Cancellation, input/storage failure are not model-health evidence. No personal force/always-new bypass; operators can revoke bad results.

New uploads supply the original for upgrades. History listing/downloads never discover models, infer, upgrade or reconstruct missing originals.

### 3.3 Shared jobs, publication and cancellation

Extend the existing database queue: owner-neutral shared work/attempts, one active work per slot, private jobs as waiters. Simultaneous compatible verified uploads join one work item; different target languages run separately. One source snapshot per work; release duplicate staging after attachment. Shared work owns source/execution pins; private jobs own authorization/status.

Pin profile/order and fence lease, generation and current pointer during publication. Stale attempts cannot downgrade a newer result. Configuration identity changes fail explicitly. Cancel detaches one waiter; others continue. Last-waiter cancellation stops/fences work and releases source while preserving any current output. History deletion/account disablement revokes the relevant user's interest, not other users' work.

### 3.4 Current downloads and deletion

History shows filename, source -> target, date/status and Download whenever the authorized current blob is valid, regardless of the producer of the user's original job. Alice's HY-MT request can later download Bob-triggered Gemma bytes without learning Bob's identity.

Add owner-scoped GET /v1/history and GET /v1/history/{id}/file. New submissions use selection_policy=website_auto, retention=cached and download_semantics=current_shared. Cached job file URLs have explicitly identical current-result semantics. Legacy saved/temporary jobs keep exact-result URLs and promises.

Authorize private grant first, then atomically resolve/pin one immutable output/digest before streaming. Replacement during a transfer does not mix bytes; future downloads see the replacement. Use private/no-store authenticated responses, no public blob URLs. History/job metadata never pins old payloads. Verify readability, not just a DB pointer. Eviction returns 410 translation_unavailable and updates the row; corruption disables availability and alerts the operator. Downloads survive producer outages. Older-profile bytes remain downloadable with truthful provenance until revoked.

Replacement releases old references for GC after readers finish. Temporary old/new coexistence, legacy/API references and finite backups are the only exceptions to one current copy; no per-user or seven-day version hold.

Deleting History removes that owner's grant/waiters. Old cached-job URLs cannot resurrect access. It does not globally delete shared bytes. Operator purge revokes the slot for everyone while private history remains truthful.

## 4. Retention, capacity and scalable storage

| Resource | Target policy |
|---|---|
| Website originals | Active queued/running/recovery work only; release on success/failure/cancel; exclude from backups |
| Shared output/report | One current result; 30 idle days after successful reuse/download; pressure may evict sooner; no absolute age or guaranteed availability |
| Private History | 90 days since that user's last submission; other users' activity does not renew it |
| Terminal work/job metadata | Existing 30-day default; preserve needed provenance before pruning; no byte pin |
| Preview/comparison artifacts | Removed; no new generation, reservation or retention |
| Desktop originals/exports | User-controlled files; never app-GC'd; only active temporary copies are app-managed |
| Legacy/API saved data | Existing promises until authorized deletion/conversion; count physical bytes |
| Backups | Daily, seven recovery points, separate budget; no transient originals |

Listing renews neither History nor cache. Successful download/reuse renews shared idle expiry only. Empty evicted slots can be recreated without deleting grants. Website copy: “Translations are shared and reused. Your history is private. Downloads are available while a translation is stored.” Remove the 20 GiB user storage meter and fixed retention promises. Missing copy: “Translation no longer available. Upload the original to translate again.”

Require explicit global blob/work budgets; charge unique pending/available/deleting bytes once across active/shared/legacy/API references. Reserve separate DB/WAL/log/model/backup capacity. Free-space floor is greater of 5 GiB or 10% of the volume. Initial caps: 100 MiB input, 200 MiB output, 16 MiB report, 1 GiB workspace; validate representative files before release.

At 90% usage including reservations, evict toward 80%: expired results, then unpinned least-recently-used current outputs. Preserve active read/work pins and legacy guarantees. Reserve staging before streaming, output/work once per shared operation and old-plus-new headroom for upgrades. If optional upgrade lacks space, return compatible cached bytes; cold miss returns 503 storage_capacity with Retry-After. Never remove the only good copy to finance speculative improvement.

Transactional reservations convert to charged bytes as written. Failed deletion remains charged; copies count separately, same-volume atomic rename transfers charge. Reconcile orphan reservations/staging after crashes. Retain per-owner request/waiter fairness, not per-user permanent output quotas. Sweep up to 500 records every five minutes and before capacity rejection; immediately attempt terminal source cleanup and retry failed cleanup during sweeps. Mark globally unreferenced/unpinned blobs deleting before removal.

Keep filesystem/SQLite for the initial single-host service. Monitor hit rate, upgrades/cooldowns, avoided inference/bytes, usage/evictions, queue age and DB contention without content logs. Multi-host database/object storage is a separate measured deployment migration, not required machinery for this design.

## 5. Standard fit, direct results and renderer removal

Keep structure-aware standard fit, source-content/protected-value checks, serialized output validation and safe publication. PPTX retains bounded geometry/spacing/shrink repairs, DOCX reflow, XLSX cell fitting and PDF legal placement; TXT fit is not applicable. No unsupported promise of pixel-perfect rendered equivalence.

Remove thorough/rendered fit, repair/render passes, preview packages/ZIPs, text/page previews, comparison screens, page images, preview polling and all production LibreOffice requirements across core/server/CLI/desktop. No hidden renderer flag or replacement renderer. Keep PyMuPDF/fonttools/HarfBuzz where translation/measurement requires them. Desktop Advanced cannot restore removed features.

| Area | Removal/change |
|---|---|
| Core types/config/identity/pipeline | Remove executable thorough/render options and render-only fingerprints; retain legacy reports as inert metadata |
| Core render and format render modules | Remove production conversion/rasterization/preview APIs after checking imports; preserve format-native writing/geometry |
| Server publication | Remove synchronous build_preview and preview ZIP before publication; retain output/report checks and pins |
| Page workers/repositories/settings | Remove scheduling, leases/retries, process supervision, renderer discovery and preview budgets |
| API/generated clients | Remove preview operations/capabilities and new thorough requests via normal generators |
| Web | Remove Preview screen/routes, comparison, page/text queries and content-viewer state |
| Packaging/CI/docs | Remove required LibreOffice and render-only dependencies; regenerate lockfiles, never edit generated artifacts manually |

Do not change standard-fit defaults/floors/prompts as an incidental removal. Prove compatibility where output is unchanged; never relabel old thorough output as newly standard-verified.

Progress states: Queued, Translating, Saving, Ready to download (website) or Ready (desktop). Fit stays inside Translating, including accessibility announcements; hide completed segment percentages during that tail and show honest activity. Saving represents actual write/verification/publication. No Checking layout, rendering-pages status, synthetic percentage or artificial stage delay. Retain internal phase/timing diagnostics.

Owner correction, 2026-09-30: restore the original floating glass-orb interface. Completed available bubbles are keyboard-accessible download buttons; clicking an unfinished orb briefly gives Lenny an annoyed expression and asks the user to wait, without changing the job. A small x cancels active work or dismisses a terminal bubble. Dismiss changes workspace presentation only, not History/access/storage. Failed bubbles explain the error and click to retry; unavailable results never download. Show compact filename/language/status labels, pronounced red progress rings and green completion rings. Position desktop bubbles around Lenny without a scroll panel, paging excess bubbles with compact arrows. Narrow screens use the original horizontal swipe strip with no visible scrollbar. History retains its explicit Download and delete-history actions; no previews return.

No automatic browser download on completion/poll/dismiss. Download all may use existing authorized URLs with unavailable-item reporting and honest browser restrictions; no new stored ZIP variants. Focus targets remain usable without hover; pause decorative movement on hover/focus if needed. No model names in ordinary flow; technical provenance is optional diagnostics, truthful for historical request versus current file. Cache hit can say “A saved translation is ready.” Fallback keeps one bubble and may say “Trying another translation service”; desktop local fallback says “Continuing on this device.” Never imply website local inference runs in the browser.

## 6. Desktop installer, runtime and application

### 6.1 Installation and turnkey credentials

Only two setup choices: **Online only** and **Online and offline (recommended)**. Both install the same automatic-routing app and working Davy configuration. The latter includes/downloads the one offline model. Users do not enter an API key, choose a runtime mode or sign into the website before translating. Davy still requires actual endpoint/network/VPN reachability; installation cannot supply connectivity or guarantee endpoint uptime.

Per explicit owner instruction, embed the same Davy inference API key used by the website deployment in the desktop distribution. This is the Davy credential, not a website session, account password or document-service API key. Inject it through restricted release packaging, not source control, documentation, checked-in defaults, logs, screenshots or test fixtures. The desktop runtime receives it outside command-line arguments/URLs; protect the installed copy using Windows credential protection where practical.

This deliberately distributes a recoverable shared credential to every installer recipient. Signing, obfuscation and Windows protection do not make a client-held key secret from that client. A leak or revocation affects website and installed desktops sharing that key; per-user attribution is unavailable from the credential alone. Record this owner-selected tradeoff rather than claiming an unextractable key. Rotation requires a signed configuration/app update that can be distributed independently of the website service, including managed/offline delivery. Old installers retain the old key until replaced. Do not introduce a new proxy or provisioning control plane to conceal this choice.

Provide normal download-based setup and a full offline installer carrying the same validated runtime/model assets. Offline installation and subsequent local inference work without a network connection. After install, settings show offline support Ready/Not installed/Installing/Needs attention, storage size and Install/Remove/Repair. These manage installed capability, not routing modes. Installation completion does not falsely imply model readiness. Adding/removing offline support requires no app reinstall and must not remove assets pinned by active jobs.

Model metadata includes immutable revision, backend/adapter/runtime compatibility, language pairs, provenance/license, per-file relative path/approved HTTPS URL/size/SHA-256 and measured resource guidance. Treat runtime executables as signed application assets, not executable model content. Reject traversal/absolute model paths and repository-supplied executable code. Prefer per-file downloads; resume only when the remote object validator matches. Check disk/compatibility, verify all files, load-test staging and atomically activate. Cancel/corruption/interruption leaves a recoverable setup screen, not false Ready. Reuse one asset installer for initial setup, repair and updates.

### 6.2 Runtime and lifecycle

Initial target Windows x64; other architectures/OS versions require separate proof. Keep packaged Python/native dependencies in a PyInstaller one-directory bundle paired with the native shell version. End users need no Python/uv/Node/build tools/terminal. Model assets are separately versioned outside application binaries. Tauri remains a candidate pending compiled signed shell/installer acceptance; CLI probe success alone does not select/prove it. Package required redistributable fonts/native prerequisites with license review.

Native shell enforces one instance per Windows user and starts the existing server executable in its desktop profile on an OS-assigned loopback port. The runtime owns direct Davy requests and local inference, keeping shared core/import boundaries. No second queue/database orchestrator in the shell.

Bootstrap:
1. Generate a fresh 256-bit session credential; send over inherited stdin with bootstrap version, never arguments/URLs/logs/plaintext settings.
2. Child derives Windows SID and stable local owner, refuses non-loopback binding and authenticates every API call.
3. Child emits one bounded readiness JSON line with protocol/API version, PID and loopback base URL; logs use stderr. Shell confirms authenticated health and times out/version-checks honestly.
4. Restrict WebView navigation/CSP, validate Host/Origin, no wildcard CORS; keep token in trusted memory. Other OS users and unrelated browser origins must fail. No firewall rule.
5. Own Python workers and llama.cpp in a Windows Job Object. Graceful Quit requests bounded shutdown before terminating only owned children; crash/restart uses durable recovery and export reconciliation.

Use Windows known-folder per-user app data with separate bounded metadata/work/log/model directories and current-user ACLs, never documents beside executables. Window close keeps accepted work running with clear background/tray behavior; explicit Quit explains interruption. Reopen reconnects; full restart rotates port/token but preserves stable owner/work state. Notifications/tray are optional conveniences; main queue remains sufficient. Start on demand, load models lazily and unload when unused (initial five-minute idle default, subject to measurements).

### 6.3 Explorer, exports and local history

Configurable Explorer target-language shortcuts under one Translate submenu are a release requirement, as defined in section 2.0. Thin activation starts the same queue for single/multiple files without a full main-window prerequisite. Never infer inside Explorer or interpolate filenames into shell commands. Modern Windows 11 registration uses IExplorerCommand with app identity per [Microsoft's integration guide](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/integrate-packaged-app-with-file-explorer); signed registration, dynamic configured subcommands, upgrade/uninstall and actual menu placement are D0 proof work.

Main window supports file/folder pickers and drag/drop, target/destination, active queue, bounded recent activity and settings. Enumerate recursively with backpressure; skip reparse points by default, exclude generated output trees, deduplicate selected paths and account for unsupported/locked items without failing siblings. Keep honest enumeration/count progress. Exports use the chosen folder directly, without mirroring source folder trees (owner amendment, 2026-09-30).

Owner amendment, 2026-09-30: default export to the Windows Downloads known folder, with an explicit alternate export-folder picker in the main window. Explorer submissions also default to Downloads. The native shell resolves Downloads and pins an explicit destination on every submission; never infer it from the input path. Export directly into that folder using report.en.docx, then numbered collision names reserved atomically. Check destination access early, choose alternate folder if necessary, preserve source hashes and verify output before atomic publication. Completion offers Open file/Show in folder. No mandatory preview window, original retention or hidden permanent document library.

Desktop sends extracted text/necessary translation context directly to Davy; that is still document content, but the full source file is not uploaded to the website. Parsing, fit, writing, queue and recent activity stay local. Website service must not be required for startup, key use, configuration, discovery, output or caching. Both routes create fresh exports per explicit run; opening an existing export does not infer. No website History sync/cache population or new desktop result cache. Website upgrades/eviction never modify exports.

Keep temporary copies only for active work/recovery, then remove at terminal completion. User-owned originals/exports are never GC'd. Missing local outputs require the user's still-existing original for retranslation. Upgrades preserve app data/exports; uninstall never silently deletes user files. Removal of app-managed data is an explicit uninstall option.

## 7. Shared visual design: restrained Lenovo influence

Owner-requested restoration, 2026-09-30: keep the website as an anchored viewport meadow, with Lenny in a stable position and compact floating file bubbles around him. Long upload lists scroll in bounded regions; result bubbles follow the corrected orb layout above, without scrolling the mascot with the page. Preserve colored document icons in uploads, bubbles and History; file-card feeding, eager drag response, mouth/gulp/chew reactions, tummy count, contextual menu, real sample files, result emergence, completion celebrations and animated dismissal. These are presentation effects only: never delay admission or imply validation/success, and respect reduced motion. Automatic translation and private History remain unchanged. On narrow screens use a result swipe strip below Lenny and bounded upload/speech areas so all actions remain reachable.

Use the existing Lenny interface, Geist Sans/Mono assets and day/night meadow. No Lenovo wordmark, “Built for Lenovo”, corporate footer or added official-brand claim. Preserve white translation-icon glyph paths, geometry, viewBox and radius; change its background only. Header/sign-in symbol matches. Lenny remains mint green, round and independently adjustable; brand tokens do not follow mascot hue.

| Semantic role | Visual contract |
|---|---|
| Icon background | #E2231A reference red, white unchanged symbol |
| Primary Translate | #B51F24, white text; hover #991B20, pressed #80171B; stable bounds |
| Selected language | Light: deep-red label/border, pale-red fill; dark: light label, deep-red fill, visible boundary; only for a real selected state |
| Active progress | Deep red light theme; lighter red such as #FF6B63 dark theme, verified against track |
| Ready/success | Success green plus checkmark/text |
| Neutral controls | Download, sign-in, settings, cancel, close, dismiss and secondary actions stay neutral |
| Error/destructive | Explicit icon/text semantics; red alone cannot distinguish error from active work |

Separate --brand-red, --action-primary, --action-primary-hover, --action-primary-fg, --progress-active, --progress-success and --selection-bg tokens with light/dark/system values. No global green replacement or blanket red button rule. Removed Translate again/skip controls are not restyled or restored. Preserve existing immediate language-submit behavior where present; styling must not introduce an extra confirmation.

Controls/chips/inputs use 6px radii; headers/speech cards/menus/settings/History use 10px; small progress labels may use 8px. Preserve circular mascot/bubbles/avatars/badges and icon geometry. Keep usable targets, spacing and speech pointer; avoid extra card layers, heavy shadows or thick outlines.

Use weights 600-700 for headings/important filenames, 400-500 body/help, 600 actions. Near-black/light and near-white/dark labels, readable secondary text without opacity washout. Retain at least 14px progress percentage, 13px filename and 12px status, tabular numerals and wrapping. Preserve thick readable rings and opaque label backing. State derives from real job status, so completed rings are green even if a prior progress snapshot remains.

Meadow-only starting treatment: saturation about 0.85, neutral wash 6-10% light and 8-12% dark, tuned against screenshots. Never filter page root, mascot, controls, text or indicators. Keep horizon/day-night framing; opaque control surfaces beat full-screen blur. No cursor parallax or pointer-following lighting; only Lenny follows the pointer. Ambient motion respects reduced motion. Do not generate new background assets.

Retain styles/lenny.css foundation and add one labelled theme section in styles/app.css. Inspect lib/theme.ts so presentation preferences cannot override action tokens. Style surviving Home, Bubbles, History, Header, SignIn and settings, using existing World layers and glyphs. Shared desktop surfaces reuse the palette/type/control treatment; compact Explorer progress need not reproduce a full meadow scene.

Normal text contrast at least 4.5:1, meaningful non-text state contrast 3:1, measured on composited surfaces. Visible unclipped keyboard focus, no color-only state, no hover-only actions. Verify 1440/768/375 and 320px layouts, narrow landscape, 200% zoom, long names/statuses, both themes/system theme and reduced motion. One polite live region announces meaningful progress/fallback, not every poll. Never announce Checking layout.

The existing Lenovo UI plan cites the [visual-identity guide color table, page 24](https://thepalladium.agency/wp-content/uploads/2024/09/lenovo-visual-identity-guidelines.pdf) and [Lenovo Brand World](https://brandworld.lenovo.com/visual-identity/logo/) as visual references. Red variants are application accessibility choices, not certified corporate colors. Existing artwork/fonts are preserved.

## 8. Clean-slate implementation sequence

### 8.1 Fresh schema and renderer removal

Implement the final shared slots/work/attempts/private grants/reservations schema directly. Reset app-managed development state when needed; do not backfill or convert existing records. Coordinate backend/frontend/client updates and stop old workers before reset so they cannot republish obsolete state. Regenerate schemas and clients with normal tooling. Test fresh initialization and current contracts.

Remove obsolete preview endpoints, old frontend polling, source-language input contracts and thorough/rendering options directly. No legacy tombstones or historical report readers are required solely for existing development data. Keep safe request validation, actionable errors and authorization on the final API.

Future operational backups include current metadata and retained outputs/reports under a separate budget, excluding transient originals. Restore must reconcile grants/revocations and stale work before exposure. Validate future recovery with synthetic fixtures; do not rehearse migration of expendable current data.

### 8.2 Delivery order

1. Freeze common policy/error/provenance contracts and final website schema. Pin the new remote order on both targets; do not silently alter live configuration as documentation work.
2. Implement shared admission/work/waiters/reservations/current downloads and cleanup together; retain restart/cancel fencing.
3. Remove rendered fit/preview pipeline, endpoints and UI; retain native standard fit and direct verified output.
4. Desktop D0: signed clean-machine runtime/shell/Explorer identity, bundled-key injection without logging, Davy direct inference with website stopped, managed HY-MT load/translation and authenticated local host. Record OS/architecture/resources/artifact hashes/signing/licensing. Tauri/provisioning/native prereqs require evidence.
5. Desktop D1: two install choices, one model, full offline bundle, add/remove/repair/resume and truthful readiness. Desktop D2: Explorer/main-window shared queue, automatic ladder, bounded fallback and collision-safe local exports. No dependency on website cached endpoints.
6. Apply restrained visual theme to surviving controls, capture deterministic before/after states, update UI audit and verify actual end-user flow. Do not decorate removed UI or ship test fixtures in production.
7. Verify fresh initialization, future backup/restore and release checks; publish measured evidence and unresolved environment gates. Lenovo managed deployment/OEM preload remains later work with separate agreements/hardware/servicing evidence.

## 9. Acceptance and evidence

- Batch interaction: with slow uploads, target click submits immediately and pins every batch member's target; an early validated file starts without waiting for a slow sibling. Detection latency/failure does not disable selection. Retry resubmits only the failed item. Later drops form a new draft; double-clicks and upload-completion races never duplicate work. Unsubmitted staging is bounded and cleaned.
- Desktop batch/shortcuts: choose target during slow folder enumeration; subsequently discovered descendants inherit it while later drops remain separate. Verify English/Chinese shortcut add/remove/reorder, persistence, multi-selection activation, menu refresh and no modal/main-window prerequisite. Changes to shortcuts never retarget running jobs. Empty shortcut configuration removes the submenu. Cancellation stops further folder admission.

- Language: target-only requests on both products; no source picker/Advanced override; Unknown/Mixed/low-confidence/detector failure does not block inference; source-equals-target does not reject or skip mixed documents; prompt payloads ignore detected source and preserve required tags/schema; detector-only changes neither invalidate cached output nor cause model calls.
- Policy: exact new order on both products; Gemma success uses no later model; missing model skips one rung; endpoint outage skips redundant calls; all remote candidates precede local. No mode/model chooser or key entry. Local missing/broken behavior is actionable. Pin/identity/restart cases are deterministic.
- Fallback: no mixed-model document, no exhausted-rung queue restart, no stale/late output publication, one export, cancellation respected; bad input/fit/storage does not consume inference rungs. Mock tests do not certify actual model quality.
- Cache/access: Alice gets HY-MT, Bob upgrades to Gemma, both current downloads become Gemma without private metadata leakage. Different names/same bytes share, same name/different bytes miss; hash-only/guessed IDs fail. Only higher models run; reordered ranks/cooldown/profile incompatibility work.
- Shared work: simultaneous users join one execution; cancel/delete/disable one does not stop others; last waiter fences work. One current slot, reader-consistent atomic replacement, no history version pins. Eviction disables download, recreation restores retained grants. Listing/download never infer.
- Storage: fake clocks/pressure test idle/history expiry, reservations/failed deletion/headroom, no seven-day guarantee, terminal original cleanup and backup exclusion. Verify caps on all formats and safe future-user retention behavior.
- Renderer removal: real service/CLI/API jobs on a machine without LibreOffice; no preview network calls, ZIPs, render subprocesses/page work for hits or misses; output opens, protected content/geometry/PDF placement remain valid. Removed endpoints/UI have no remaining callers; cleanup works without a legacy compatibility layer.
- Desktop: clean install without dev tools/key entry; cold-start Davy translation with website stopped; full offline install and translation with network disabled; online-only error/install-offline flow; model corruption/interruption/disk exhaustion; Unicode/space/long paths, folder dedupe/locked destinations; duplicate Explorer activation, window-close/Quit/crash recovery; exported files intact after update/uninstall.
- Credentials: packaged secret absent from repository/logs/arguments/diagnostics; runtime can authenticate immediately on a reachable approved Davy network; signed key-update delivery independent of website demonstrated. Tests must not claim client key extraction is prevented.
- Security boundaries: cross-user and unrelated-browser loopback denial, authenticated history/current files, no private settings in shared outputs, safe shared reports. Desktop activity neither uploads full source to website nor syncs its History.
- UI: ready-orb click downloads directly; unfinished click asks for patience with an annoyed Lenny; small x cancels/dismisses and desktop Open/Show folder; unavailable current output refresh; no hidden Checking layout label/announcement or stale 100% during fit. Red active/green ready, mint Lenny, anchored meadow, unchanged white glyphs, no branding text. Visual/keyboard/contrast/responsive checks listed above.
- Performance: measure time to ready/download before/after on identical fixtures with cold/warm cases and mandatory-fit timing; no invented speedup. Real Davy acceptance for every enabled rung and all formats, including primary Chinese-to-English; capture relevant model/prompt quality evidence. Unsupported configured rungs require operator correction before rollout.
- Implementation checks: uv sync --all-packages; uv run ruff format --check; uv run ruff check; uv run pyright; uv run lint-imports; uv run pytest. Also actual frontend lint/typecheck/unit/build/Playwright scripts, signed installer tests and real-runtime integration. Record unavailable prerequisites honestly. Documentation-only consolidation uses document/link/consistency checks, not a claim of production acceptance.

## 10. Source map

| Earlier document | Consolidated coverage |
|---|---|
| Automatic website translation / ADR-027 | Sections 2, 3, 8, 9 |
| Website cache and retention / ADR-028 | Sections 3, 4, 8, 9 |
| Standard fit/direct downloads / ADR-029 | Sections 5, 8, 9 |
| Desktop Online/Offline delivery / ADR-030 | Sections 2, 6, 8, 9; earlier mode selectors and individual-credential requirement superseded |
| D0 desktop runtime contract | Section 6.2 plus D0 acceptance in 8/9; historical probe evidence remains in experiments |
| Desktop/internal-app D1/D2 | Section 6 and 8/9; separate I1 API integration scope is preserved |
| Subtle Lenovo UI | Section 7 and visual acceptance in 9; stale skip/layout/Translate again references removed |

Internal-app integration remains the existing versioned REST submit/status/cancel/exact-result contract with individual service-account authorization, idempotency, bounded batches/retries and explicit saved/temporary retention, or deliberate public-core embedding where the caller owns lifecycle. It is not changed to embedded shared desktop credentials or implicitly opted into shared cache. MCP remains later work.

Owner-approved UI refinement, 2026-09-30: uploads remain inside an expandable tummy-count pill rather than a persistent sidebar. Its light-dismiss file list retains progress, removal and retry, automatically opens on a new upload failure and reveals that item. Completed and active orbs use a two-line caption (filename; target and concise status), a subtle translucent backing, percentage only while measurable, and a single completion check. Keep detailed errors visible and full filenames accessible on hover/focus.

History presentation refinement, 2026-09-30: use compact aligned document rows (file icon/name, language pair, availability/status, updated date, icon actions), with metadata wrapping beneath the filename on narrow screens. Remove repeated tall button stacks. Download and remove remain explicit accessible controls; unavailable downloads remain disabled with an explanation, and removal confirmation expands only its own row.

Default-language correction, 2026-09-30: a supported saved default is pinned to each newly added file batch before upload callbacks run, so dropping/picking/sample-feeding files starts translation as soon as each upload is ready without asking again. Ask me every time (or an unavailable saved language) retains manual selection. Changing the preference affects future additions only; it never retargets earlier drafts or accepted/pending work. Remove the redundant default-language shortcut button and reflect the selected target in Lenny's upload message.
