# Implementation Plans

One file per phase or subphase from `docs/IMPLEMENTATION_PLAN.md`, named `<ID>-<short-name>.md` (e.g. `P2.1-authentication.md`). Start each from [`_TEMPLATE.md`](_TEMPLATE.md).

A plan is the contract between the architect and the coder(s) implementing it: it should be detailed enough that a coder doesn't need to make architectural decisions while implementing.

## Execution Entry Point

Start with the [P2-P6 delivery handoff](P2-P6-delivery-handoff.md): user-owned service CLI/API batches, complete five-format backend, then audit/integrate the existing mock web UI. It fixes product choices and provides the multi-role design/implementation/review sequence; technical gates still need evidence before coding.

## Current Index

| Plan | State / use |
|------|-------------|
| [P0](P0-project-foundation.md) | Completed foundation |
| [P1](P1-translation-engines-and-benchmark.md) | Approved, implemented; delivery verification/closure outstanding |
| [P1.1](P1.1-baseline-capture.md) | Draft operational plan for deferred baselines; required before prompt/model changes |
| [P2.0](P2.0-document-design-validation.md) | Draft architect experiments and decisions |
| [P2](P2-document-translation-and-cli.md) | Draft API/format/CLI contract; technical gates precede architect acceptance/coding |
| [P3.0](P3.0-fit-design-validation.md) | Draft measurement/font design work |
| [P3 implementation](P3-fit-check.md) | Tasks/contracts after measurement gate |
| [P4](P4-pdf-support.md) | PDF experiment/ADR and implementation contract |
| [P5 implementation](P5-server-and-service-cli.md) | Users, auth, REST, batches, jobs, storage and service CLI |
| [P6](P6-web-ui-integration.md) | Existing mock audit, real backend integration and browser acceptance |
| [P5.0](P5.0-server-design-validation.md) | Draft authentication/server/operations design work |

Design-validation plans produce decisions and a coder-ready implementation contract; they do not authorize coders to fill in architectural gaps. Drafting a plan does not mark its phase Active or an ADR Accepted. The roadmap owns phase/board state.
