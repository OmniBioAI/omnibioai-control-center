# OmniBioAI Control Center

**Operational health dashboard, ecosystem report server, and observability hub for the OmniBioAI stack.**

The Control Center is a FastAPI service that aggregates health status across all OmniBioAI components, serves an interactive ecosystem report, exposes Prometheus metrics, and auto-generates reports on a configurable schedule.

---

## What It Does

- **Health monitoring** — TCP, HTTP, and disk checks across all ecosystem services
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
│   │   │   ├── routes_report.py    # GET /report
│   │   │   ├── routes_llm.py       # GET /llms, /cloud, /knowledge-base, /storage
│   │   │   └── routes_reference.py # GET /reference
│   │   ├── checks/
│   │   │   ├── http.py             # HTTP health checks
│   │   │   ├── tcp.py              # TCP health checks (MySQL, Redis)
│   │   │   └── disk.py             # Disk usage checks
│   │   ├── core/
│   │   │   ├── runner.py           # Dispatches checks per service type
│   │   │   └── settings.py         # Loads control_center.yaml
│   │   └── utils/
│   │       └── summary_client.py   # Fetches /summary for report generation
│   └── tests/
│       ├── test_checks.py          # Unit tests — tcp/http/disk
│       ├── test_runner.py          # Unit tests — runner + settings
│       └── test_summary_client.py  # Unit tests — health data parsing
│
├── compose/
│   └── docker-compose.control-center.yml
├── config/
│   ├── control_center.yaml         # Active configuration
│   └── control_center.example.yaml # Reference configuration
└── docker/
    └── Dockerfile
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

### Via Docker Compose (recommended)

```bash
# From the ecosystem root (~/Desktop/machine)
docker compose \
  --project-directory . \
  -f omnibioai-control-center/compose/docker-compose.control-center.yml \
  up -d
```

Access at: `http://localhost/_svc/control` — read-only endpoints (`/health`, `/summary`, `/services`, `/report`, `/report/data`) are public; everything else requires a valid JWT via the nginx reverse proxy, and admin-gated write endpoints additionally require the `admin` role (see API Endpoints above).

For local scripts and Prometheus scraping (localhost only):
`http://127.0.0.1:7070`

> **Note:** Port 7070 is bound to `127.0.0.1` only in production.
> External access requires a valid JWT via the nginx reverse proxy.

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
| `WORKSPACE_ROOT`        | `/workspace`                  | Ecosystem root **as seen inside the container** — this is the mount point, not a host path. The compose file maps it via `${MACHINE_DIR}:/workspace`, so on the host this is wherever `MACHINE_DIR` points (e.g. `~/Desktop/machine`) |
| `CONTROL_CENTER_PORT`   | `7070`                        | Service port |
| `REPORT_SCHEDULE_HOURS` | `6`                           | Auto-regenerate report every N hours |
| `WORK_DIR`              | `/workspace/omnibioai-work`   | Path to work/output directory, **container-internal** (same `/workspace` mount as `WORKSPACE_ROOT` above) — on the host this resolves to `${MACHINE_DIR}/omnibioai-work` |
| `JWT_SECRET`            | `change-me`                   | Shared HS256 secret for validating admin JWTs locally (`require_admin`) — same value as `AUTH_SECRET_KEY` used by omnibioai-auth/workbench/api-gateway/model-registry |
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

The Admin tab shares its session with the omnibioai-studio SPA: it reads the same `omnibioai_access_token` from `localStorage`, so an existing Studio login is recognized automatically (same origin, no separate sign-in needed). If no token is present, the tab shows a login form that posts directly to `/auth/login`; if a token is present but lacks the `admin` role, the tab renders everything read-only with an explicit "admin access required" message instead of showing controls that would just fail. A 401 on any admin action (e.g. the 15-minute access-token expiry) clears the stored token and re-prompts for login rather than failing silently.

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

Most tests are self-contained (in-process HTTP servers, real temp-dir filesystem fixtures, no real external services). The `checks/*.py` and `routes_docker.py`/`routes_llm.py` suites additionally mock `subprocess` (docker/nvidia-smi CLI calls) and network clients (`httpx`, `redis`, `pymysql`, `neo4j`, `celery`) at the call site — no real database, broker, GPU, or Docker daemon is required at test time.

---

## Design Principles

- **Stateless-ish** — no database; the only persistent writes are the YAML config (`/config/service`), `known_issues.json`, and — for admins only — the host crontab itself
- **Config-driven** — add services via YAML, no code changes
- **Graceful degradation** — unreachable services show `DOWN`, never crash the dashboard
- **Zero mandatory cloud** — runs fully offline and air-gapped
- **Minimal dependencies** — FastAPI, uvicorn, PyYAML, pydantic, PyJWT only
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

## Current Status — v0.4.0-beta

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
| Unit tests | ✓ Stable — 529 tests, 99.84% coverage (98% gate met) |
| Docker Compose deployment | ✓ Stable |
| Prometheus metrics (/metrics) | ✓ Stable |
| Scheduled report generation | ✓ Stable |
| JWT authentication (via nginx) | ✓ Stable |
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
| Reference genome registry | ✓ Stable — 12 organisms |
| AI Knowledge Base (/knowledge-base) | ✓ Stable — 28M+ abstracts |
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
| Historical tracking | Planned |
| Alert hooks (Slack, email) | Planned |
| `/auth/login` audit trail | Planned — needs deliberate design, see Planned Enhancements |

---

## License

Apache License 2.0
