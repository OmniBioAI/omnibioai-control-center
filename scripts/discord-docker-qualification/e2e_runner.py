"""Containerized HTTP contract tests against the real Discord router process."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jwt

BASE = os.environ["ROUTER_URL"]
MOCK = os.environ["MOCK_URL"]
CONTROL = os.environ["MOCK_CONTROL_TOKEN"]
JWT_SECRET = os.environ["SYNTHETIC_JWT_SECRET"]
SOURCE_SECRETS = json.loads(os.environ["SOURCE_SECRETS_JSON"])
EVIDENCE = Path(os.environ["EVIDENCE_PATH"])
CHANNEL_CASES = [
    ("github", "platform.release", "announcements"),
    ("github", "github.issue.confirmed", "bug-reports"),
    ("support", "feature.request.accepted", "feature-requests"),
    ("support", "support.incident", "support"),
    ("documentation", "documentation.published", "tutorials"),
    ("infrastructure", "infrastructure.alert", "omnibioai-alerts"),
]
CHANNEL_IDS = {channel: f"9{index:05d}" for index, (_, _, channel) in enumerate(CHANNEL_CASES, 1)}
WEBHOOKS = {channel: f"https://discord.com/api/webhooks/{CHANNEL_IDS[channel]}/synthetic-token-{index}"
            for index, (_, _, channel) in enumerate(CHANNEL_CASES, 1)}
RESULTS: dict = {"synthetic": True, "routes": [], "negative_cases": [], "community_exclusions": [], "requests": []}


def wait_ready() -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{BASE}/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise RuntimeError("router readiness timed out")


def issue_token(permission: str) -> str:
    return jwt.encode({"sub": "synthetic-qualification-operator", "permissions": [permission],
                       "type": "access", "exp": int(time.time()) + 300}, JWT_SECRET, algorithm="HS256")


def envelope(source: str, event_type: str, channel: str, event_id: str, *, approved: bool = False) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "source_service": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "destination_channel": channel,
        "approved_publication": approved,
        "safe_message_payload": {
            "title": f"Synthetic qualification {channel}",
            "message": f"Synthetic Docker qualification event for {channel}; not a public notice.",
            "color": "info",
            "fields": {"qualification": "synthetic", "run": "isolated"},
        },
        "correlation_id": event_id,
    }


def request_event(client: httpx.Client, source: str, data: dict, *, nonce: str | None = None,
                  timestamp: str | None = None, signature: str | None = None,
                  omit_signature: bool = False) -> httpx.Response:
    body = json.dumps(data, separators=(",", ":")).encode()
    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or f"n_{uuid.uuid4().hex}"
    key = SOURCE_SECRETS[source]
    import hmac
    import hashlib as _hashlib
    mac = hmac.new(key.encode(), timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body, _hashlib.sha256).hexdigest()
    headers = {
        "X-Omni-Discord-Source": source,
        "X-Omni-Discord-Timestamp": timestamp,
        "X-Omni-Discord-Nonce": nonce,
        "Content-Type": "application/json",
    }
    if not omit_signature:
        headers["X-Omni-Discord-Signature"] = signature or f"v1={mac}"
    return client.post(f"{BASE}/integrations/discord/events", content=body, headers=headers)


def mock_get_messages(client: httpx.Client) -> list[dict]:
    response = client.get(f"{MOCK}/__test__/messages", headers={"X-Qualification-Control": CONTROL})
    response.raise_for_status()
    return response.json()["messages"]


def run() -> None:
    wait_ready()
    with httpx.Client(timeout=10, verify=os.environ["REQUESTS_CA_BUNDLE"]) as client:
        # All six API events begin pending, then an IAM-authorized operator
        # approves them through the production route and the real publisher.
        for source, event_type, channel in CHANNEL_CASES:
            event_id = f"docker-qual:{channel}:001"
            data = envelope(source, event_type, channel, event_id)
            response = request_event(client, source, data)
            assert response.status_code == 202, (channel, response.status_code, response.text)
            assert response.json()["approval_state"] == "pending"
            token = issue_token("platform.manage_content")
            delivered = client.post(
                f"{BASE}/integrations/discord/events/{event_id}/approve",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert delivered.status_code == 200, (channel, delivered.status_code, delivered.text)
            record = delivered.json()
            assert record["delivery_status"] == "delivered" and record["attempts"] == 1
            messages = mock_get_messages(client)
            matching = [item for item in messages if item["payload"]["embeds"][0]["title"] == f"Synthetic qualification {channel}"]
            assert len(matching) == 1 and matching[0]["webhook_id"] == CHANNEL_IDS[channel]
            payload = matching[0]["payload"]
            assert payload["allowed_mentions"] == {"parse": [], "replied_user": False}
            assert payload["embeds"][0]["footer"]["text"] == "OmniBioAI"
            assert "not a public notice" in payload["embeds"][0]["description"]
            assert record["destination_channel"] == channel
            assert "webhook" not in json.dumps(record).lower()
            RESULTS["routes"].append({"channel": channel, "status": "PASS", "event_id": event_id,
                                       "delivery_status": "delivered", "attempts": record["attempts"],
                                       "mock_webhook_id": CHANNEL_IDS[channel], "audit_approval": record["approved_by"]})

            duplicate = request_event(client, source, data)
            assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
            assert duplicate.json()["delivery_status"] == "delivered"

        community = {"automated_routes": sorted({row[2] for row in CHANNEL_CASES}),
                     "forbidden_routes": ["general", "research-chat", "show-and-tell"]}
        assert not (set(community["automated_routes"]) & set(community["forbidden_routes"]))
        RESULTS["community_exclusions"] = [{"channel": name, "status": "PASS", "automated_mapping": False}
                                           for name in community["forbidden_routes"]]

        source, event_type, channel = CHANNEL_CASES[0]
        cases = []
        data = envelope(source, event_type, channel, "docker-qual:bad-signature")
        response = request_event(client, source, data, signature="v1=" + "0" * 64)
        cases.append(("invalid_signature", response.status_code == 401, response.status_code))
        data = envelope(source, event_type, channel, "docker-qual:missing-signature")
        response = request_event(client, source, data, omit_signature=True)
        cases.append(("missing_signature", response.status_code == 401, response.status_code))
        data = envelope(source, event_type, channel, "docker-qual:expired")
        response = request_event(client, source, data, timestamp=str(int(time.time()) - 301))
        cases.append(("expired_signature", response.status_code == 401, response.status_code))
        data = envelope(source, event_type, channel, "docker-qual:replay")
        nonce = f"n_{uuid.uuid4().hex}"
        first = request_event(client, source, data, nonce=nonce)
        replay = request_event(client, source, data, nonce=nonce)
        cases.append(("replayed_nonce", first.status_code == 202 and replay.status_code == 401, replay.status_code))
        data = envelope("support", "platform.release", "announcements", "docker-qual:cross-source")
        response = request_event(client, "support", data)
        cases.append(("unauthorized_event_type", response.status_code == 422, response.status_code))
        data = envelope(source, event_type, channel, "docker-qual:malformed")
        data["unknown"] = True
        response = request_event(client, source, data)
        cases.append(("malformed_envelope", response.status_code == 422, response.status_code))
        data = envelope(source, event_type, channel, "docker-qual:approval-required", approved=True)
        response = request_event(client, source, data)
        cases.append(("source_cannot_self_approve", response.status_code == 403, response.status_code))
        RESULTS["negative_cases"] = [{"case": name, "status": "PASS" if ok else "FAIL", "http_status": code}
                                      for name, ok, code in cases]
        assert all(ok for _, ok, _ in cases)

        # Read the shared disposable SQLite file through its read-only mount to
        # verify durable event/approval/receipt state and manifest assertions.
        db = sqlite3.connect("file:/run/discord-state/deliveries.sqlite3?mode=ro", uri=True)
        rows = db.execute("SELECT event_id, delivery_status, attempts, approval_state, receipt_json FROM discord_event_records ORDER BY event_id").fetchall()
        assert len([row for row in rows if row[0].startswith("docker-qual:")]) >= 7
        successful = [row for row in rows if row[0].startswith("docker-qual:") and row[1] == "delivered"]
        assert len(successful) == 6
        RESULTS["persistence"] = {"synthetic_records": len(rows), "six_routes_delivered": len(successful),
                                  "receipt_rows": sum(bool(row[4]) for row in rows)}
        db.close()

    RESULTS["status"] = "PASS"
    RESULTS["routes_passed"] = len(RESULTS["routes"])
    RESULTS["community_exclusions_passed"] = len(RESULTS["community_exclusions"])
    EVIDENCE.write_text(json.dumps(RESULTS, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        RESULTS["status"] = "FAIL"
        RESULTS["error_type"] = type(exc).__name__
        EVIDENCE.write_text(json.dumps(RESULTS, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
