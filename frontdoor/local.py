"""Local stand-in for the Lambda function URL: calls route() and serves web/ on one port.

web/config.js is a deploy output, so the local page gets its config from this server instead.

    DEMO_KEY=dev BACKEND=http DECIDER_URL=http://127.0.0.1:8080 python -m frontdoor.local
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from frontdoor.handler import BACKENDS, ROUTES, route

WEB = Path(os.environ.get("WEB_DIR", Path(__file__).resolve().parent.parent / "web")).resolve()
API_PATHS = {path for _, path in ROUTES}


class Handler(BaseHTTPRequestHandler):
    backend = None
    demo_key = ""

    def _api(self, method: str):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            status, payload = route(method, self.path.split("?")[0], headers, body, self.backend, self.demo_key)
        except Exception as e:
            print(f"front door error: {e!r}", file=sys.stderr)
            status, payload = 502, {"error": "decider call failed"}
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _config(self):
        config = {"frontdoorUrl": "", "stylistUrl": os.environ.get("STYLIST_URL", "http://127.0.0.1:8081"),
                  "demoKey": self.demo_key}
        self._send(200, f"window.OUTFIT_CONFIG = {json.dumps(config)};\n".encode(), "text/javascript")

    def _static(self):
        rel = self.path.split("?")[0].lstrip("/") or "index.html"
        if rel == "config.js":
            return self._config()
        path = (WEB / rel).resolve()
        if not path.is_relative_to(WEB) or not path.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype)

    def _send(self, status: int, data: bytes, ctype: str):
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] in API_PATHS:
            return self._api("GET")
        self._static()

    def do_POST(self):
        self._api("POST")

    def log_message(self, fmt, *args):
        pass


def main():
    Handler.backend = BACKENDS[os.environ.get("BACKEND", "http")].from_env()
    Handler.demo_key = os.environ.get("DEMO_KEY", "")
    port = int(os.environ.get("PORT", "9000"))
    print(f"front door on http://127.0.0.1:{port} serving {WEB}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
