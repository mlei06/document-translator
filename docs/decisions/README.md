# Architecture Decision Records

Lightweight ADRs for decisions that are significant and hard to reverse (choice of datastore, auth strategy, major framework, etc.). Number sequentially: `ADR-001-<short-name>.md`, `ADR-002-...`. Start each from [`ADR-000-template.md`](ADR-000-template.md).

An ADR exists so that an agent working on this months later understands a decision was intentional, instead of "fixing" it back to whatever seems locally simpler.

## Index

| ADR | State |
|-----|-------|
| [001 MCP deployment](ADR-001-mcp-server-deployment.md) | Accepted |
| [002 language and stack](ADR-002-language-and-stack.md) | Accepted |
| [003 source structure](ADR-003-source-structure.md) | Accepted |
| [004 job storage](ADR-004-job-storage.md) | Accepted |
| [005 quality evaluation](ADR-005-translation-quality-evaluation.md) | Accepted |
| [006 MT selection](ADR-006-mt-model-selection.md) | Accepted; full quality baseline deferred |
| [007 reuse and document storage](ADR-007-translation-reuse-and-document-storage.md) | Partly superseded by ADR-014 |
| [008 job execution](ADR-008-job-execution-model.md) | Accepted |
| [009 XLSX preservation](ADR-009-xlsx-preservation.md) | Accepted (sheet names preserved; recalculation on open) |
| [010 shared service CLI](ADR-010-shared-service-cli.md) | Accepted by owner; implementation pending |
| [011 document translation contract](ADR-011-document-translation-contract.md) | Accepted (formatting, writers, detection, identity) |
| [012 lightweight fit](ADR-012-lightweight-fit-policy.md) | Accepted by owner; implementation reconciliation pending |
| [013 deployment profiles](ADR-013-deployment-profiles.md) | Accepted direction; storage amended by ADR-014 |
| [014 storage, ownership and retranslation](ADR-014-storage-ownership-and-retranslation.md) | Accepted; implementation in progress on `release/p2-p6` |
| [015 authentication and ownership](ADR-015-authentication-and-ownership.md) | Accepted (per-user opaque API keys, owner-filtered queries, TLS for network binds); its cache side-channel section is superseded by ADR-014 (owner-scoped reuse) |
| [016 service execution and operations](ADR-016-service-execution-and-operations.md) | Accepted (attempt claim tokens amending ADR-008; blob pins and GC; backup/restore); its cache and retention defaults are superseded by ADR-014 |
| [017 web UI service extensions](ADR-017-web-ui-service-extensions.md) | Accepted (browser sessions, detection via saved documents, preview packages, bubble dismissal, SPA hosting) |
| [018 PDF strategy](ADR-018-pdf-strategy.md) | Accepted (PyMuPDF targeted replacement; amends ADR-003's capability table for PDF) |
| [019 configured translators](ADR-019-configured-translators.md) | Accepted; service/CLI/web selection implemented; full P6 acceptance pending; installer remains D0/D1 |
| [020 browser accounts and decoding](ADR-020-browser-accounts-and-decoding.md) | Accepted; email/password accounts and SMALL-100 Beam 4/Greedy presets |
| [021 empty translation preservation](ADR-021-empty-translation-preservation.md) | Accepted; preserve empty-answer source text with a translation warning |
| [022 protected dictionaries](ADR-022-protected-dictionaries.md) | Accepted; syntax protection, maintained names and private account dictionaries |
| [023 page rendering for previews](ADR-023-page-rendering-for-previews.md) | Accepted; renders after publication, `DOCTRANSLATOR_PAGE_PREVIEWS` eager/on_open/off; browser-verified for PDF, PPTX, DOCX and XLSX |
| [024 translator availability](ADR-024-translator-availability.md) | Accepted; installed local MT artifacts and cached approved Davy model discovery |
| [025 local HY-MT](ADR-025-local-hy-mt.md) | Owner-authorized laptop benchmarking and explicit local HY-MT protocol integration; external inference-server lifecycle |
| [026 offline fit v2](ADR-026-offline-fit-v2.md) | Accepted; structure-aware offline fitting, bounded repairs and opt-in rendered verification |
| [027 automatic website translation](ADR-027-automatic-website-translation.md) | Owner-requested direction; Gemma/Davy/HY-MT Q8 Vulkan ladder; specification, not implemented |
| [028 website cache and retention](ADR-028-website-cache-and-retention.md) | Owner-approved shared standard output, private History, ranked replacement/current downloads; specification, not implemented |
| [029 standard fit and direct downloads](ADR-029-standard-fit-direct-download.md) | Owner-approved removal of thorough fit, previews and production LibreOffice; specification, not implemented |
| [030 desktop Online/Offline delivery](ADR-030-desktop-online-offline-delivery.md) | Amended: automatic direct Davy, installer-provisioned shared key, optional device HY-MT; no modes; unified specification, implementation pending |

Proposed ADRs are review material, not architecture authority over an accepted decision or the README. Accepted server decisions describe the intended design; they do not imply those features are implemented.
