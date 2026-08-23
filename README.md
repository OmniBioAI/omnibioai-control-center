# OmniBioAI Control Center

> README last reviewed: **2026-08-23**

**Operational health dashboard, ecosystem report server, and observability hub for the OmniBioAI stack.**

The Control Center is a FastAPI service that aggregates health status across all OmniBioAI components, serves an interactive ecosystem report, exposes Prometheus metrics, and auto-generates reports on a configurable schedule.

---

## What It Does

- **Health monitoring** — TCP, HTTP, and disk checks across all ecosystem services
- **Enterprise Admin Console** — a separate frontend build served at `admin.omnibioai.org`: Organizations, Users, Teams, Roles & Permissions, MFA Policy, IAM/SSO Management, Audit Logs, API Keys/Service Accounts, Billing, Workflows, Tool Execution, AI Models, RAG/PubMed, Settings — see [Admin Console](#admin-console) below
- **Ecosystem report** — interactive HTML report (architecture · projects · languages · coverage · health) served at `/`; `/dashboard` redirects here (its live per-service cards and generate button were folded into the report's header status chip and Admin tab)
- **JSON API** — machine-readable health summary at `/summary` for CI/CD and external monitoring
- **Scheduled report generation** — auto-regenerates the ecosystem report every N hours (configurable via REPORT_SCHEDULE_HOURS)
- **Admin controls** — an Admin tab in the report for triggering report/coverage regeneration, pausing/rescheduling the 7 host cron jobs, and tracking known issues; every write action is JWT-role-gated (`admin` role required), enforced both by nginx and independently by the app itself
- **Prometheus metrics** — `/metrics` endpoint scraped by Prometheus for Grafana dashboards
- **Docker inventory** — platform containers, tool SIF images, and plugin Docker images via `/docker/*` endpoints
- **Structured JSON logging** — all key events logged as JSON to stdout for log aggregation
- **LLM monitoring** — local Ollama models and API key status via `/llms`
- **Reference genome registry** — 12 organisms, indexes, variants via `/reference`
- **AI Knowledge Base** — 28M+ PubMed abstracts, FAISS indexes via `/knowledge-base`
- **Storage monitoring** — disk usage, per-organism reference indexes via `/storage`
- **Cloud backends** — execution backend status via `/cloud`

## Architecture

![Architecture](images/OmniBioAI_ecosystem_architecture_diagram.png)
---

## Authentication

Control Center delegates all authentication to `omnibioai-auth`; it never
verifies a password or issues a token itself. It plays two distinct roles:

1. **Same-origin proxy for the browser** — `routes_auth_proxy.py` relays
   `/auth/login`, `/auth/refresh`, `/auth/logout`, and `/auth/validate`
   straight through to auth-service, existing purely because
   `control.omnibioai.org`'s ingress reaches this service directly,
   bypassing the nginx router that fronts every other domain's `/auth/*`
   path.
2. **Local verifier for its own admin-gated endpoints** — `require_admin`
   (`core/auth.py`) independently checks every write endpoint's bearer
   token, rather than trusting the proxy hop above.

### Login

The Admin tab's login form (or the omnibioai-studio SPA sharing the same
origin) `POST`s credentials through this service's `/auth/login` proxy.
auth-service authenticates and returns an `access_token` in the JSON body
*and* sets the `omnibioai_session` cookie on the response — the proxy
relays that `Set-Cookie` back to the browser rather than dropping it.

### Browser session

The frontend (`frontend/cc-ui/src/auth.ts`) keeps only the short-lived
**access token** client-side, in `localStorage` (`omnibioai_access_token`)
— attached as `Authorization: Bearer <token>` on every gated request. It
never reads, stores, or forwards the refresh token: that lives solely in
the `HttpOnly` `omnibioai_session` cookie the browser attaches
automatically to same-origin requests, invisible to page JavaScript.

### Refresh flow

The frontend decodes the access token's own `exp` claim (no signature
check needed — it's opaque either way until the server re-validates it)
and schedules a silent refresh ~60 seconds before it expires. That refresh
call sends an **empty body** to `/auth/refresh` — the browser's
`omnibioai_session` cookie is what actually authorizes the rotation; the
proxy relays the incoming `Cookie` header upstream and the rotated
`Set-Cookie` back downstream. A failed refresh (missing/expired/revoked
session) forces a return to the login screen; a network-level failure
fails open and simply lets the current access token run out naturally.

### Logout

`POST /auth/logout` (via the proxy) sends only the access token in the
body — the refresh token is never available to send, since it's cookie-only.
The proxy fills in `refresh_token` server-side from the
`omnibioai_session` cookie before forwarding to auth-service, which
revokes it, blacklists the access token's `jti`, and clears the cookie;
the frontend clears its own `localStorage` entry regardless of whether the
network call itself succeeded.

### Admin authorization

`require_admin` (`core/auth.py`) gates every write endpoint (see the
"Admin-gated" markers in [API Endpoints](#api-endpoints)):

```
verify token
      │
      ▼
check roles
      │
      ▼
allow / deny
```

It parses the `Authorization` header, delegates signature/expiry/type/
claim/revocation verification to `core/jwt_verify.py`, and then makes its
own decision: 401 if the token itself is invalid, 403 if it's valid but
lacks the `admin` role. This runs independently of nginx's own
`auth_request` check in front of `/_svc/control` — so a misconfigured
nginx rule alone can never expose a write endpoint, since this service
checks the specific role itself either way.

### JWT verification

`core/jwt_verify.py` is this service's own local copy of the shared
verification logic (structurally identical to
[omnibioai-security-audit](../omnibioai-security-audit)'s) — it does not
call back into auth-service on every request. It checks signature,
expiry, token type (rejects a presented refresh token), the required
`sub` claim, and Redis jti-blacklist revocation, dispatched by each
token's own `alg` header (see RS256 readiness below).

### Redis revocation

The same jti-blacklist auth-service writes to on logout
(`blacklist:jti:{jti}`) is checked here directly against the same Redis
instance — **fail-open** on a Redis error, matching auth-service's own
documented tradeoff: a Redis blip must not 401 every admin request in
this service either.

### RS256 readiness

`core/jwt_verify.py` verifies both HS256 (today's production default) and
RS256 (auth-service's `/.well-known/jwks.json`, once
`JWT_ALGORITHM=RS256` is enabled there), dispatched by each token's own
`alg` header — never by local configuration. An RS256 token's `kid` is
resolved against a cached, auto-refreshing JWKS client; any signature or
JWKS-fetch failure fails closed. No production deployment has switched
issuance to RS256 yet — see [omnibioai-auth's README](../omnibioai-auth#jwt)
and the ecosystem root README's Deployment Notes.

### Authentication sequence

```
Browser
   │
   ▼
Control Center            (routes_auth_proxy.py — same-origin relay)
   │
   ▼
Auth Service               (omnibioai-auth — authenticates, issues tokens)
   │
   ▼
JWT                        access_token in JSON body (Authorization: Bearer, 15 min)
   │
   ▼
Refresh Cookie              omnibioai_session (HttpOnly, Secure, SameSite=Lax) —
                             relayed browser ↔ Control Center ↔ Auth Service,
                             drives the silent-refresh flow above
```

---

## Repository Structure

```text
omnibioai-control-center/
│
├── scripts/
│   └── generate_report.py          # Ecosystem report generator (CLI)
│
├── backend/
│   ├── pyproject.toml              # Package definition and dependencies
│   ├── src/control_center/
│   │   ├── main.py                 # FastAPI app — registers all routers
│   │   ├── api/
│   │   │   ├── routes_health.py    # GET /health
│   │   │   ├── routes_services.py  # GET /services
│   │   │   ├── routes_summary.py   # GET /summary
│   │   │   ├── routes_report.py    # GET /report, /report/generate, /report/status, /report/data
│   │   │   ├── routes_config.py    # GET /config, POST /config/service
│   │   │   ├── routes_cron.py      # /cron/jobs + pause/resume/schedule
│   │   │   ├── routes_docker.py    # /docker/*
│   │   │   ├── routes_known_issues.py  # /known-issues CRUD
│   │   │   ├── routes_llm.py       # GET /llms, /knowledge-base
│   │   │   ├── routes_cloud.py     # GET /cloud
│   │   │   ├── routes_reference.py # GET /reference
│   │   │   ├── routes_storage.py   # GET /storage
│   │   │   ├── routes_infra.py     # GET /gpu, /celery, /database, /license, /usage,
│   │   │   │                       # /gateway-traffic, /audit-trail, /activity,
│   │   │   │                       # /image-freshness, /integrity
│   │   │   ├── routes_dashboard.py # GET /dashboard/summary (Overview page stat cards)
│   │   │   ├── routes_auth_proxy.py    # /auth/login, /auth/refresh, /auth/logout, /auth/validate
│   │   │   │                           # — same-origin relay to auth-service
│   │   │   └── routes_{org,user,role,team,service_accounts,org_sso,org_mfa,audit,
│   │   │       billing,tes,model_registry,workflow_bundles,rag,platform_config}_proxy.py
│   │   │                           # Admin Console enterprise proxy layer (15 files) —
│   │   │                           # see "Admin Console" below
│   │   ├── checks/
│   │   │   ├── http.py / tcp.py / disk.py          # Core checks — HTTP, TCP (MySQL/Redis), disk
│   │   │   ├── cron_jobs.py        # Host-crontab status + pause/resume/reschedule logic
│   │   │   ├── known_issues.py     # Known-issue store (known_issues.json)
│   │   │   └── gpu.py / celery_status.py / database_status.py / license_status.py /
│   │   │       usage_status.py / audit_trail.py / gateway_traffic.py /
│   │   │       image_freshness.py / integrity.py / activity.py
│   │   │                           # Infra/observability checks backing routes_infra.py
│   │   ├── core/
│   │   │   ├── runner.py           # Dispatches checks per service type
│   │   │   ├── settings.py         # Loads control_center.yaml
│   │   │   ├── auth.py             # require_admin — JWT role gate for write endpoints
│   │   │   └── jwt_verify.py       # Local JWT verification (HS256 + RS256/JWKS)
│   │   ├── notifications/
│   │   │   └── discord.py          # Discord webhook alerts (known issues, GPU temp)
│   │   └── utils/
│   │       └── summary_client.py   # Fetches /summary for report generation
│   └── tests/                      # 1,394 collected tests at last review — see "Running Tests" below
│
├── frontend/cc-ui/src/
│   ├── apps/
│   │   ├── ControlApp.tsx          # Ops console root — built when VITE_APP_MODE=control
│   │   ├── AdminApp.tsx            # Admin Console root — built when VITE_APP_MODE=admin
│   │   └── AuthGate.tsx            # Shared login/session state machine (both apps)
│   ├── navigation.ts               # Single source of truth for Admin Console's sectioned nav
│   └── pages/, components/         # Page and component implementations
│
├── compose/
│   └── docker-compose.control-center.yml
├── config/
│   ├── control_center.yaml         # Active configuration
│   └── control_center.example.yaml # Reference configuration
└── docker/
    ├── Dockerfile
    └── nginx/
        ├── control-center.conf     # Host-based split: control.omnibioai.org / admin.omnibioai.org
        └── api-proxy.conf          # Shared API proxy rules, included by both server blocks
```

---

## API Endpoints

| Endpoint               | Method | Description |
|------------------------|--------|-------------|
| `/`                    | GET    | Ecosystem report (auto-refreshes) |
| `/dashboard`           | GET    | Redirects to `/` (retired — see Admin tab) |
| `/health`              | GET    | Control Center self-check |
| `/services`            | GET    | Per-service health status (JSON) |
| `/summary`             | GET    | Full ecosystem summary — services + disk (JSON) |
| `/report`              | GET    | Redirects to `/` (serves report with live header) |
| `/report/generate`     | POST   | **Admin-gated.** Trigger background report generation |
| `/report/status`       | GET    | Poll report job state (running/done/error/idle) |
| `/report/data`         | GET    | Structured report data as JSON |
| `/coverage/generate`   | POST   | **Admin-gated.** Trigger coverage collection, scoped to control-center itself (see Design Principles) |
| `/coverage/status`     | GET    | Poll coverage job state |
| `/config`              | GET    | Raw `control_center.yaml` contents (plain text) |
| `/config/service`      | POST   | Append a new monitored service to the config |
| `/cron/jobs`           | GET    | Status of the 7 known host-crontab jobs |
| `/cron/jobs/{id}/pause`    | POST | **Admin-gated.** Pause one of the 7 known jobs (whitelist-only) |
| `/cron/jobs/{id}/resume`   | POST | **Admin-gated.** Resume a paused job |
| `/cron/jobs/{id}/schedule` | PUT  | **Admin-gated.** Reschedule a job in the real crontab |
| `/known-issues`        | GET    | List tracked known issues |
| `/known-issues`        | POST   | **Admin-gated.** Create a known issue |
| `/known-issues/{id}`   | PUT    | **Admin-gated.** Update a known issue |
| `/known-issues/{id}`   | DELETE | **Admin-gated.** Delete a known issue |
| `/docker/containers`   | GET    | Platform container list with status |
| `/docker/sif-images`   | GET    | Tool SIF image inventory and sizes |
| `/docker/plugin-images`| GET    | Plugin Docker image inventory |
| `/metrics`             | GET    | Prometheus metrics endpoint |
| `/llms`                | GET    | Local LLM models + API key status |
| `/cloud`               | GET    | Cloud/HPC execution backend status |
| `/reference`           | GET    | Reference genome registry (12 organisms) |
| `/knowledge-base`      | GET    | AI knowledge base stats (PubMed + FAISS) |
| `/storage`             | GET    | Disk usage + per-organism index sizes |
| `/dashboard/summary`   | GET    | Overview page stat cards (both Admin Console and ops console) |
| `/gpu`                 | GET    | GPU temperature/utilization via `nvidia-smi` |
| `/celery`              | GET    | Celery worker + recent task-queue status |
| `/database`            | GET    | MySQL/Redis/Neo4j data-layer connectivity |
| `/license`             | GET    | Seat usage and license expiry status |
| `/usage`               | GET    | Product usage — active users, run counts |
| `/gateway-traffic`     | GET    | API Gateway request/route traffic (7-day window) |
| `/audit-trail`         | GET    | Auth/policy/HPC audit log stream (7-day window) |
| `/activity`            | GET    | Live CPU/memory/network via Prometheus + cAdvisor |
| `/image-freshness`     | GET    | Deployed image digests vs. latest on GHCR |
| `/integrity`           | GET    | Configured symlink/mount integrity checks |

"Admin-gated" endpoints require a valid JWT carrying the `admin` role, checked twice independently: once by nginx's `auth_request` (any valid JWT) and once inside the app itself via `require_admin` (the specific role) — so an nginx misconfiguration alone can't expose a write endpoint. All other endpoints above are fully open, no auth required.

This table covers the original ops-console surface. A separate, larger set of `/orgs/*`, `/platform/*`, `/billing/*`, `/tes/*`, `/model-registry/*`, `/workflow-bundles/*`, `/rag/*`, and `/auth/config` proxy routes backs the Admin Console — see [Admin Console → Enterprise proxy routes](#enterprise-proxy-routes) below rather than duplicating all ~35 of them here; each is gated by whatever permission its owning service already requires (`omnibioai-auth`'s `manage_all_orgs`/org-membership checks, `omnibioai-billing`'s org-scoped IAM, etc.) — Control Center's own `require_admin`/nginx layer above doesn't apply to them.

### `/health`

```json
{ "status": "ok" }
```

### `/summary`

```json
{
  "overall_status": "UP",
  "generated_at": "2026-03-20T02:44:00+00:00",
  "services": [
    {
      "name": "omnibioai",
      "type": "http",
      "target": "http://omnibioai:8000/",
      "status": "UP",
      "latency_ms": 12,
      "message": "HTTP 200"
    },
    {
      "name": "mysql",
      "type": "mysql",
      "target": "mysql:3306",
      "status": "UP",
      "latency_ms": 3,
      "message": "TCP connect ok"
    }
  ],
  "system": {
    "disk": [
      {
        "name": "disk:/workspace/out",
        "type": "disk",
        "target": "/workspace/out",
        "status": "UP",
        "latency_ms": null,
        "message": "45.2% free"
      }
    ]
  }
}
```

Status values: `UP` | `DOWN` | `WARN`

---

## Configuration

All monitored services and disk paths are defined in `config/control_center.yaml`.

```yaml
services:
  mysql:
    type: mysql
    host: mysql
    port: 3306

  redis:
    type: redis
    host: redis
    port: 6379

  toolserver:
    type: http
    url: http://toolserver:9090/health
    timeout_s: 2

  tes:
    type: http
    url: http://tes:8081/health
    timeout_s: 2

  omnibioai:
    type: http
    url: http://omnibioai:8000/
    timeout_s: 2

  lims-x:
    type: http
    url: http://lims-x:7000/
    timeout_s: 2

  model-registry:
    type: http
    url: http://model-registry:8095/health
    timeout_s: 2

system:
  disk_checks:
    - path: /workspace/out
      warn_pct_free_below: 15
    - path: /workspace/tmpdata
      warn_pct_free_below: 10
    - path: /workspace/local_registry
      warn_pct_free_below: 10
```

### Supported check types

| Type | Required fields | Description |
|------|----------------|-------------|
| `http` | `url`, `timeout_s` | HTTP GET — UP if 2xx, WARN if 3xx/4xx/5xx |
| `mysql` | `host`, `port` | TCP connect to MySQL port |
| `redis` | `host`, `port` | TCP connect to Redis port |

### Adding a new service

Add a block to `config/control_center.yaml` and restart the container:

```yaml
services:
  my-new-service:
    type: http
    url: http://my-service:8080/health
    timeout_s: 2
```

No code changes required.

---

## Running

### Via Docker (repository-local)

The repository root `Dockerfile` builds both frontend bundles and the FastAPI
service. Build and run it directly from this checkout:

```bash
docker build -t omnibioai-control-center -f Dockerfile .
docker run --rm -p 7070:7070 \
  -e CONTROL_CENTER_CONFIG=/workspace/config/control_center.yaml \
  -e WORKSPACE_ROOT=/workspace \
  -v "$PWD:/workspace" \
  omnibioai-control-center
```

The checked-in `compose/docker-compose.control-center.yml` is an ecosystem
deployment template and currently references an external `deploy/control-center`
build context; do not use it as a standalone command from this checkout until
that deployment layout is present.

Access the direct development service at `http://127.0.0.1:7070`. In the full
ecosystem deployment, nginx exposes the service at `/_svc/control`; read-only
endpoints are public there, while other endpoints require JWT authentication
and write endpoints additionally require the `admin` role.

### Standalone (development)

```bash
cd backend
pip install -e ".[dev]"

CONTROL_CENTER_CONFIG=../config/control_center.yaml \
WORKSPACE_ROOT=~/Desktop/machine \
uvicorn control_center.main:app --host 0.0.0.0 --port 7070 --reload
```

### Environment variables

| Variable                | Default                       | Description |
|-------------------------|-------------------------------|-------------|
| `CONTROL_CENTER_CONFIG` | `/config/control_center.yaml` | Path to YAML config |
| `WORKSPACE_ROOT`        | `/workspace`                  | Ecosystem root as seen inside the container or local process |
| `CONTROL_CENTER_PORT`   | `7070`                        | Service port |
| `REPORT_SCHEDULE_HOURS` | `6`                           | Auto-regenerate report every N hours |
| `WORK_DIR`              | `/workspace/omnibioai-work`   | Work/output directory; use a path valid for the selected local or container deployment |
| `JWT_SECRET`            | `change-me`                   | Shared HS256 secret for validating admin JWTs locally (`require_admin`) — same value as `AUTH_SECRET_KEY` used by omnibioai-auth/workbench/api-gateway/model-registry |
| `JWKS_URL`               | `https://auth.omnibioai.org/.well-known/jwks.json` | RS256 verification (not yet enabled in production) — see [Authentication](#authentication) |
| `JWKS_TIMEOUT_SECONDS` / `JWKS_CACHE_TTL_SECONDS` | `5` / `300`  | JWKS fetch timeout and key-set cache lifetime |
| `CRONTAB_SPOOL_PATH`    | `/var/spool/cron/crontabs/manish` | Host crontab spool file, bind-mounted in so `/cron/jobs/{id}/pause\|resume\|schedule` can read/write it directly |
| `DISCORD_ALERT_WEBHOOK_URL` | *(empty)*                 | Discord webhook for new high-severity known-issue alerts — empty disables alerting gracefully, same pattern as `SENTRY_DSN` |

---

## Ecosystem Report

The report is a single interactive HTML file with a left sidebar-nav layout (not flat tabs) — top-level groups, some of which expand into sub-tabs:

| Group | Sub-tab | Contents |
|-------|---------|----------|
| Architecture | — | SVG lane diagram of all services |
| Projects | Code Summary | Code line distribution across repositories |
| | Languages | Language breakdown across the ecosystem |
| | Code Coverage | Per-repo pytest coverage with progress bars |
| Ecosystem Status | — | Per-repo git working-tree status (branch, clean/dirty, modified/untracked/unpushed) across every repo under the ecosystem root — same scan as `bash omnibioai-utils/ecosystem_status.sh`. Also surfaced as its own tab on the Admin Console's Ecosystem Report page (`EcosystemPage.tsx`), both reading the same `gitStatus` array from `/report/data` |
| Health Status | Overview | KPI summary + status donut + per-service latency bars |
| | Services | Live per-service health cards |
| | Disk & Mounts | Disk usage checks + symlink/mount integrity |
| | GPU | `nvidia-smi` temperature/utilization panel |
| | Activity | Live CPU/memory/network via Prometheus + cAdvisor |
| | Audit Trail | Auth/policy/HPC audit log stream |
| | Errors | Aggregated Sentry error counts |
| Usage | Product Usage | Active users, run counts (30-day window) |
| | API Gateway | Gateway request/route traffic (7-day window) |
| LLMs & Cloud | LLMs | Local Ollama models + API key configuration |
| | Cloud | Cloud/HPC execution backend status |
| | Cost Tracking | Placeholder — not yet implemented |
| Reference Data | — | 12 organism genomes, indexes, variant databases |
| AI Knowledge Base | — | 28M+ PubMed abstracts, FAISS index stats |
| Model Registry | — | Registered model versions, real vs. synthetic data classification |
| Docker Images | Platform Containers | Running/stopped platform container inventory |
| | Tool SIF Images | Singularity image build status and sizes |
| | Plugin Docker Images | Plugin image inventory vs. local Docker images |
| Miscellaneous | Active Runs | Currently running/queued workflow runs |
| | Storage | Disk usage bar, data categories, organism indexes |
| | Catalog | Plugin/tool/workflow-bundle counts and breakdowns |
| | Data Layer | MySQL/Redis/Neo4j connectivity status |
| | Task Queue | Celery worker + recent task status |
| | License | Seat usage and license expiry |
| | Secrets Audit | Compose file scan for exposed secrets |
| | Image Freshness | Deployed image digests vs. latest on GHCR |
| | Exposed Ports | Compose file scan for host-exposed ports |
| | CI/CD Health | GitHub Actions status + dependency vulnerability scan per repo (npm audit requires Node in the runtime image — see Requirements) |
| | CVE Trend | Vulnerability count history over time, charted |
| | Backup Status | Backup job recency and status |
| Admin | Actions | Regenerate report / refresh coverage — admin-gated, hidden behind a login form for everyone else |
| | Scheduled Jobs | Status of the 7 host cron jobs; pause/resume/reschedule for admins, read-only otherwise |
| | Known Issues | Tracked open/acknowledged/resolved issues — live CRUD for admins (moved here from Miscellaneous), read-only otherwise. Creating a **high**-severity entry fires a Discord alert (see below); medium/low never do |

### Admin access

See [Authentication](#authentication) above for the full login/refresh/logout
flow. In short: when embedded as an iframe under omnibioai-studio's web
build (same origin, `/_svc/control`), the Admin tab reads the same
`omnibioai_access_token` `localStorage` entry Studio already wrote, so an
existing Studio login is recognized automatically with no separate
sign-in. If no token is present, the tab shows a login form that posts
directly to `/auth/login`; if a token is present but lacks the `admin`
role, the tab renders everything read-only with an explicit "admin access
required" message instead of showing controls that would just fail. The
scheduled silent refresh (see Authentication) keeps the session alive
across the 15-minute access-token TTL; only an unrecoverable 401 (refresh
itself failed) clears the stored token and re-prompts for login.

### Known-issue Discord alerts

Every genuinely new **high**-severity known issue (create only — never on updates, and never for medium/low, to keep this high-signal) posts a Discord embed via `DISCORD_ALERT_WEBHOOK_URL` (a separate webhook from `DISCORD_WEBHOOK_URL`, which is used for GPU temperature alerts). This fires on the same code path regardless of whether the entry was created by a human via the Admin tab or automatically by one of the host cron self-check scripts (`check_cron_health.py`, `check_disk_space.py`, `check_domain_health.py`) — closing the loop between "the system detected a problem" and "a human finds out." Unset/unreachable webhook, or any error in sending the alert, never blocks the actual known-issue from being recorded — the alert is fire-and-forget.

### Generate

```bash
# From the ecosystem root — with live health data
python omnibioai-control-center/scripts/generate_report.py \
    --root ~/Desktop/machine

# Skip health check (faster, offline)
python omnibioai-control-center/scripts/generate_report.py \
    --root ~/Desktop/machine \
    --skip-health

# Skip coverage collection (code stats only, very fast)
python omnibioai-control-center/scripts/generate_report.py \
    --root ~/Desktop/machine \
    --skip-coverage

# All options
python omnibioai-control-center/scripts/generate_report.py \
    --root ~/Desktop/machine \
    --control-center-url http://127.0.0.1:7070 \
    --out out/reports/omnibioai_ecosystem_report.html \
    --title "OmniBioAI Ecosystem Report"
```

### Requirements

```bash
# cloc for code counting
sudo apt-get install cloc        # Ubuntu/Debian
conda install -c conda-forge cloc  # Conda

# Python dependencies
pip install pandas

# For coverage collection (best-effort)
pip install pytest pytest-cov

# For npm-audit vulnerability scanning of JS-manifest repos
# (already installed in the backend Docker image; only needed if running
# the report generator standalone outside the container)
sudo apt-get install nodejs npm  # Ubuntu/Debian — pins whatever major
                                  # version your distro repo ships; the
                                  # Docker image pins Node 20 explicitly
```

### View

- **File:** `~/Desktop/machine/out/reports/omnibioai_ecosystem_report.html`
- **Browser:** Open directly — no server needed
- **Live:** `http://localhost/_svc/control` when Control Center is running

The report generates gracefully even if the Control Center is offline or coverage collection fails — those tabs show a clear unavailable state rather than breaking the whole report.

---

## Admin Console

**One repository, two frontend builds, two domains.** `control.omnibioai.org`
serves the ops console described above (Health, Docker, Ecosystem Report,
Config, LLMs, Cloud — no enterprise administration UI at all, not hidden,
genuinely absent from that build's JavaScript). `admin.omnibioai.org` serves
a separate enterprise administration SPA covering Organizations, Users,
Teams, Roles & Permissions, Security (MFA Policy, IAM/SSO Management, Audit
Logs, API Keys/Service Accounts), Billing, Workflows, Tool Execution, AI
Models, RAG/PubMed, and platform Settings.

Same repository, same FastAPI backend, same auth system, same permission
checks either way — the domain only decides which pre-built frontend
bundle nginx serves. **The build split is a deployment/UX optimization,
never an authorization boundary**: every `require_permission`/
`require_admin` check and every org-membership check in `omnibioai-auth`
is unchanged regardless of which domain a request came from, and nothing
about the serving hostname is itself authenticated. Full design record:
`docs/admin-console-build.md`.

### Build

`src/main.tsx` picks a root component at build time from `VITE_APP_MODE`:

```
VITE_APP_MODE=admin   npm run build:admin    → src/apps/AdminApp.tsx   → dist-admin/
VITE_APP_MODE=control npm run build:control  → src/apps/ControlApp.tsx → dist-control/
```

`AdminApp.tsx` is the original, full-featured app; `ControlApp.tsx` imports
only the six ops pages and has no reference anywhere to
`OrganizationsPage`, `UsersPage`, or any `components/organizations`/
`components/roles`/`components/teams` code. Vite/Rollup constant-folds and
tree-shakes the unused branch at build time (verified against real output
— `dist-control`'s bundle is ~45KB smaller, and the losing app's strings
don't appear in it at all), so this is a genuinely smaller bundle, not
hidden-but-shipped UI. Both apps share `AuthGate.tsx` (session/login state
machine) and `Header.tsx`.

### Navigation (25 functional pages)

Single source of truth: `frontend/cc-ui/src/navigation.ts`.

| Section | Page(s) | Notes |
|---|---|---|
| — | Overview | Stat cards via `/dashboard/summary` |
| Administration | Organizations, Users, Teams, Roles & Permissions | |
| Operations | Infrastructure (Health, Docker, Ecosystem Report, Config, LLMs, Cloud) | The 6 pre-existing ops pages, grouped under one expandable parent |
| | Workflows, Tool Execution, AI Models | Proxy `omnibioai-workflow-bundles`, `omnibioai-tes`, `omnibioai-model-registry` directly — authorization is entirely each upstream service's own, per-request |
| Security | Security Overview, MFA Policy, IAM/SSO Management, Audit Logs, API Keys/Service Accounts | |
| | Sessions | **Placeholder (`functional: false`)** — no session-list/revoke backend exists yet |
| Business | Billing | Proxies `omnibioai-billing`'s existing read APIs |
| Knowledge | RAG, PubMed | Both point at one page — RAG's only indexed corpus today is PubMed abstracts |
| Platform | Settings | Read-only view of `omnibioai-auth`'s `GET /auth/config`; the corresponding `PUT` (platform-wide LLM/cloud credentials) is deliberately not proxied yet |
| | Integrations | **Placeholder (`functional: false`)** — no integration/CRUD entity exists yet |

Placeholder items still appear in the nav (rendered as "Coming Soon," per
this app's own convention — never hidden) rather than being removed.
Every `functional: true` page is wired to a real backend; none renders a
`<ComingSoon/>` fallthrough while claiming to be functional (re-verified
in `docs/pr-e-admin-console-production-hardening.md`).

### Enterprise proxy routes

Every Admin Console page is backed by a thin `routes_*_proxy.py` layer —
Control Center holds no organization/user/role/billing data of its own,
it forwards to the service that owns it:

| Router | Example paths | Proxies to (env var) |
|---|---|---|
| `routes_org_proxy.py` | `/orgs`, `/orgs/{id}`, `/orgs/{id}/members`, `/platform/orgs` | `IAM_URL` → auth-service |
| `routes_user_proxy.py` | `/platform/users`, `/platform/users/{id}`, `/platform/users/{id}/mfa/reset` | `IAM_URL` → auth-service |
| `routes_role_proxy.py` | `/platform/roles`, `/orgs/{id}/roles`, `/organizations/{id}/permissions` | `IAM_URL` → auth-service |
| `routes_team_proxy.py` | `/orgs/{id}/teams`, `/orgs/{id}/teams/{id}/members` | `IAM_URL` → auth-service |
| `routes_service_accounts_proxy.py` | `/orgs/{id}/api-keys`, `/orgs/{id}/oauth-clients`, `/platform/permissions` | `IAM_URL` → auth-service |
| `routes_org_sso_proxy.py` | `/orgs/{id}/sso`, `/orgs/{id}/sso/override` | `IAM_URL` → auth-service |
| `routes_org_mfa_proxy.py` | `/orgs/{id}/mfa-policy`, `/orgs/{id}/mfa-policy/override` | `IAM_URL` → auth-service |
| `routes_audit_proxy.py` | `/platform/audit-events` | `IAM_URL` → auth-service |
| `routes_platform_config_proxy.py` | `/auth/config` (read-only) | `IAM_URL` → auth-service |
| `routes_billing_proxy.py` | `/billing/organizations/{id}/usage`, `/summary`, `/invoices`, `/cost-breakdown`, `/subscription` | `BILLING_URL` → billing-service |
| `routes_tes_proxy.py` | `/tes/tools`, `/tes/tools/capabilities`, `/tes/runs` | `TES_URL` → tes |
| `routes_model_registry_proxy.py` | `/model-registry/models`, `/health`, `/auth-status` | `MODEL_REGISTRY_URL` → model-registry |
| `routes_workflow_bundles_proxy.py` | `/workflow-bundles/workflows`, `/categories`, `/runs` | `WORKFLOW_BUNDLES_URL` → workflow-bundles |
| `routes_rag_proxy.py` | `/rag/studies`, `/rag/cache-stats`, `/rag/health` | `RAG_URL` → rag |

Auth forwarding, a uniform 10s timeout, and error mapping
(`httpx.RequestError` → 503, non-JSON upstream body → same status +
`{"error": ...}`) are consistent across all 15 files — audited
line-by-line in `docs/pr-e-admin-console-production-hardening.md`. No
secret (`RAGBIO_API_KEY`, etc.) is ever echoed into a response or logged;
each is injected only into the outbound `Authorization` header.

### Deployment status

**PR14.7B (merged):** `dist-admin`/`dist-control` are wired into an actual
nginx serving image (`docker/nginx/{control-center.conf,api-proxy.conf}` +
a dedicated `control-center-web` container), host-based on the `Host`
header, verified on `localhost:5174`. `control-center`'s FastAPI process
itself is unchanged — it never serves static files itself.

**PR14.7C (prepared, not yet applied):** the Cloudflare Tunnel cutover
that makes both domains reachable externally —
`control.omnibioai.org`'s ingress moving from `:7070` direct-to-backend to
`:5174`, plus a new `admin.omnibioai.org` → `:5174` rule. Blocked on two
things outside a coding agent's reach: root access on the tunnel host to
edit `/etc/cloudflared/config.yml`, and a DNS record for
`admin.omnibioai.org` (none exists yet — Cloudflare Tunnel ingress rules
alone don't create DNS). Cloudflare Access policy coverage for the new
hostname is separately not yet done either. See `docs/admin-console-build.md`
for the exact target-state diagram and rollout prerequisites.

---

## Running Tests

```bash
cd backend
pip install -e ".[dev]"
pytest tests/ -v
```

### Test coverage

| File | What it tests |
|------|--------------|
| `test_checks.py` | TCP, HTTP, and disk check modules; `/health` and `/report` routes |
| `test_discord.py` | Discord webhook notification helper |
| `test_gpu.py` | GPU checks — `nvidia-smi` temperature polling and full `/gpu` status (memory, utilization, processes, Ollama models) |
| `test_main.py` | FastAPI app lifecycle — job state machine, dashboard/report rendering, background report job runner, scheduler loop, startup hook |
| `test_routes_cloud.py` | `/cloud` — execution backend status |
| `test_routes_config.py` | Config-loading routes backing the dashboard/report UI |
| `test_routes_docker.py` | `/docker/*` — container inventory and tool SIF image status |
| `test_routes_llm.py` | `/llms` and `/knowledge-base` — Ollama/API key status, PubMed abstract and index-size scanning |
| `test_routes_reference.py` | `/reference` — reference genome registry |
| `test_routes_storage.py` | `/storage` — disk usage and per-organism index sizes |
| `test_runner.py` | Check-runner service-type dispatch, settings loading, `/services` and `/summary` routes |
| `test_summary_client.py` | `/summary` fetch/parse helpers, report-generator health-parsing helpers |
| `test_check_activity.py` | `/activity` — Prometheus-backed container/host resource metrics |
| `test_check_audit_trail.py` | `/audit-trail` — Redis audit-stream aggregation (event/decision/reason breakdowns) |
| `test_check_celery_status.py` | `/celery` — worker online/offline detection, recent-task parsing from the Redis result backend |
| `test_check_database_status.py` | `/database` — MySQL, Redis, and Neo4j live status |
| `test_check_gateway_traffic.py` | `/gateway-traffic` — API gateway request/latency/status-code aggregation from the audit stream |
| `test_check_image_freshness.py` | `/image-freshness` — local vs. registry `:latest` image digest comparison |
| `test_check_integrity.py` | `/integrity` — configured symlink/mount health checks |
| `test_check_license_status.py` | `/license` — license-seat/expiry status derivation |
| `test_check_usage_status.py` | `/usage` — user activity, session counts, plugin-run success-rate stats |
| `test_routes_infra.py` | Wiring for all `/gpu`, `/celery`, `/database`, `/image-freshness`, `/license`, `/usage`, `/gateway-traffic`, `/audit-trail`, `/activity`, `/integrity` routes |
| `test_core_auth.py` | `require_admin` — JWT decode, expiry, missing/invalid token, role check |
| `test_check_cron_jobs.py` | Cron-job status derivation and the pause/resume/reschedule crontab-mutation logic |
| `test_routes_cron.py` | `/cron/jobs` and its admin-gated mutation routes |
| `test_check_known_issues.py` | Known-issue load/create/update/delete logic, including UUID backfill |
| `test_routes_known_issues.py` | `/known-issues` CRUD routes, read-open/write-admin-gated |
| `test_jwt_verify.py` | `core/jwt_verify.py` — HS256 + RS256/JWKS verification, revocation, `alg`-header dispatch |
| `test_routes_dashboard.py` | `/dashboard/summary` — Overview page stat cards |
| `test_routes_auth_proxy.py` | `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/validate` proxy relay + cookie forwarding |
| `test_routes_org_proxy.py` | `/orgs`, `/platform/orgs` proxy routes |
| `test_routes_user_proxy.py` | `/platform/users` proxy routes, including MFA reset |
| `test_routes_role_proxy.py` | `/platform/roles`, `/orgs/{id}/roles`, `/organizations/{id}/roles` proxy routes |
| `test_routes_team_proxy.py` | `/orgs/{id}/teams` proxy routes |
| `test_routes_service_accounts_proxy.py` | `/orgs/{id}/api-keys`, `/orgs/{id}/oauth-clients` proxy routes |
| `test_routes_org_sso_proxy.py` | `/orgs/{id}/sso` proxy routes |
| `test_routes_org_mfa_proxy.py` | `/orgs/{id}/mfa-policy` proxy routes |
| `test_routes_audit_proxy.py` | `/platform/audit-events` proxy route |
| `test_routes_platform_config_proxy.py` | `/auth/config` read-only proxy route |
| `test_routes_billing_proxy.py` | `/billing/*` proxy routes (usage, summary, invoices, cost-breakdown, subscription) |
| `test_routes_tes_proxy.py` | `/tes/*` proxy routes |
| `test_routes_model_registry_proxy.py` | `/model-registry/*` proxy routes |
| `test_routes_workflow_bundles_proxy.py` | `/workflow-bundles/*` proxy routes |
| `test_routes_rag_proxy.py` | `/rag/*` proxy routes |

Most tests are self-contained (in-process HTTP servers, real temp-dir filesystem fixtures, no real external services). The `checks/*.py` and `routes_docker.py`/`routes_llm.py` suites additionally mock `subprocess` (docker/nvidia-smi CLI calls) and network clients (`httpx`, `redis`, `pymysql`, `neo4j`, `celery`) at the call site — no real database, broker, GPU, or Docker daemon is required at test time.

---

## Design Principles

- **Stateless-ish** — no database; the only persistent writes are the YAML config (`/config/service`), `known_issues.json`, and — for admins only — the host crontab itself
- **Config-driven** — add services via YAML, no code changes
- **Graceful degradation** — unreachable services show `DOWN`, never crash the dashboard
- **Zero mandatory cloud** — runs fully offline and air-gapped
- **Focused dependencies** — FastAPI, uvicorn, PyYAML, pydantic, JWT, Prometheus, Celery/Redis, database clients, and report-generation libraries
- **stdlib HTTP in report** — `urllib` used for health fetching in report generator, no extra deps
- **Design-token driven** — CSS uses `@omnibioai/design-tokens` vocabulary; zero hardcoded hex values in the report or dashboard
- **Structured logging** — all key events (startup, report triggered/finished/failed, scheduler) emitted as JSON to stdout
- **Defense-in-depth on writes** — every admin-gated endpoint checks the JWT's role independently inside the app (`require_admin`), rather than trusting nginx's `auth_request` alone
- **Honest scope over convenience** — `/coverage/generate` only runs on control-center itself rather than faking full-ecosystem coverage from inside a container that can't actually run the other repos' test suites (see `/coverage/generate` in API Endpoints)

---

## Planned Enhancements (Post-Beta)

- Historical uptime tracking
- Alert hooks (Slack, email)
- `/auth/login` audit trail — it currently bypasses api-gateway's `AuditMiddleware` entirely (nginx proxies `/auth/*` straight to auth-service), so there's no IP-level or attempt-level record of login attempts anywhere in the ecosystem. Needs deliberate design (what to log, where, without creating a new PII/security concern in the audit stream itself), not a quick patch — tracked as a known issue in the Admin tab

---

## Current Status — repository snapshot (2026-08-23)

| Feature | Status |
|---------|--------|
| HTTP health checks | ✓ Stable |
| TCP checks (MySQL, Redis) | ✓ Stable |
| Disk usage checks | ✓ Stable |
| JSON summary API | ✓ Stable |
| Ecosystem report — Architecture | ✓ Stable |
| Ecosystem report — Projects | ✓ Stable |
| Ecosystem report — Languages | ✓ Stable |
| Ecosystem report — Coverage | ✓ Stable |
| Ecosystem report — Health tab | ✓ Stable |
| Unit tests | ✓ 1,394 tests collected at last review; configured coverage gate is 98%, but the current checkout requires coverage work before that gate is met |
| Docker deployment | ✓ Root Dockerfile is current; Compose file is an ecosystem template with an external build context |
| Prometheus metrics (/metrics) | ✓ Stable |
| Scheduled report generation | ✓ Stable |
| JWT authentication (via nginx) | ✓ Stable |
| Browser session cookie + silent refresh | ✓ Stable |
| RS256/JWKS verification (local `jwt_verify.py`) | ✓ Ready — HS256 still the production default |
| Admin-role gating (app-level, defense-in-depth) | ✓ Stable |
| Admin tab — Actions (report/coverage regen) | ✓ Stable |
| Admin tab — Scheduled Jobs (7 cron jobs, pause/resume/reschedule) | ✓ Stable |
| Admin tab — Known Issues (live CRUD) | ✓ Stable |
| Coverage collection (/coverage/generate, control-center-scoped) | ✓ Stable |
| npm-audit vulnerability scanning (CI/CD Health tab) | ✓ Stable |
| Background report job API | ✓ Stable |
| Docker inventory endpoints | ✓ Stable |
| Structured JSON logging | ✓ Stable |
| Design token CSS alignment | ✓ Stable |
| LLM monitoring (/llms) | ✓ Stable |
| Cloud backend status (/cloud) | ✓ Stable |
| Reference genome registry | ✓ Implemented; organism/index availability is deployment-dependent |
| AI Knowledge Base (/knowledge-base) | ✓ Implemented; corpus size is deployment-dependent |
| Storage monitoring (/storage) | ✓ Stable |
| Report — LLMs tab | ✓ Stable |
| Report — Cloud tab | ✓ Stable |
| Report — Reference Data tab | ✓ Stable |
| Report — AI Knowledge Base tab | ✓ Stable |
| Report — Storage tab | ✓ Stable |
| Sidebar navigation (report UI) | ✓ Stable |
| GPU health detection (/gpu) | ✓ Stable |
| Audit Trail (/audit-trail) | ✓ Stable |
| CVE Trend | ✓ Stable |
| Admin Console — Organizations, Users, Teams, Roles & Permissions | ✓ Stable |
| Admin Console — Security (MFA Policy, IAM/SSO, Audit Logs, API Keys/Service Accounts) | ✓ Stable |
| Admin Console — Billing, Workflows, Tool Execution, AI Models, RAG/PubMed, Settings | ✓ Stable |
| Admin Console — Sessions, Integrations | Placeholder (`functional: false`, "Coming Soon") |
| Admin Console dual-build (`dist-admin`/`dist-control`, nginx host-based split) | ✓ Implemented and locally verifiable; external deployment is separate |
| Admin Console external domain cutover (`admin.omnibioai.org` via Cloudflare Tunnel) | Pending — requires DNS, tunnel-host access, and Cloudflare Access policy |
| Historical tracking | Planned |
| Alert hooks (Slack, email) | Planned |
| `/auth/login` audit trail | Planned — needs deliberate design, see Planned Enhancements |

---

## License

Apache License 2.0
