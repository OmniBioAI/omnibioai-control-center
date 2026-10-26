"""HTTPS-only synthetic Discord webhook sink for the isolated qualification net."""
from __future__ import annotations

import json
import os
import re
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

CAPTURE = Path(os.environ["MOCK_EVIDENCE_PATH"])
TOKEN = os.environ["MOCK_CONTROL_TOKEN"]
LOCK = threading.Lock()
MESSAGES: list[dict] = []
RESPONSES: dict[str, list[dict]] = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "SyntheticDiscordReceiver/1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("X-Qualification-Control") == TOKEN

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/__test__/health":
            self._json(200, {"status": "ok", "synthetic": True})
        elif self.path == "/__test__/messages" and self._authorized():
            with LOCK:
                self._json(200, {"messages": list(MESSAGES)})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        length = min(int(self.headers.get("Content-Length", "0")), 65536)
        body = self.rfile.read(length)
        if self.path == "/__test__/control" and self._authorized():
            try:
                command = json.loads(body)
                webhook_id = str(command["webhook_id"])
                responses = command["responses"]
                if not re.fullmatch(r"9[0-9]{5}", webhook_id) or not isinstance(responses, list):
                    raise ValueError
                with LOCK:
                    RESPONSES[webhook_id] = [dict(item) for item in responses]
                self._json(200, {"configured": True})
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_control"})
            return

        match = re.fullmatch(r"/api(?:/v[0-9]+)?/webhooks/([0-9]+)/([A-Za-z0-9_-]+)", urlsplit(self.path).path)
        if not match:
            self._json(404, {"error": "not_found"})
            return
        webhook_id = match.group(1)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid_json"})
            return
        record = {
            "webhook_id": webhook_id,
            "payload": payload,
            "received_at": time.time(),
            "synthetic": True,
        }
        with LOCK:
            MESSAGES.append(record)
            with CAPTURE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
            response = RESPONSES.get(webhook_id, [])
            next_response = response.pop(0) if response else {"status": 204}
        if next_response.get("delay_seconds"):
            time.sleep(min(8.0, max(0.0, float(next_response["delay_seconds"]))))
        status = int(next_response.get("status", 204))
        headers = next_response.get("headers", {})
        response_body = json.dumps(next_response.get("body", {}), separators=(",", ":")).encode()
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() in {"retry-after", "content-type"}:
                self.send_header(key, str(value))
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        if response_body:
            self.wfile.write(response_body)


server = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(os.environ["MOCK_TLS_CERT"], os.environ["MOCK_TLS_KEY"])
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever(poll_interval=0.25)
