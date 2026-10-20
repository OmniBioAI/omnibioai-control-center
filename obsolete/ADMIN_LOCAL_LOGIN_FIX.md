# Admin local login fix

## Changes

1. `frontend/cc-ui/vite.config.ts:16-46,53-59` now defines one local API proxy table and applies it to both Vite `server` and `preview`. This keeps `/auth`, `/platform`, and the other existing API routes on the same-origin path to the local Control Center backend at `http://localhost:7070`; no production hostname or direct browser-to-Auth URL was added.
2. `backend/src/control_center/api/routes_auth_proxy.py:80-95` now converts any non-JSON Auth upstream response to a stable JSON HTTP 502. Previously it kept the upstream status, including a misleading 2xx status that could look like an empty successful login. Valid JSON status/body and Set-Cookie relay behavior remain unchanged.
3. Control Center now exposes a narrow same-origin `POST /auth/mfa/challenge` relay to Auth's `POST /users/me/mfa/challenge`. The Admin SPA recognizes `mfa_required`, holds the challenge token only in component memory, accepts a TOTP/recovery code, and establishes the session only after Auth returns and `/auth/validate` confirms an access token. MFA is not bypassed or disabled.

The 5185 Admin dev process was reused. Preview behavior was separately qualified on temporary loopback port 5186 and shut down afterward. No existing service on 5174, 5175, or 5190 was touched. Control Center on 7070 was reloaded once to register the new route and returned healthy. The Admin SPA production build also passed.

## Operator login steps

The current identity cannot complete password login because its authoritative password field is disabled and unsupported. After an authorized identity owner restores a supported password through the approved Auth lifecycle (outside this restricted workstream), open `http://127.0.0.1:5185/`, enter `admin@omnibioai` and that authorized credential, then enter the current MFA code if Auth requests it. The target route is `http://127.0.0.1:5185/licenses/manual`. Do not paste access tokens or cookies into the browser.

For a Mac on the same LAN as this DGX (`spark-c275`, observed address `192.168.86.28`), run:

```sh
ssh -N -L 5185:127.0.0.1:5185 manish@192.168.86.28
```

Then open `http://127.0.0.1:5185/licenses/manual` on the Mac. This creates only an SSH port forward; it does not expose or reconfigure the preview service.

## Remaining dependency

Two dependencies remain. First, the legacy Admin identity needs an authorized credential lifecycle operation; no password or identity change was performed here. Second, the running Auth image is older than the current manual-license source: `/platform/licenses/policy` is absent from its OpenAPI, and the local request returns JSON 404. Do not work around either issue with hard-coded validity options or weakened authorization. No Auth container restart, migration, or database write was performed here.
