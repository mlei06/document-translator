# ADR-027 - Automatic website translation

Status: Owner-requested product direction, 2026-09-29; implementation pending. Operational defaults below are the specification, not measured model-quality rankings.

## Context and authority

The owner requires a simpler website: no model selection, Gemma first, then the other approved Davy models, then a server-local model. Storage should support avoiding repeated translation. Current code instead pins a user-selected translator and fails or retries that translator; reuse is restricted to the owned document's current result.

This decision supersedes ADR-019/020/024 for website selection/fallback and ADR-025's no-fallback restriction for this hosted policy. ADR-028 additionally supersedes website personal translation settings (ADR-022) and output-affecting fit/skip choices: one common website profile enables shared reuse. Local desktop advanced settings remain available; legacy/API contracts remain separate. ADR-028 authorizes shared results with private history and current-result downloads, while preserving legacy saved promises.

## Decision

- Hosted browser submissions always use one server-owned automatic policy. Gemma is its first candidate; it is not an editable user preference. All other enabled, approved Davy entries follow in an explicit administrator-defined order. Exactly one configured server-local translator is last.
- Owner-updated order for website and desktop: `gemma`, `nemotron-3-ultra`, `nemotron-3-super-120b`, `gpt-oss-120b-thinking`, `gpt-oss-120b`, `laguna-s-2.1`, then available `hy-mt-local`. Website HY-MT1.5-1.8B Q8_0 uses llama.cpp Vulkan, four generation/prompt threads and four slots; desktop owns its installed runtime. No SMALL-100 rung. This is preferred order, not certified quality. The [unified specification](../plans/unified-translator-design.md) owns current policy, delivery and acceptance.
- A verified upload consults the shared slot. Compatible Gemma output is immediately reusable; a lower-ranked saved result stops traversal at its producer. Try only eligible higher rungs, replace on validated success, otherwise reuse without rerunning equal/lower models. Shared cooldowns bound repeated failed upgrades. History downloads always serve current stored output without discovery or inference. No website force/always-new bypass.
- A model failure advances the whole document to the next eligible candidate. Never splice successful segments from different models into one output. Do not fan out speculative translations.
- Distinguish model/service failures from invalid documents, cancellation, storage failures and lost worker ownership. Only the former permit fallback. Common Davy outages may mark all remaining Davy candidates unavailable without repeated calls to a known failed endpoint.
- Keep private history/authorization, verified uploads, common-profile and producer identities, atomic publication and bounded runtime loading. New cached downloads resolve the current shared result; each active stream pins immutable bytes. Legacy/API exact downloads remain separate. Never label a fallback result as Gemma.
- Remove website model/decoding/connection-retry/personal terminology/dictionary/fit/skip/force controls. Keep files, target language, detected source, progress/cancel, History and downloads. Advanced personal translation options belong to local desktop installs, not a hidden website panel.

## Alternatives and consequences

Keeping an advanced model picker conflicts with the requested single website path. Per-segment fallback complicates reproducibility and document consistency. A routing service, global health control plane, speculative parallel inference and persistent segment cache are unnecessary for this change.

Whole-document fallback can repeat work when a model fails late. Durable rung progress prevents restarting exhausted rungs; interruption within a rung may repeat it. Cross-user reuse, ranked stopping and cooldowns reduce repeated work. Quality differences remain visible in actual result provenance. Upgrades on new uploads intentionally trade computation for preferred-model results; history reads never cause upgrades.

The component contract is in [Architecture](../Architecture.md#automatic-website-translation-adr-027); implementation and acceptance are in [the delivery specification](../plans/unified-translator-design.md).
