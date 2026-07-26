# OmniBioAI Control Center

**Operational health dashboard, ecosystem report server, and observability hub for the OmniBioAI stack.**

The Control Center is a FastAPI service that aggregates health status across all OmniBioAI components, serves an interactive ecosystem report, exposes Prometheus metrics, and auto-generates reports on a configurable schedule.

---

## What It Does

- **Health monitoring** — TCP, HTTP, and disk checks across all ecosystem services
- **Live dashboard** — auto-refreshing browser UI at `/dashboard` with per-service status cards
- **Ecosystem report** — interactive HTML report (architecture · projects · languages · coverage · health) served at `/`
- **JSON API** — machine-readable health summary at `/summary` for CI/CD and external monitoring
- **Scheduled report generation** — auto-regenerates the ecosystem report every N hours (configurable via REPORT_SCHEDULE_HOURS)
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
| `/dashboard`           | GET    | Live health dashboard UI |
| `/health`              | GET    | Control Center self-check |
| `/services`            | GET    | Per-service health status (JSON) |
| `/summary`             | GET    | Full ecosystem summary — services + disk (JSON) |
| `/report`              | GET    | Redirects to `/` (serves report with live header) |
| `/report/generate`     | POST   | Trigger background report generation |
| `/report/status`       | GET    | Poll report job state (running/done/error/idle) |
| `/report/data`         | GET    | Structured report data as JSON |
| `/config`              | GET    | Raw `control_center.yaml` contents (plain text) |
| `/config/service`      | POST   | Append a new monitored service to the config |
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

Access at: `http://localhost/_svc/control` (JWT required)

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
| `WORKSPACE_ROOT`        | `/workspace`                  | Ecosystem root |
| `CONTROL_CENTER_PORT`   | `7070`                        | Service port |
| `REPORT_SCHEDULE_HOURS` | `6`                           | Auto-regenerate report every N hours |
| `WORK_DIR`              | `/workspace/omnibioai-work`   | Path to work/output directory |

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
| Miscellaneous | Known Issues | Tracked open/acknowledged/resolved issues |
| | Active Runs | Currently running/queued workflow runs |
| | Storage | Disk usage bar, data categories, organism indexes |
| | Catalog | Plugin/tool/workflow-bundle counts and breakdowns |
| | Data Layer | MySQL/Redis/Neo4j connectivity status |
| | Task Queue | Celery worker + recent task status |
| | License | Seat usage and license expiry |
| | Secrets Audit | Compose file scan for exposed secrets |
| | Image Freshness | Deployed image digests vs. latest on GHCR |
| | Exposed Ports | Compose file scan for host-exposed ports |
| | CI/CD Health | GitHub Actions status + dependency vulnerability scan per repo |
| | CVE Trend | Vulnerability count history over time, charted |
| | Backup Status | Backup job recency and status |

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

Most tests are self-contained (in-process HTTP servers, real temp-dir filesystem fixtures, no real external services). The `checks/*.py` and `routes_docker.py`/`routes_llm.py` suites additionally mock `subprocess` (docker/nvidia-smi CLI calls) and network clients (`httpx`, `redis`, `pymysql`, `neo4j`, `celery`) at the call site — no real database, broker, GPU, or Docker daemon is required at test time.

---

## Design Principles

- **Stateless** — no database, no persistent state
- **Config-driven** — add services via YAML, no code changes
- **Graceful degradation** — unreachable services show `DOWN`, never crash the dashboard
- **Zero mandatory cloud** — runs fully offline and air-gapped
- **Minimal dependencies** — FastAPI, uvicorn, PyYAML, pydantic only
- **stdlib HTTP in report** — `urllib` used for health fetching in report generator, no extra deps
- **Design-token driven** — CSS uses `@omnibioai/design-tokens` vocabulary; zero hardcoded hex values in the report or dashboard
- **Structured logging** — all key events (startup, report triggered/finished/failed, scheduler) emitted as JSON to stdout

---

## Planned Enhancements (Post-Beta)

- Historical uptime tracking
- Alert hooks (Slack, email)

---

## Current Status — v0.4.0-beta

| Feature | Status |
|---------|--------|
| HTTP health checks | ✓ Stable |
| TCP checks (MySQL, Redis) | ✓ Stable |
| Disk usage checks | ✓ Stable |
| Live dashboard UI | ✓ Stable |
| JSON summary API | ✓ Stable |
| Ecosystem report — Architecture | ✓ Stable |
| Ecosystem report — Projects | ✓ Stable |
| Ecosystem report — Languages | ✓ Stable |
| Ecosystem report — Coverage | ✓ Stable |
| Ecosystem report — Health tab | ✓ Stable |
| Unit tests | ✓ Stable — 413 tests, 99.81% coverage (98% gate met) |
| Docker Compose deployment | ✓ Stable |
| Prometheus metrics (/metrics) | ✓ Stable |
| Scheduled report generation | ✓ Stable |
| JWT authentication (via nginx) | ✓ Stable |
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

---

## License

Apache License 2.0
