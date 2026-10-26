# Legacy publishers, IAM, and observability — V4 assessment

## Legacy publisher source review

Repository search found the central publisher `backend/src/control_center/notifications/discord.py`, the authenticated event API/client (`backend/src/control_center/api/routes_discord_events.py`, `backend/src/control_center/notifications/discord_events.py`, `scripts/publish_discord_event.py`), plus GitHub and support adapters. GitHub workflows target the central event client. Direct legacy webhook environment names remain in the central compatibility layer (`DISCORD_WEBHOOK_URL`, `DISCORD_ALERT_WEBHOOK_URL`) and integration status/reporting surfaces.

This is a static source assessment, not proof that every deployed runtime has migrated. Legacy-alert compatibility remains a fallback and may be required for existing behavior; no active production config was read or changed. No production publisher was cut over. Therefore `LEGACY_PUBLISHERS=NOT_QUALIFIED` pending call-site inventory, production runtime readback without values, compatibility tests, and approved cutover plan.

## IAM/security

Prior evidence reports 15 focused IAM API tests and source-specific HMAC/replay controls; the current local V4 runner could not collect the focused API suite because its Python environment lacks `fastapi` and pytest-cov. The installed repo `.venv` also lacks pytest. No IAM policy or secret was accessed. Code/test gate G6 retains its prior PASS scope, but production source identity qualification remains 0/7. Docker negative-security tests did not execute.

## Supported observability and operations

The synchronous publisher defines Prometheus delivery and retry counters, stores durable delivery state in SQLite, and writes eligible terminal failures to a local JSONL dead-letter record. There is no queue/worker or queue reconciliation mechanism. A release runbook must monitor those actual metrics and files, alert on failed/retrying delivery and durable-state age, correlate event IDs, protect SQLite/dead-letter file permissions, and verify webhook secret redaction. Thresholds, deployed scraping/alert rules, and operational recovery were not verified in this workstream. Do not describe this as queue monitoring or exactly-once delivery.
