# Admin authentication routing tests

## Passed

- Frontend full suite: **770 passed** across 68 test files. Focused login, MFA, Admin deep-link/navigation, and Manual Licenses coverage is included.
- Control Center focused backend suite run inside the existing backend container against bind-mounted source: `test_routes_auth_proxy.py`, `test_routes_license_admin_proxy.py`, and `test_core_auth.py` — **57 passed**. Includes valid/error JSON relay, backend unreachable, HTML/non-JSON upstream normalization, cookie behavior, MFA challenge relay, authorization header and idempotency forwarding.
- Auth isolated API tests: `test_manual_license_admin.py` and `test_license_ownership_security.py` — **17 passed**. Confirms the authoritative issuance endpoint denies unauthorized users and enforces owner/tenant boundaries; fixtures use isolated test storage.
- TypeScript build check and Admin Vite production build passed; only Vite's existing large-chunk advisory was emitted.
- Local dummy invalid-credential smoke checks at Auth `:8001`, Control Center `:7070`, current Admin dev `:5185`, and isolated Vite preview `:5186` returned JSON 401, not HTML.
- The local `:5186` preview deep link `/licenses/manual` returned SPA HTML as expected; `/auth/login` returned JSON through both proxy layers.

## Not run / limits

- No valid Admin password was entered. The authoritative password field is disabled/incompatible, and no password reset or identity modification occurred.
- Playwright could not start locally because the installed runtime is Node 18.19.1 while this Playwright version requires Node 20+. Unit tests and HTTP loopback smoke checks were used instead.
- The running Auth image lacks `/platform/licenses/*`; consequently no live policy choices or live Manual Licenses browser session could be verified. The Auth source-level API tests are not evidence that the stale running image has those endpoints.
- No license was issued; no database migrations, Auth restart, production deployment, Cloudflare change, or changes to MacBook settings occurred.
- A broad selected backend run completed 181 passed / 3 failed; all three are pre-existing legacy dashboard assertions. A later all-backend run reached repository tests that recursively launch another full pytest process, producing successive nested pytest children. Only those exact test processes were terminated; Control Center remained healthy. The focused 57-test backend suite is the authoritative result for this workstream.
