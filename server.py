#!/usr/bin/env python3
"""Agent Observability MVP static server with same-origin API proxies."""

from __future__ import annotations

import argparse
import http.client
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATUS_BACKEND_HOST = os.environ.get("MISSION_CONTROL_BACKEND_HOST", "127.0.0.1")
STATUS_BACKEND_PORT = int(os.environ.get("MISSION_CONTROL_BACKEND_PORT", "8090"))
OBS_BACKEND_HOST = os.environ.get("AGENT_OBSERVABILITY_BACKEND_HOST", "127.0.0.1")
OBS_BACKEND_PORT = int(os.environ.get("AGENT_OBSERVABILITY_BACKEND_PORT", "8091"))
STATIC_FILES = {
    "/app.js": "app.js",
    "/styles.css": "styles.css",
    "/mock-data.js": "mock-data.js",
    "/favicon.svg": "favicon.svg",
}


class ObservabilityHandler(BaseHTTPRequestHandler):
    server_version = "AgentObservabilityProxy/1.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlsplit(self.path)
        path = parsed.path

        if path in ("/", "/index.html", "/onboarding", "/connect-hermes", "/overview"):
            self.serve_file(ROOT / "index.html", "text/html; charset=utf-8")
            return

        if path in STATIC_FILES:
            self.serve_file(ROOT / STATIC_FILES[path])
            return

        if path == "/api/status":
            self.proxy_backend(STATUS_BACKEND_HOST, STATUS_BACKEND_PORT, "/api/status")
            return

        if path == "/api/me" or path.startswith("/api/projects/") or path == "/api/projects" or path.startswith("/api/auth/phone/"):
            backend_path = path + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, backend_path)
            return

        # Dev fallback for older backend APIs.
        if path == "/api/sessions":
            backend_path = "/sessions" + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, backend_path)
            return

        if path in {"/api/overview/session-card", "/api/overview/trace-card", "/api/overview/token-card", "/api/overview/top-sessions", "/api/overview/top-traces"}:
            backend_path = path.removeprefix("/api") + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, backend_path)
            return

        if path == "/api/search":
            backend_path = "/search" + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, backend_path)
            return

        if path.startswith("/api/traces/"):
            trace_suffix = self.path[len("/api/traces/") :]
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, "/traces/" + trace_suffix)
            return

        if path == "/health":
            self.send_text(200, "OK\n", "text/plain; charset=utf-8")
            return

        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith("/api/auth/phone/") or path.startswith("/api/projects/"):
            backend_path = path + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, backend_path, method="POST", forward_body=True)
            return
        self.send_error(404, "Not found")

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith("/api/projects/"):
            backend_path = path + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, backend_path, method="PATCH", forward_body=True)
            return
        self.send_error(404, "Not found")

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith("/api/projects/"):
            backend_path = path + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_backend(OBS_BACKEND_HOST, OBS_BACKEND_PORT, backend_path, method="DELETE", forward_body=True)
            return
        self.send_error(404, "Not found")

    def serve_file(self, file_path: Path, content_type: str | None = None) -> None:
        if not file_path.is_file():
            self.send_error(404, "Not found")
            return

        data = file_path.read_bytes()
        guessed_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type or guessed_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def proxy_backend(self, host: str, port: int, backend_path: str, method: str = "GET", forward_body: bool = False) -> None:
        conn: http.client.HTTPConnection | None = None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            headers = {"Accept": "application/json"}
            auth = self.headers.get("Authorization")
            if auth:
                headers["Authorization"] = auth
            body = None
            if forward_body:
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length) if length > 0 else None
                content_type = self.headers.get("Content-Type")
                if content_type:
                    headers["Content-Type"] = content_type
            conn.request(method, backend_path, body=body, headers=headers)
            response = conn.getresponse()
            body = response.read()

            self.send_response(response.status)
            content_type = response.getheader("Content-Type") or "application/json"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # keep frontend response deterministic if backend is down
            detail = f"{type(exc).__name__}: {exc}"
            upstream = f"http://{host}:{port}{backend_path}"
            body = (
                '{"error":"api proxy unavailable",'
                f'"detail":"{detail}",'
                f'"upstream":"{upstream}"}}\n'
            ).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def send_text(self, status: int, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        # The server can be launched from a short-lived agent subprocess whose stdout
        # is closed after handoff. BaseHTTPRequestHandler calls log_message during
        # send_response(); writing to a closed pipe raises BrokenPipeError before
        # headers are sent, which surfaces to browsers as "Empty reply from server".
        try:
            print(f"{self.address_string()} - {fmt % args}", flush=True)
        except (BrokenPipeError, OSError):
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Agent Observability MVP with same-origin API proxies.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8088")))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ObservabilityHandler)
    print(
        f"Agent Observability MVP listening on http://{args.host}:{args.port}; "
        f"proxying /api/status to http://{STATUS_BACKEND_HOST}:{STATUS_BACKEND_PORT}/api/status; "
        f"proxying project-scoped /api/* and legacy fallbacks to http://{OBS_BACKEND_HOST}:{OBS_BACKEND_PORT}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
