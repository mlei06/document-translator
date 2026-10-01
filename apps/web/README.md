# Lenny web client

React/TypeScript port of the preserved Lenny prototype, backed by the authenticated document service. Production serves `dist` from the same origin as `/v1`; no demo API or public analytics are included.

## Develop

From this directory run `npm ci`, then `npm run dev`. Start the Python service separately on loopback port 8765. `DOCTRANSLATOR_DEV_SERVICE` changes the proxy target. The development proxy preserves the browser Host and Origin so the service's same-origin checks continue to apply. Do not use wildcard credentialed CORS.

For production, run `npm run build` and configure `DOCTRANSLATOR_WEB_DIR` with the absolute path to `apps/web/dist`. Users sign in with email and password. Enable account creation explicitly with `DOCTRANSLATOR_REGISTRATION_ENABLED=true`; otherwise the service rejects registration. An optional access-key sign-in remains available for provisioned users. Both methods create the same HttpOnly session; passwords and keys are cleared from the form and never saved in browser storage. Ownership checks remain in the service.

## Checks

```text
npm run gen:api
npm run typecheck
npm run lint
npm run format:check
npm test
npm run build
npx playwright install chromium
npm run e2e
```

`gen:api` runs the Python OpenAPI exporter and openapi-typescript. Never hand-edit `openapi.json` or `src/api/schema.d.ts`.

Playwright runs the built app against an isolated loopback service on port 8876. Its explicit test entry point uses real sessions, database, blobs, worker and core document pipeline with deterministic translators. It creates temporary users/data and is never imported by production startup. Install Python workspace dependencies from the repository root first (`uv sync --all-packages`). Browser tests verify application behavior, not real-model translation quality or full release acceptance. Traces and screenshots go in ignored `test-results`.

The website follows the [unified translator design](../../docs/plans/unified-translator-design.md). Uploads begin as soon as files are selected or dropped. Clicking a target language pins the current batch immediately, including uploads still in flight. Each validated file submits independently using the standard website automatic policy. Later drops start a separate draft. Failed files retain independent Retry, Cancel and Dismiss actions.

There are no source-language, model, decoding, protected-word, force-retranslation or layout controls. Detection is informational. Browser settings only control appearance, behavior and a preferred target shortcut. The service selects the configured automatic ladder; the browser never receives model credentials.

Completed groups offer direct Download. History is private and downloads resolve the currently available shared translation. Eviction or a revoked grant removes availability without triggering inference; the user supplies the original for new work. There are no preview requests or bubble-body navigation. Standard fitting remains internal under Translating.

Implementation decisions, measured contrast and verification are recorded in [website evidence](../../docs/plans/unified-web-evidence.md). Selected acceptance screenshots are retained in `verification/screenshots`.
