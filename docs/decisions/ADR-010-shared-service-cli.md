# ADR-010: Shared Service for the Pre-GUI CLI and API

> Superseded in part on 2026-09-29 by [ADR-014](ADR-014-storage-ownership-and-retranslation.md): local exports always translate fresh with temporary working storage; hosted owners retain one current result per document/language pair, with owner-scoped reuse and immutable job results. Human and application service accounts are owners. Earlier global-cache, mandatory version-history, desktop-library and conflicting retention requirements below are historical; ADR-014 takes precedence. Fit skip remains supported, but no separate old full-fit cache is retained.


## Status

Accepted (2026-09-27), based on the owner's explicit selection of a shared service for CLI and API. Implementation is pending.

## Context

The requested pre-GUI release must translate batches of TXT, PPTX, DOCX, XLSX and text-based PDF through either CLI or API, with fit checking, cache lookup and persisted results. P6 integrates the existing mock web GUI after this backend milestone; the overall handoff now includes P6.

ADR-003 and ADR-007 originally describe only a synchronous, database-free CLI. Building an independent persistent CLI would duplicate server storage, ownership, cache and recovery behavior. Calling server Python internals from the CLI would violate the enforced app boundaries.

## Decision

- Add service commands to `doctranslator_cli` in P5. They use the versioned REST API over HTTP and do not import `doctranslator_server` or access its database/blob directory.
- Keep P2's `translate` command as an explicitly local, synchronous command using the public core. It writes files but has no persistent job history or document cache. It remains useful for core acceptance and offline operation.
- The pre-GUI acceptance path uses `submit`, `jobs`, `batches` and `download` against the shared service. It never silently falls back to local translation if the service is unavailable.
- REST submissions and service CLI submissions share authentication, job records, the exact-byte document cache, original/output/report blobs, document ownership and retention.
- Each uploaded file is an independent job. A batch groups references and outcomes; it is not an all-or-nothing translation transaction or a second queue. One corrupt file cannot cancel unrelated jobs.
- Process long batches through bounded per-file HTTP requests, bounded upload concurrency and the existing database queue. There is no product-level maximum total batch count; per-file limits, disk capacity and queue admission provide explicit backpressure. A manifest avoids operating-system command-line length limits. No promise of infinite storage or simultaneous processing is made.
- The release gate requires P2, P3, P4 and P5 together. P5 development may begin after P2, but the pre-GUI release is not complete until all five formats and the fit contract are verified through the service.

## Amendments to Earlier Decisions

ADR-003's synchronous CLI description still applies to `translate`; service commands are thin HTTP clients. Its Python import boundaries remain unchanged.

ADR-007's statement that the CLI does not use the cache applies only to local `translate`. Service CLI commands use the same server cache as REST. The core remains database-free. No persistent segment cache is added.

ADR-008's job queue remains authoritative. Batch grouping adds no broker or second execution mechanism.

## Consequences

- A local service must be running even when persistent CLI use is on the same laptop. Startup and credentials need a documented bootstrap path.
- The CLI can resume submissions and downloads from a private manifest containing IDs and local paths, never credentials or full file contents.
- P6 can consume the same batch/job API without moving translation logic into the UI.
- The detailed contracts and acceptance sequence live in [the P2-P6 handoff](../archive/plans/P2-P6-delivery-handoff.md) and [P5](../archive/plans/P5-server-and-service-cli.md).
