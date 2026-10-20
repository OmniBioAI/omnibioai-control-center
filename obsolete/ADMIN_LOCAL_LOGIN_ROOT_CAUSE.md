# Admin local login: diagnosis

## Findings

The Admin client posts JSON `{email, password}` to same-origin `POST /auth/login` (`frontend/cc-ui/src/auth.ts:364-399`). The intended local chain is:

`127.0.0.1:5185` Vite Admin SPA → `127.0.0.1:7070` Control Center → `http://auth-service:8001/auth/login`.

Vite dev proxy was present, but the same proxy table was not configured for `vite preview`. A preview-mode SPA fallback could therefore serve `index.html` for API paths. The active port 5185 process was verified as Vite dev (`VITE_APP_MODE=admin`) and the `/auth/login` request currently traverses correctly. The proxy table is now shared by both dev and preview. This preview gap was real, but it was not the root cause of the observed failure from the active dev server.

The exact message “auth-service returned a non-JSON response” originates in the Control Center Auth relay when Auth's upstream body cannot be parsed as JSON (`backend/src/control_center/api/routes_auth_proxy.py:60-95`). It does not indicate a bad password. A wrong-password response for a synthetic nonexistent identity is JSON 401. That probe returned HTTP 401 / `application/json` at `127.0.0.1:5185`, `:7070`, and directly at Auth `:8001`.

The original failure was reproduced in the local service logs for the legacy identity. Auth found the row, called Passlib verification, and raised `passlib.exc.UnknownHashError: hash could not be identified`. Uvicorn returned a plain non-JSON HTTP 500, and Control Center produced the reported message. The exact root cause is therefore an unsupported/disabled stored password contract, not the submitted password and not an HTML response from Vite.

The correct Control Center backend is running on loopback port 7070 (`/health` returned JSON `{"status":"ok"}`); the local Auth container is reachable by the backend's default Docker-network address, `auth-service:8001`. The login and MFA relay routes are included in `backend/src/control_center/main.py:52-60,246-256`.

Separate local-stack mismatch: Control Center's `/platform/licenses/policy` proxy is present, but the running Auth service's OpenAPI does not include `/platform/licenses/*`; the preview request returned JSON 404. Thus Manual Licenses policy/validity cannot currently load from this running Auth image. This mismatch is not the login non-JSON symptom.

## Local identity and credential boundary

A SELECT-only query through the Auth service ORM found exactly: ID `1`, email `admin@omnibioai`, status `active`, role `admin`. MFA is disabled for this identity. Only non-secret password-field metadata was inspected: the value is present, begins with the standard disabled-password marker, and is not recognized by the configured bcrypt/bcrypt-sha256 Passlib context. The stored value itself was never printed. The actual password was not tested or changed.

Restoring password authentication requires an authorized identity lifecycle change that replaces the disabled value with a supported hash. That is forbidden by this workstream. Stripping the marker or verifying the credential in Control Center would bypass the authoritative Auth service and was not done.

The observed current 5185 service is bound to `127.0.0.1`, and the current local stack reports the Admin app mode. No service on ports 5174, 5175, or 5190 was stopped or restarted. Only Control Center on 7070 was reloaded after its local relay code changed; it returned healthy afterward.
