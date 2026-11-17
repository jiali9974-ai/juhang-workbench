"""GitHub push receiver. Nginx exposes only /__jh_git_push; HMAC is required."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SECRET_FILE = Path(os.environ.get("JH_WEBHOOK_SECRET_FILE", "/srv/jh-workbench/webhook.secret"))
REPOSITORY = "jiali9974-ai/juhang-workbench"
MAX_BODY = 2 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.connection.settimeout(10)
        if self.path != "/__jh_git_push":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if not 0 < length <= MAX_BODY:
            self.send_error(413)
            return
        try:
            body = self.rfile.read(length)
        except (OSError, TimeoutError):
            self.send_error(408)
            return
        signature = "sha256=" + hmac.new(SECRET_FILE.read_bytes().strip(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, self.headers.get("X-Hub-Signature-256", "")):
            self.send_error(403)
            return
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Expected an object")
        except (ValueError, UnicodeDecodeError):
            self.send_error(400)
            return
        event = self.headers.get("X-GitHub-Event", "")
        repository = payload.get("repository") or {}
        if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY:
            self.send_error(403)
            return
        if event == "push" and payload.get("ref") == "refs/heads/main" and not payload.get("deleted"):
            try:
                subprocess.run(
                    ["sudo", "-n", "systemctl", "start", "--no-block", "jh-workbench-sync.service"],
                    check=True, timeout=10, capture_output=True,
                )
            except (subprocess.SubprocessError, OSError):
                self.send_error(503)
                return
            self.send_response(202)
        else:
            self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    SECRET_FILE.read_bytes()  # Fail at startup if the secret is unavailable.
    ThreadingHTTPServer(("127.0.0.1", 18766), Handler).serve_forever()
