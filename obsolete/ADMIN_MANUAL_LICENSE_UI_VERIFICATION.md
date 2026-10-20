# Manual Licenses UI verification

## UI and authorization

- Route `/licenses/manual` maps to `manual-licenses` in `frontend/cc-ui/src/apps/AdminApp.tsx:182-195`; rendering is gated again at `:583-584`.
- Administration → Manual Licenses is registered in `frontend/cc-ui/src/navigation.ts:69-84` and shown only when `hasManualLicenseAccess` allows it. The UI mirror checks stable user ID 1 plus `admin`, or both `platform_admin` and `admin` (`frontend/cc-ui/src/auth.ts:212-220`). Server authorization remains authoritative.
- `ManualLicensesPage` renders Full name, Email, Role, License validity, and organization ID; policy-backed persona/duration options and Generate License state are in `frontend/cc-ui/src/pages/ManualLicensesPage.tsx:60-76`.
- Isolated page tests verify Developer/Application User, 30/90 options from policy, masked historical keys, one-time display, and disabled generation when policy is empty (`frontend/cc-ui/src/pages/ManualLicensesPage.test.tsx`). The full frontend suite passed all 770 tests, including Admin navigation visibility and `/licenses/manual` deep-link coverage.

## Current local-stack result

The Manual Licenses SPA path is reachable, but its policy request is not ready in the currently running stack. `GET /platform/licenses/policy` through the local preview returned JSON 404 because the running Auth service's OpenAPI has no `/platform/licenses/*` paths. As a result, this live instance cannot provide role/validity choices; the page displays a policy-load error and keeps Generate License disabled. The UI must not invent choices or issue a key while policy is unavailable.

The matching Auth source has an authorized policy/issuance API, but refreshing the running Auth service and validating its schema/policy are outside this local login fix. No issuance or API mutation was attempted. Unauthorized behavior is covered by isolated Auth API tests, but could not be exercised against a missing live endpoint.

## Status

Route and UI source/tests: PASS. Live policy/persona rendering and an authorized browser session: BLOCKED on both the disabled Admin password state and the local Auth service version. Browser automation is additionally unavailable under the installed Node runtime. No key was generated.
