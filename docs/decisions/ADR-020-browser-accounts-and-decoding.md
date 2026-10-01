# ADR-020 - Browser Accounts and Translation Presets

Status: Accepted by owner, 2026-09-29. The current explicit request supersedes the access-key-only browser sign-in and no-self-registration restrictions in ADR-015, ADR-017 and the P6 plan. Existing owner-scoped storage and API-key clients remain unchanged.

## Decision

Website amendment: [ADR-027](ADR-027-automatic-website-translation.md) removes translator/decoding controls in the upcoming automatic website flow. Account/session decisions below remain unchanged. Routing implementation is pending.

- Add basic email/password registration and sign-in for human users. The owner-set minimum password length is 8 characters (maximum 128). Normalize email for unique lookup; keep stable user IDs as the sole ownership identity. Do not merge an existing account based on a claimed email.
- Store only salted, memory-hard password hashes. Passwords never appear in responses, logs or browser persistent storage. Registration is enabled explicitly by the deployment; this local website enables it.
- Reuse the existing opaque, HttpOnly, SameSite browser sessions, CSRF/origin checks, expiry and user-disable behavior. Password sessions have no API-key dependency; key-backed sessions still honor key revocation. Keep API-key authentication for service accounts, CLI and existing clients.
- Bound authentication attempts and password-hashing concurrency. Return generic invalid-credential responses. Email verification, password recovery, SSO and public Internet deployment are outside this basic internal/local account flow; entering an email does not prove ownership of that mailbox.
- The requested running configuration supports SMALL-100 locally and the existing internal Gemma endpoint. Offer SMALL-100 Beam 4 and Greedy as configured translator presets with beam_size 4 and 1 respectively. Reuse ADR-019 translator IDs and fingerprints rather than accepting arbitrary inference parameters from the browser. Per ADR-019's runtime-reuse amendment, these presets share one loaded SMALL-100 runtime per worker and pass their decoding settings per inference call.
- Clicking Lenny exposes translator settings: choose SMALL-100 or Gemma, and choose Beam 4 or Greedy when SMALL-100 is selected. Selection applies to subsequent submissions, not already accepted jobs. Existing targets, downloads, fit-skip and owner-scoped reuse remain intact.
- Model bundles, endpoint credentials and the local service configuration stay outside version control. Bind this runnable development website to loopback; shared deployment still requires TLS.

## Verification

Exercise registration, duplicate/invalid email, wrong password, sign-in, reload, sign-out, disabled users, session isolation, and migration of existing key sessions. Browser acceptance must create a real account, select both SMALL-100 decoding choices through Lenny, and show real service translator IDs. Run real model smoke translations and report endpoint availability honestly.
