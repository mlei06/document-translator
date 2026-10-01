# Implementation Plans

One file per phase or subphase from `docs/IMPLEMENTATION_PLAN.md`, named `<ID>-<short-name>.md` (e.g. `P2.1-authentication.md`). Start each from [`_TEMPLATE.md`](_TEMPLATE.md).

A plan is the contract between the architect and the coder(s) implementing it: it should be detailed enough that a coder doesn't need to make architectural decisions while implementing.

## Execution Entry Point

Start with [Unified translator product and delivery specification](unified-translator-design.md). It consolidates website routing/cache/private History, standard fit/direct downloads, automatic desktop installation/application and subtle Lenovo visuals. The former five feature plans now point there; their duplicate delivery text has been retired.

Read [standard fit/direct downloads](standard-fit-direct-download.md) with ADR-027/028's website plans: ADR-029 removes all preview/rendered-fit requirements from the target release, retaining standard fit and direct bubble/History actions.

Latest website specifications: [automatic translation](automatic-website-translation.md) and [cache/retention](website-cache-and-retention.md). Read ADR-027/028 before older website selection and permanent-library plans. These are design deliverables, not completed implementation.

Start with the [P2-P6 delivery handoff](P2-P6-delivery-handoff.md): user-owned service CLI/API batches, complete five-format backend, then audit/integrate the existing mock web UI. It fixes product choices and provides the multi-role design/implementation/review sequence; technical gates still need evidence before coding.

## Current Index

| Plan | State / use |
|------|-------------|
| [Desktop UI design](desktop-ui-design.md) | Implemented desktop source: drag feedback, draft selection, destination reset and compact activity; automated verification recorded separately; updated native UI acceptance pending |
| [Subtle Lenovo-inspired UI](subtle-lenovo-ui.md) | Proposed visual sweep: unchanged white icon on red, restrained action accents, sharper controls and quieter meadow; planning only |
| [P0](P0-project-foundation.md) | Completed foundation |
| [P1](P1-translation-engines-and-benchmark.md) | Approved, implemented; delivery verification/closure outstanding |
| [P1.1](P1.1-baseline-capture.md) | Draft operational plan for deferred baselines; required before prompt/model changes |
| [P2.0](P2.0-document-design-validation.md) | Draft architect experiments and decisions |
| [P2](P2-document-translation-and-cli.md) | Draft API/format/CLI contract; technical gates precede architect acceptance/coding |
| [P3.0](P3.0-fit-design-validation.md) | Draft measurement/font design work |
| [P3 implementation](P3-fit-check.md) | Tasks/contracts after measurement gate |
| [Offline fit v2](offline-fit-v2.md) | Owner-approved follow-on: structure-aware offline repairs and explicit thorough verification; implementation evidence in the plan |
| [P4](P4-pdf-support.md) | PDF experiment/ADR and implementation contract |
| [P5 implementation](P5-server-and-service-cli.md) | Users, auth, REST, batches, jobs, storage and service CLI |
| [P6](P6-web-ui-integration.md) | Existing mock audit, real backend integration and browser acceptance |
| [P5-D2 storage and ownership](P5-D2-storage-and-ownership.md) | ADR-014 transition: local exports, hosted current results, human/service owners |
| [P5-P6 progress](P5-P6-document-progress.md) | Proposed latest-job snapshot, honest stage/count display, polling and recovery contract |
| [P5.0](P5.0-server-design-validation.md) | Draft authentication/server/operations design work |

Design-validation plans produce decisions and a coder-ready implementation contract; they do not authorize coders to fill in architectural gaps. Drafting a plan does not mark its phase Active or an ADR Accepted. The roadmap owns phase/board state.
