# ADR-015 - Authentication and Ownership for the Internal Service

Amended by [ADR-020](ADR-020-browser-accounts-and-decoding.md): optional email/password self-registration and password-backed browser sessions are now accepted. API-key clients remain supported.

Status: Accepted 2026-09-29 (P5.0). Amended by [ADR-014](ADR-014-storage-ownership-and-retranslation.md): owner kinds are `human` and `service`, reuse is scoped to the owner's own saved document (the cache side-channel section below no longer applies), and by [ADR-017](ADR-017-web-ui-service-extensions.md) (browser sessions). Ratifies the recommended contract in the [P5 plan](../archive/plans/P5-server-and-service-cli.md#p50-authentication-decision-to-ratify) for the internal pre-GUI release. Browser sessions (P6) and company identity integration extend this user model; they do not replace it.

## Context

Every batch, job and document must belong to an authenticated user (P2-P6 handoff). The first deployment is a laptop or one internal host reached by colleagues, the service CLI, internal applications (ADR-013) and later the web UI. There is no company identity provider integration available to this project yet, and enterprise OAuth is out of scope until P8. ADR-007 accepted a small cross-user signal from the shared exact-byte cache and asked this ADR to weigh it.

## Options Considered

- **Company identity (OIDC/Entra ID) now:** the right long-term answer for browser users, but no tenant registration, redirect host or client secret exists for this laptop service; blocking P5 on it would block the release.
- **Shared service password or network trust:** no per-user ownership, no revocation of one person, and "on the company network" is not an identity.
- **Per-user opaque API keys:** revocable per key, rotation with overlap, works for CLI, raw HTTP clients and internal applications, and gives the web UI a user to attach sessions to. Accepted.
- **Signed tokens (JWT) as API keys:** revocation needs a lookup anyway; opaque keys are simpler and leak nothing.

## Decision

**Users.** `users(id UUID, display_name, kind, active, created_at, disabled_at, issuer, subject)`. `kind` is `person` or `service` (ADR-013 machine clients get their own service identities; acting for a person requires a later explicit delegation contract). `(issuer, subject)` is unique when set and reserved for future identity integration. The display name is never an authorization key. There is no signup; administrators create users.

**Keys.** A key is `dt_<prefix>_<secret>`: `prefix` is 12 random base32 characters used for lookup, `secret` 43 base64url characters (256 random bits from `secrets`). The database stores `api_keys(id, user_id, prefix unique, digest, label, created_at, last_used_at, revoked_at)` where `digest = SHA-256(secret)` hex. Lookup by prefix, then `hmac.compare_digest` on the digest. A plain SHA-256 is sufficient because the secret has 256 bits of entropy (no password hashing needed). Keys are shown once at creation and never stored, logged or printed again. A user may hold several keys (rotation overlap). `last_used_at` is updated at most once a minute per key.

**Transport.** `Authorization: Bearer <key>` on every `/v1` route except `GET /v1/health`. Missing, malformed, unknown, revoked or disabled-user credentials give 401 with the same body and `WWW-Authenticate: Bearer`, before any owned record is read or created. Caller-supplied identity headers are never trusted.

**Administration.** `doctranslator-server users create|list|disable|enable` and `keys create|list|revoke` run locally against the database with the deployment's OS permissions (whoever can read the data directory already holds every document). Normal REST routes have no administrator bypass of ownership.

**Ownership.** The authenticated user's ID is the only owner source. Every repository query for batches, items, jobs, documents, versions, originals and reports filters by `owner_id` in SQL. Absent and other-user resources both return 404 `not_found`. Nested resources (items of a batch, a job's document, a document's report) are reached only through an owned parent. Cache rows (`translation_results`) have no owner and are never exposed by any route; a cache hit creates a new job, document and version 0 owned by the submitter.

**Disabled users.** Disabling commits `active = false`, then requests cancellation of the user's queued and running jobs. Worker completion checks `users.active` inside the fenced publication transaction, so nothing publishes after the disable commits. Stored documents stay until retention and are inaccessible while disabled. Revoking one key does not cancel accepted work.

**Network.** Bind to `127.0.0.1` by default. A non-loopback bind requires TLS configured on the server (certificate and key files issued by the company CA) or an explicit statement that a trusted TLS-terminating reverse proxy is in front (`DOCTRANSLATOR_SERVER_BEHIND_PROXY=true`); the server refuses to start on a non-loopback address otherwise. There is no unauthenticated mode. Clients verify TLS against the OS trust store (truststore), so the company CA works without disabling verification.

**Audit.** `audit_events(id, at, actor_user_id, action, target_type, target_id, outcome)` for user/key administration, authentication failures (by key prefix when parseable, never the secret), submission, cancellation, deletion and job outcomes. Logs and audit rows never contain Bearer headers, secrets, source text or file paths.

**Cache side channel.** Accepted as recorded in ADR-007: a user who submits byte-identical content learns, from an immediately completed job, that someone translated it before with the same options. That user already holds the document; no other user's IDs, names or timing are exposed. A deployment that cannot accept this signal needs a new decision (for example per-user cache keys) before it goes live.

**Browser sessions (P6).** The web UI exchanges a user's API key once for an HttpOnly, Secure (on HTTPS), SameSite=Strict session cookie bound to the same user and revocable server-side, with CSRF protection on state-changing requests. The exact session contract is part of P6.0; it reuses `users` and ownership unchanged.

## Consequences

- Colleagues receive keys through an approved private channel; losing a key means revoking it and issuing another.
- Internal applications get service identities with their own keys and see only their own records.
- Company SSO later maps `(issuer, subject)` to existing users without migrating ownership.
- The service is safe to run on loopback without TLS, and refuses a network bind without TLS.
