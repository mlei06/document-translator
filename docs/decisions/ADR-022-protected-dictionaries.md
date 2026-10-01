# ADR-022 - Literal Protection and Account Dictionaries

Status: Accepted by owner request, 2026-09-29. Amends ADR-011 section 3.

## Decision

Website amendment: ADR-028 removes personal dictionaries/toggles and account-settings merging from standard hosted website/shared-cache work. The common maintained dictionary remains. Personal translation options belong to local desktop advanced settings. The implementation described below remains historical/current code until this amendment ships; existing separate API contracts require explicit compatibility, not a new customized website bypass.

Protect literals before translation using the existing `Keep` nodes and validated placeholder restoration. Do not translate names and then reverse their translations. Use conservative syntax rules for recognizable URLs (including bare domains with paths), email addresses, paths, environment identifiers, dotfiles and standalone environment assignments. Do not protect ordinary numbers or entire prose sentences merely because they contain punctuation.

Ship a small reviewed UTF-8 dictionary of unambiguous company and product names in the core package. Keep the data separate from regex/code, expose its entries through the public core API, and include its content digest in output identity. Dictionary matches are case-sensitive, respect Latin identifier boundaries, prefer longer overlapping terms, and preserve exact source spelling. Chinese entries may occur within Chinese prose. This is preservation, not translation or terminology substitution.

Users can view the default list, enable or disable it, and edit their private additional words in Settings. Store the account dictionary on the service, not in shared browser preferences. Human accounts and application service accounts use the same ownership rules. Accept at most 500 account entries of up to 200 characters each; reject invalid entries rather than truncate. Normalize whitespace at entry edges, deduplicate and order entries deterministically. API access uses existing authentication and CSRF protection.

`GET /v1/me/translation-settings` returns `protected_terms`, `use_default_dictionary` and the read-only `default_protected_terms`. `PUT` replaces the two writable fields. Explicit per-request protected terms add to the account terms. An optional per-request default-dictionary boolean overrides the account choice. Direct core/local callers default to the built-in dictionary and can disable it through document options.

Snapshot effective account and request options into each new job before fingerprinting. Workers never read mutable account preferences. Settings changes affect new submissions, not queued jobs or an idempotent replay of a prior submission. Existing saved outputs are reusable only with matching effective options and protection/dictionary identity. Default-list edits require restart/deployment; there is no live global dictionary editor.

## Scope and verification

Use the current Settings dialog with a labelled one-term-per-line editor, explicit Save action, errors, loading/saving feedback and a default-list switch. Do not let a failed load overwrite saved settings. Resetting browser appearance does not erase the account dictionary.

Verify syntax false positives, names and boundaries, formatting preservation, dictionary identity, account isolation, migration, job snapshots and retry behavior, and browser save/reload/submission behavior. Replay the reported PowerPoint literals with SMALL-100. Repetition detection is outside this change; literal protection prevents these literals from being translated but is not a general translation-quality detector.
