from __future__ import annotations

import os
import json
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from control_center.notifications.discord import DiscordEvent, DiscordPublisher


def test_process_dies_after_mock_acceptance_and_restart_never_blindly_resends(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    source = backend / "src"
    state = tmp_path / "durable-state"
    receiver_accepted = threading.Event()
    release_response = threading.Event()
    receiver_ledger = []

    class MockReceiver(BaseHTTPRequestHandler):
        def do_POST(self):
            receiver_ledger.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            receiver_accepted.set()
            release_response.wait(timeout=10)
            self.send_response(204)
            self.end_headers()

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockReceiver)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    child = r'''
import sys
import httpx
from control_center.notifications.discord import DiscordEvent, DiscordPublisher
state = sys.argv[1]
event = DiscordEvent("crash:ambiguous:1", "support.incident", "Synthetic", "Synthetic", approved=True)
def send_to_mock_receiver(*args, **kwargs):
    return httpx.post(sys.argv[2], json=kwargs["json"], timeout=8)
publisher = DiscordPublisher({"support": "https://discord.com/api/webhooks/123/test"}, state_dir=state, post=send_to_mock_receiver)
publisher.publish(event)
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(source)
    process = subprocess.Popen(
        [sys.executable, "-c", child, str(state),
         f"http://127.0.0.1:{server.server_address[1]}/synthetic-webhook"], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert receiver_accepted.wait(timeout=8), process.communicate(timeout=1)[1]
        # The mock receiver has recorded the remote side effect, but withholds
        # the response so the publisher cannot persist a local 2xx receipt.
        process.terminate()
        process.communicate(timeout=5)
        release_response.set()
        assert len(receiver_ledger) == 1
    finally:
        release_response.set()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    event = DiscordEvent("crash:ambiguous:1", "support.incident", "Synthetic", "Synthetic", approved=True)
    sends = []
    restarted = DiscordPublisher(
        {"support": "https://discord.com/api/webhooks/123/test"}, state_dir=state,
        post=lambda *a, **k: sends.append((a, k)), sleep=lambda _: None,
    )
    # Advance only the in-process lease clock; SQLite data is the actual state
    # left by the terminated child, not a mocked state transition.
    future = time.time() + 301
    with patch("control_center.notifications.discord.time.time", return_value=future):
        result = restarted.publish(event)
    assert result.status == "delivery_unknown"
    assert restarted.delivery_state(event.event_id)[0] == "unknown"
    assert sends == []
    assert len(receiver_ledger) == 1


def test_api_crash_before_event_persistence_is_unacknowledged_and_retryable(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    state = tmp_path / "state-before-persist"
    body_path = tmp_path / "event.json"
    marker = tmp_path / "ingest-reached"
    response_marker = tmp_path / "response-written"
    event_id = "crash:before-persist:1"
    body_path.write_text(json.dumps({
        "event_id": event_id,
        "event_type": "platform.release",
        "source_service": "github",
        "created_at": "2026-10-25T00:00:00+00:00",
        "destination_channel": "announcements",
        "approved_publication": False,
        "safe_message_payload": {"title": "Synthetic", "message": "Synthetic", "color": "info", "fields": {}},
        "correlation_id": "github:crash-test",
    }, separators=(",", ":")), encoding="utf-8")
    child = r'''
import os, sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from control_center.api.routes_discord_events import router
from control_center.notifications.discord_events import DiscordEventStore
marker, response_marker, body_path = map(Path, sys.argv[2:5])
def crash_before_event_persistence(self, event, envelope):
    marker.write_text("ingest reached before commit", encoding="utf-8")
    os._exit(74)
DiscordEventStore.ingest = crash_before_event_persistence
app = FastAPI()
app.include_router(router)
with TestClient(app) as client:
    client.post("/integrations/discord/events", content=body_path.read_bytes(), headers={
        "X-Omni-Discord-Source": "github",
        "X-Omni-Discord-Timestamp": os.environ["TEST_TIMESTAMP"],
        "X-Omni-Discord-Nonce": os.environ["TEST_NONCE"],
        "X-Omni-Discord-Signature": os.environ["TEST_SIGNATURE"],
    })
response_marker.write_text("response returned", encoding="utf-8")
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend / "src")
    env["DISCORD_DELIVERY_STATE_DIR"] = str(state)
    env["DISCORD_EVENT_SOURCE_SECRETS"] = json.dumps({"github": "s" * 43})
    env["DISCORD_CHANNEL_WEBHOOKS"] = json.dumps({
        "announcements": "https://discord.com/api/webhooks/123/test",
    })
    from control_center.notifications.discord_events import sign_request
    timestamp, nonce = str(int(time.time())), "crash-before-persist-nonce"
    event_body = body_path.read_bytes()
    env["TEST_TIMESTAMP"] = timestamp
    env["TEST_NONCE"] = nonce
    env["TEST_SIGNATURE"] = sign_request("s" * 43, timestamp, nonce, event_body)
    result = subprocess.run(
        [sys.executable, "-c", child, str(state), str(marker), str(response_marker), str(body_path)],
        env=env, timeout=10,
    )
    assert result.returncode == 74
    assert marker.read_text(encoding="utf-8") == "ingest reached before commit"
    assert not response_marker.exists()  # process died before API acknowledgment
    from control_center.notifications.discord_events import store_from_env, sign_request
    store = store_from_env(env)
    with pytest.raises(KeyError):
        store.get(event_id)

    # A retry with a fresh signed nonce after restart is accepted and persisted.
    app = __import__("fastapi").FastAPI()
    from control_center.api.routes_discord_events import router
    app.include_router(router)
    retry_timestamp, retry_nonce = str(int(time.time())), "crash-before-persist-retry"
    headers = {
        "X-Omni-Discord-Source": "github",
        "X-Omni-Discord-Timestamp": retry_timestamp,
        "X-Omni-Discord-Nonce": retry_nonce,
        "X-Omni-Discord-Signature": sign_request("s" * 43, retry_timestamp, retry_nonce, event_body),
    }
    with patch.dict(os.environ, env, clear=False):
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            response = client.post("/integrations/discord/events", content=event_body, headers=headers)
    assert response.status_code == 202
    assert store_from_env(env).get(event_id)["delivery_status"] == "pending_approval"


def test_process_dies_after_durable_claim_before_http_restart_preserves_ambiguity(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    state = tmp_path / "state-claimed-before-http"
    child = r'''
import os, sys
from control_center.notifications.discord import DiscordEvent, DiscordPublisher
event = DiscordEvent("crash:before-http:1", "support.incident", "Synthetic", "Synthetic", approved=True)
publisher = DiscordPublisher({"support": "https://discord.com/api/webhooks/123/test"}, state_dir=sys.argv[1])
assert publisher._claim(event, "support")
os._exit(75)  # SQLite claim committed; submission did not begin
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend / "src")
    result = subprocess.run([sys.executable, "-c", child, str(state)], env=env, timeout=10)
    assert result.returncode == 75

    event = DiscordEvent(
        "crash:before-http:1", "support.incident", "Synthetic", "Synthetic", approved=True,
    )
    sends = []
    restarted = DiscordPublisher(
        {"support": "https://discord.com/api/webhooks/123/test"}, state_dir=state,
        post=lambda *args, **kwargs: sends.append((args, kwargs)), sleep=lambda _: None,
    )
    future = time.time() + 301
    with patch("control_center.notifications.discord.time.time", return_value=future):
        result = restarted.publish(event)
    assert result.status == "delivery_unknown"
    assert restarted.delivery_state(event.event_id)[0] == "unknown"
    assert sends == []


def test_process_dies_during_submission_then_restart_does_not_resend(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    state = tmp_path / "state-during-submit"
    marker = tmp_path / "submission-started"
    child = r'''
import os, sys
from pathlib import Path
from control_center.notifications.discord import DiscordEvent, DiscordPublisher
marker = Path(sys.argv[2])
def interrupted_post(*args, **kwargs):
    marker.write_text("started")
    os._exit(76)
publisher = DiscordPublisher({"support": "https://discord.com/api/webhooks/123/test"}, state_dir=sys.argv[1], post=interrupted_post)
publisher.publish(DiscordEvent("crash:during-submit:1", "support.incident", "Synthetic", "Synthetic", approved=True))
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend / "src")
    result = subprocess.run(
        [sys.executable, "-c", child, str(state), str(marker)], env=env, timeout=10,
    )
    assert result.returncode == 76
    assert marker.read_text() == "started"

    sends = []
    restarted = DiscordPublisher(
        {"support": "https://discord.com/api/webhooks/123/test"}, state_dir=state,
        post=lambda *a, **k: sends.append((a, k)), sleep=lambda _: None,
    )
    with patch("control_center.notifications.discord.time.time", return_value=time.time() + 301):
        result = restarted.publish(DiscordEvent(
            "crash:during-submit:1", "support.incident", "Synthetic", "Synthetic", approved=True,
        ))
    assert result.status == "delivery_unknown"
    assert sends == []


def test_concurrent_processes_cannot_claim_the_same_event(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    state = tmp_path / "state-concurrent"
    start = tmp_path / "start-workers"
    publisher = DiscordPublisher(
        {"support": "https://discord.com/api/webhooks/123/test"}, state_dir=state,
    )
    child = r'''
import os, sys, time
from control_center.notifications.discord import DiscordEvent, DiscordPublisher
state, start = sys.argv[1:]
publisher = DiscordPublisher({"support": "https://discord.com/api/webhooks/123/test"}, state_dir=state)
while not os.path.exists(start):
    time.sleep(0.001)
event = DiscordEvent("crash:concurrent:1", "support.incident", "Synthetic", "Synthetic", approved=True)
print("claimed" if publisher._claim(event, "support") else "not-claimed", flush=True)
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend / "src")
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", child, str(state), str(start)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(2)
    ]
    start.write_text("go")
    outputs = []
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=10)
        assert worker.returncode == 0, stderr
        outputs.append(stdout.strip())
    assert sorted(outputs) == ["claimed", "not-claimed"]
    assert publisher.delivery_state("crash:concurrent:1") == ("pending", 0)


def test_publisher_process_restart_during_retry_preserves_ambiguous_claim(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    state = tmp_path / "state-during-retry"
    marker = tmp_path / "retry-waiting"
    child = r'''
import sys, time
from pathlib import Path
import httpx
from control_center.notifications.discord import DiscordEvent, DiscordPublisher
def connect_failure(*args, **kwargs):
    raise httpx.ConnectError("synthetic network interruption")
def wait_after_failure(delay):
    Path(sys.argv[2]).write_text("waiting")
    while True:
        time.sleep(0.05)
publisher = DiscordPublisher({"support": "https://discord.com/api/webhooks/123/test"}, state_dir=sys.argv[1], post=connect_failure, sleep=wait_after_failure)
publisher.publish(DiscordEvent("crash:retry-restart:1", "support.incident", "Synthetic", "Synthetic", approved=True))
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend / "src")
    worker = subprocess.Popen(
        [sys.executable, "-c", child, str(state), str(marker)], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), worker.communicate(timeout=1)[1]
    worker.terminate()
    worker.communicate(timeout=10)

    sends = []
    restarted = DiscordPublisher(
        {"support": "https://discord.com/api/webhooks/123/test"}, state_dir=state,
        post=lambda *a, **k: sends.append((a, k)), sleep=lambda _: None,
    )
    with patch("control_center.notifications.discord.time.time", return_value=time.time() + 301):
        result = restarted.publish(DiscordEvent(
            "crash:retry-restart:1", "support.incident", "Synthetic", "Synthetic", approved=True,
        ))
    assert result.status == "delivery_unknown"
    assert sends == []


def test_database_lock_failure_never_submits_to_discord(tmp_path):
    database = tmp_path / "state-db-lock" / "deliveries.sqlite3"
    publisher = DiscordPublisher(
        {"support": "https://discord.com/api/webhooks/123/test"},
        state_dir=database.parent, post=lambda *a, **k: pytest.fail("must not submit"),
    )
    lock = sqlite3.connect(database, timeout=1)
    lock.execute("BEGIN EXCLUSIVE")
    real_connect = sqlite3.connect

    def short_timeout_connect(*args, **kwargs):
        kwargs["timeout"] = 0.01
        return real_connect(*args, **kwargs)

    try:
        with patch("control_center.notifications.discord.sqlite3.connect", side_effect=short_timeout_connect):
            with pytest.raises(sqlite3.OperationalError):
                publisher.publish(DiscordEvent(
                    "crash:db-lock:1", "support.incident", "Synthetic", "Synthetic", approved=True,
                ))
    finally:
        lock.rollback()
        lock.close()
