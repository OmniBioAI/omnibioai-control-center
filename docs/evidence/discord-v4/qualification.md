# Discord V4 qualification evidence

Date: 2026-10-24 (America/Chicago)

## Source revisions inspected

| Repository | Local HEAD | Notes |
|---|---|---|
| Control Center | `f37ce8c` | Working tree contains the V4 Discord changes and other pre-existing work. |
| RAG | `9e7f6b6` | Working tree includes the async Discord client/test dependency work. |
| Workbench | `79feb3da` | Working tree includes isolated Discord client tests/workflow. |
| Documentation | `559ed48` | Deploy notification script uses the central client. |
| Studio | `ec0772e7` | Active compose wiring validated; unrelated working changes remain. |

These are repository-local source references, not deployment/image provenance.

## Fresh test evidence

| Scope | Command / method | Result |
|---|---|---|
| Control Center Discord | `PYTHONPATH=backend/src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /tmp/discord-v4-pytest-venv/bin/python -m pytest -p pytest_asyncio.plugin -c /dev/null -q backend/tests/test_discord.py backend/tests/test_discord_routing.py backend/tests/test_discord_events.py backend/tests/test_discord_event_client.py -o addopts=` | 49 passed, 0 failed |
| RAG async Discord | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. /tmp/discord-v4-pytest-venv/bin/python -m pytest -p pytest_asyncio.plugin -c /dev/null -q tests/test_discord.py -o addopts=` | 10 passed, 0 failed |
| Workbench Discord | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python -m pytest -c /dev/null -q discord_tests/test_discord_events.py -o addopts=` | 8 passed, 0 failed |
| Disposable pipeline | `PYTHONPATH=backend/src /tmp/discord-v4-pytest-venv/bin/python scripts/discord_disposable_e2e.py` | PASS: HMAC verification, persistent pending event, explicit approval, mock Discord 2xx, duplicate suppression. It bypasses API route dispatch and production IAM. |
| Full Control Center collection | `PYTHONPATH=backend/src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /tmp/discord-v4-pytest-venv/bin/python -m pytest -c /dev/null --collect-only -q backend/tests -o addopts=` | Blocked: 1,121 tests collected; 48 collection errors due unavailable `sentry_sdk`, `sqlalchemy`, and `weasyprint`; no full suite execution. |
| Studio Compose | `docker compose -f docker-compose.yml config -q` in `omnibioai-studio` | PASS for active compose; no containers started. |
| Workflow syntax | PyYAML parse of Control Center `discord-release-event.yml` | PASS. |
| ARM64 host | `uname -m` | `aarch64`; Docker daemon inspection denied by socket permissions. |

Fresh automated pytest case total: 67 passed, 0 failed (49+10+8). This excludes
the standalone disposable pipeline check and blocked full-backend collection.
Historical V3 results are not included in these totals.

## Configuration and external acceptance

The authorized local Studio environment was inspected for names/presence only:
legacy alert key present; channel webhook map absent; all seven per-source
current keys absent. No values are included. No secret-manager writes, Discord
requests, live messages, deployments, migrations, or production service
changes were made. The existing legacy alert channel identity was not verified.

Docker host access failed with permission denied. No permission changes or
privilege escalation were attempted. Consequently active image digest,
architecture, source provenance, runtime configuration, and rollback remain
unverified. Live canaries remain 0/6 because explicit live-publishing approval
was not provided.

## V4-specific changed-file manifest

The following paths were changed or added for Discord qualification during this
workstream; unrelated dirty-worktree paths are intentionally omitted:

- `omnibioai-control-center/backend/src/control_center/notifications/discord.py`
- `omnibioai-control-center/backend/tests/test_discord.py`
- `omnibioai-control-center/backend/tests/test_discord_routing.py`
- `omnibioai-control-center/scripts/discord_disposable_e2e.py`
- `omnibioai-control-center/docs/discord-multichannel-integration-v1.md`
- `omnibioai-control-center/docs/evidence/discord-v4/qualification.md`
- `omnibioai-rag/pyproject.toml`
- `omnibioai-rag/.github/workflows/discord-events.yml`
- `omnibioai-workbench/pyproject.toml`
- `omnibioai-workbench/discord_tests/test_discord_events.py`
- `omnibioai-workbench/.github/workflows/discord-events.yml`
- `omnibioai-docs/scripts/deploy-docs.sh`
- `omnibioai-utils/build_omnibioai_ecosystem.sh`
- `omnibioai-studio/docker-compose.yml`
- `omnibioai-studio/.env.example`

The seven upstream event contracts are not all connected. See the V4 source
matrix and exact operator dependencies in the integration runbook.
