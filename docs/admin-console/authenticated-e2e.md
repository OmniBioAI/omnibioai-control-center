# Authenticated Admin Console browser certification

This is the standard browser certification mechanism for the Admin Console. It uses Playwright against the deployed UI, submits the existing Admin Console login form, and validates authenticated DOM, sidebar navigation, supported deep links, and hard refresh behavior.

## Prerequisites and execution

From `frontend/cc-ui/`, install dependencies and browser binaries once:

```sh
npm ci
npx playwright install chromium
```

Run a certification with credentials supplied only by the environment:

```sh
ADMIN_E2E_BASE_URL=https://admin.omnibioai.org \
ADMIN_E2E_USERNAME='e2e-admin@example.invalid' \
ADMIN_E2E_PASSWORD='provided-by-secret-manager' \
npm run test:e2e:admin
```

`ADMIN_E2E_TIMEOUT_MS` controls the test timeout (default 30 seconds). Set `ADMIN_E2E_HEADED=1` for a headed run. `ADMIN_E2E_IGNORE_HTTPS_ERRORS=1` is intended only for an explicitly approved non-production environment.

The identity must be an existing dedicated E2E administrator, or a bootstrap administrator used only for read-only certification. Tests do not create users, edit Auth SQL, fabricate JWTs, select tenants, execute workflows, or click mutation controls. Auth has no disposable-user lifecycle wired into this suite; use the deployment's approved secret/identity process and avoid creating persistent users per run.

The setup project stores Playwright's ephemeral session state in `e2e/.auth/admin.json` with mode 0600. It is gitignored and should be removed after a run; the suite never prints it. The Playwright report and failure artifacts are also ignored. Treat traces as local diagnostic material and do not publish them: browser traces can contain page/network context even though this suite does not attach headers, cookies, tokens, or request bodies to its own diagnostics.

## Coverage and CI

The suite covers the authenticated landing page, Health, Regression Health, Deployment Health, Integration Health, Security Posture, Workflow Operations, Audit Explorer, sidebar reachability, supported direct routes, hard refresh, browser Back/Forward history, and anonymous rejection. Audit Explorer coverage is read-only: it checks the live safe-event source, filtering, detail expansion, honest freshness/integrity metadata, deep-link refresh, and the absence of mutation controls. Integration Health asserts source/inventory rendering and a non-zero populated inventory without hard-coding a count. Error-state contracts for 401/403/503 and empty/partial sources remain covered by the existing Vitest page tests, where responses can be controlled safely.

## Current certification

On 2026-08-31 against `https://admin.omnibioai.org`, the authenticated/anonymous suite passed **8/8**. The run used the merged Admin Console frontend, including the Audit Explorer deep-link fix: direct `/audit-explorer`, hard refresh, sidebar navigation, and Workflows ↔ Audit Explorer Back/Forward history all remained stable. Integration Health rendered an available registry source with a populated dynamic inventory. The supporting frontend Vitest suite passed **678/678**, and application/E2E TypeScript checks plus Admin and Control production builds passed.

This is certification of the exercised deployed Admin Console paths and the approved administrator identity only. It is not a claim of non-admin authorization-matrix coverage, artificial tenant/source-failure coverage, or broader ecosystem production certification.

CI needs network access to the configured Admin Console URL, the dedicated secret inputs, and the Chromium Playwright dependency. It should run against a stable deployment fixture and retain failure artifacts privately. This repository's existing CI is backend-focused; this documentation intentionally does not enable a broad CI change.

Known limitations: the current application has supported URL deep links only for the routes exercised here; sidebar-only pages are certified through navigation and refresh. A safe non-admin identity has not been provisioned by this repository, so the authorization matrix currently proves anonymous rejection and authorized-admin access; non-admin-forbidden coverage requires an approved identity lifecycle.
