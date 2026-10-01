# ADR-028 - Shared website translations and private history

Status: Owner-approved direction, 2026-09-29; specification only, implementation pending. Replaces the earlier owner-scoped cache, multiple settings variants, seven-day exact website output guarantee and pending ranked-upgrade proposal.

## Context and authority

Every website user uses one standard translation configuration. Advanced personal translation settings belong only to local desktop installs. Users have private history showing their filenames, source/target languages and a download button whenever a shared translation exists, irrespective of the model used on their original request.

Current code retains owned source/current results, merges account translation settings and pins exact job outputs. This decision supersedes those website parts of ADR-014 and ADR-022. ADR-027 defines routing. Existing API saved/temporary contracts and legacy saved promises remain explicit migration exceptions; they do not populate the new shared cache by default.

## Decision

ADR-029 removes all preview/comparison generation and thorough fit from this target. No preview budget, on-open rendering or source-comparison re-upload workflow remains; direct downloads and minimal metadata replace content viewers.

- One shared slot per company deployment, original SHA-256 and target language. User, filename and model are not cache identity. Separate security domains require separate namespaces.
- At most one current reusable translated output per slot, with canonical source language, actual producer/revision, common-profile identity, fit status and minimal safe report. No personal variants or customized bypass.
- Website uses the common dictionary, generation settings and standard fit. Remove terminology/dictionary/model/decoding/fit/skip/force/always-new options. Users choose target; the standard pipeline detects source. Local desktop advanced outputs never populate shared slots.
- On verified upload, try only eligible models above the compatible saved result's producer. Atomically replace after complete validated success; otherwise return the saved result without rerunning its model or anything lower. No compatible result uses the full ladder. Shared failed-upgrade cooldown prevents repeated expensive failures. Rank represents preference, not measured quality.
- History/jobs are private grants earned by verified source upload or an already-authorized source reference. Hashes alone grant nothing. No shared-library listing or cross-user metadata visibility. Shared artifacts contain no uploader filenames, identity or personal options.
- History download resolves the current shared output, regardless of historical producer. New cached-job downloads explicitly use the same current-result semantics. Historical provenance is metadata, never a reason to retain old payloads. Downloading history performs no inference/discovery.
- No seven-day or exact-version guarantee for new website work. Release superseded payloads after active readers/publication pins finish. Finite backups and independent legacy/API references remain documented exceptions.
- Originals exist only for active work and bounded recovery; release at success, terminal failure or cancellation, including source previews/workspaces. Do not back up transient originals. Retain hashes/size/format. Upgrades require a fresh verified original, never a previously translated output.
- Shared idle expiry defaults to 30 days since successful reuse/download; unpinned entries may be evicted earlier under pressure. Useful results have no arbitrary maximum age. Private history expires 90 days after that user's last submission.
- Deleting history removes that user's record/access, not shared translations or another user's access. Operator purge can revoke a shared slot. Global budgets/reservations/GC bound storage; no website per-user permanent allowance.

## Consequences

Alice receives HY-MT. Bob later uploads identical bytes and upgrades the slot to Gemma. Alice's same history row now downloads Gemma, while her historical producer metadata stays HY-MT. Eviction makes downloads unavailable; a later upload by another user may restore availability for Alice's still-retained grant.

Atomic replacement briefly needs old and new outputs; active streams finish against pinned bytes. These are operational exceptions, not retained versions. Legacy saved promises cannot be silently removed to achieve a physical one-copy claim. Translated files preserve source structure/assets; deleting originals does not remove all source information from translated outputs.

A common-profile change can invalidate reuse without allocating another slot. Preserve old output during replacement. History can download an available older-profile result with truthful provenance unless revoked; new translation submissions enforce current compatibility. No background upgrade on model recovery or history reads.

See [Architecture](../Architecture.md#bounded-website-cache-and-retention-adr-028) and [delivery specification](../plans/website-cache-and-retention.md).
