#!/usr/bin/env python3
"""Lightweight local status API for Agent Mission Control.

No database, no external web framework. It samples local Hermes/runtime state on each
GET /api/status request and returns a frontend-friendly JSON payload.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Iterable, List, Optional, Tuple

HOST = "0.0.0.0"
PORT = 8090

AGENT_DEFS = [
    {"id": "cto", "name": "Jack", "role": "CTO", "profile": "cto"},
    {"id": "backend", "name": "David", "role": "Backend", "profile": "backend"},
    {"id": "frontend", "name": "Vivi", "role": "Frontend", "profile": "frontend"},
]

RunCmd = Callable[[List[str], int], str]
Now = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def run_command(cmd: List[str], timeout: int = 3) -> str:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return proc.stdout or ""
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def normalize_gateway(value: str) -> str:
    lower = value.strip().lower()
    if "running" in lower or lower in {"up", "active", "online", "true", "yes"}:
        return "running"
    if "stopped" in lower or lower in {"down", "inactive", "offline", "false", "no"}:
        return "stopped"
    return "unknown"


def parse_profile_gateways(output: str) -> Dict[str, str]:
    """Parse `hermes profile list` output with tolerance for table/plain formats."""
    states = {agent["profile"]: "unknown" for agent in AGENT_DEFS}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith(("name", "profile", "---")):
            continue
        for profile in states:
            if not re.search(rf"(^|\s|[◆*│|]){re.escape(profile)}(\s|[│|]|$)", line):
                continue
            lower = line.lower()
            if "gateway" in lower and not any(s in lower for s in ("running", "stopped", "active", "inactive")):
                continue
            states[profile] = normalize_gateway(line)
            # If the line is a simple table, the final status token is usually best.
            tokens = re.split(r"\s+|[│|]", line)
            tokens = [token for token in tokens if token]
            if tokens:
                last_status = normalize_gateway(tokens[-1])
                if last_status != "unknown":
                    states[profile] = last_status
    return states


def is_port_listening(ss_output: str, port: int) -> bool:
    return bool(re.search(rf"[:.]%d\b" % port, ss_output))


def parse_collector_logs(logs: str) -> Dict[str, Optional[str] | bool]:
    recent_lines = [line for line in logs.splitlines() if line.strip()]
    text = "\n".join(recent_lines[-300:])

    def first(patterns: Iterable[str]) -> Optional[str]:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip().strip('"')
        return None

    service_name = first(
        [
            r"service\.name[=:\s]+(?:Str\()?\"?([A-Za-z0-9_.:/@-]+)\"?\)?",
            r"service_name[=:\s]+(?:Str\()?\"?([A-Za-z0-9_.:/@-]+)\"?\)?",
            r'"service\.name"\s*:\s*"([^"]+)"',
        ]
    )
    session_id = first(
        [
            r"session\.id[=:\s]+(?:Str\()?\"?([A-Za-z0-9_.:/@-]+)\"?\)?",
            r"session_id[=:\s]+(?:Str\()?\"?([A-Za-z0-9_.:/@-]+)\"?\)?",
            r'"session\.id"\s*:\s*"([^"]+)"',
        ]
    )
    trace_id = first(
        [
            r"Trace ID\s*[:=]\s*([A-Fa-f0-9-]+)",
            r"trace[_\s.-]?id[=:\s]+([A-Fa-f0-9-]+)",
        ]
    )
    span_name = first(
        [
            r"Span Name\s*[:=]\s*([^,\n]+)",
            r"^\s*Name\s*[:=]\s*([^,\n]+)",
            r"span[_\s.-]?name[=:\s]+([A-Za-z0-9_.:/@ -]+)",
            r"name[=:\s]+([A-Za-z0-9_.:/@-]+)",
        ]
    )
    recent_trace_seen = bool(trace_id or service_name or session_id or re.search(r"\b(trace|span)\b", text, re.I))
    return {
        "recent_trace_seen": recent_trace_seen,
        "last_service_name": service_name,
        "last_session_id": session_id,
        "last_trace_id": trace_id,
        "last_span_name": span_name,
    }


def read_collector_logs(run_cmd: RunCmd) -> str:
    commands = [
        ["docker", "logs", "--tail", "300", "agent-otel-collector"],
        ["podman", "logs", "--tail", "300", "agent-otel-collector"],
    ]
    for cmd in commands:
        output = run_cmd(cmd, 5)
        if output and "no such" not in output.lower() and "not found" not in output.lower():
            return output
    return ""


def collect_systems(run_cmd: RunCmd) -> Tuple[dict, dict]:
    ss_output = run_cmd(["ss", "-ltn"], 3)
    collector_running = is_port_listening(ss_output, 4317) or is_port_listening(ss_output, 4318)
    frontend_running = is_port_listening(ss_output, 8088)

    logs = read_collector_logs(run_cmd) if collector_running else ""
    parsed_logs = parse_collector_logs(logs)

    systems = {
        "otel_collector": {
            "running": collector_running,
            "grpc_port": 4317,
            "http_port": 4318,
            "recent_trace_seen": bool(parsed_logs["recent_trace_seen"]),
            "last_service_name": parsed_logs["last_service_name"],
            "last_session_id": parsed_logs["last_session_id"],
        },
        "mission_control_frontend": {"running": frontend_running, "port": 8088},
        "status_api": {"running": True, "port": PORT},
    }
    return systems, parsed_logs


def agent_status(agent_id: str, gateway: str, systems: dict) -> str:
    if agent_id == "cto":
        return "Coordinating" if gateway == "running" else ("Idle" if gateway == "stopped" else "Unknown")
    if agent_id == "backend":
        if systems["otel_collector"]["running"]:
            return "Running OTEL Collector"
        return "In Progress" if gateway == "running" else "Idle"
    if agent_id == "frontend":
        if systems["mission_control_frontend"]["running"]:
            return "Serving Mission Control"
        return "Building" if gateway == "running" else "Idle"
    return "Unknown"


def agent_task(agent_id: str, systems: dict, parsed_logs: dict) -> str:
    if agent_id == "cto":
        return "Coordinating Agent Mission Control MVP integration"
    if agent_id == "backend":
        if systems["otel_collector"]["running"]:
            service = parsed_logs.get("last_service_name") or "local Hermes"
            return f"Exposing local status API and monitoring OTEL traces from {service}"
        return "Preparing status API and checking OTEL collector availability"
    if agent_id == "frontend":
        if systems["mission_control_frontend"]["running"]:
            return "Serving Mission Control UI on localhost:8088"
        return "Waiting for Mission Control frontend on port 8088"
    return ""


def build_agents(gateways: Dict[str, str], systems: dict, parsed_logs: dict) -> List[dict]:
    agents = []
    for base in AGENT_DEFS:
        gateway = gateways.get(base["profile"], "unknown")
        signals = [f"gateway={gateway}"]
        if base["id"] == "backend":
            signals.append(f"otel_collector_running={systems['otel_collector']['running']}")
            if parsed_logs.get("last_service_name"):
                signals.append(f"last_service_name={parsed_logs['last_service_name']}")
            if parsed_logs.get("last_session_id"):
                signals.append(f"last_session_id={parsed_logs['last_session_id']}")
        if base["id"] == "frontend":
            signals.append(f"frontend_8088={systems['mission_control_frontend']['running']}")
        agent = dict(base)
        agent.update(
            {
                "gateway": gateway,
                "status": agent_status(base["id"], gateway, systems),
                "current_task": agent_task(base["id"], systems, parsed_logs),
                "signals": signals,
            }
        )
        agents.append(agent)
    return agents


def build_activity(now_iso: str, gateways: Dict[str, str], systems: dict, parsed_logs: dict) -> List[dict]:
    activity = []
    if gateways.get("cto") == "running":
        activity.append({"time": now_iso, "agent": "Jack", "event": "cto gateway running", "level": "info"})
    if systems["otel_collector"]["running"]:
        activity.append({"time": now_iso, "agent": "David", "event": "OTEL collector listening on 4317/4318", "level": "success"})
    if systems["otel_collector"]["recent_trace_seen"]:
        service = systems["otel_collector"].get("last_service_name") or "unknown service"
        session = systems["otel_collector"].get("last_session_id") or "unknown session"
        span = parsed_logs.get("last_span_name") or "unknown span"
        activity.append(
            {
                "time": now_iso,
                "agent": "David",
                "event": f"collector received {service} trace, session={session}, span={span}",
                "level": "info",
            }
        )
    if systems["mission_control_frontend"]["running"]:
        activity.append({"time": now_iso, "agent": "Vivi", "event": "frontend serving on 8088", "level": "success"})
    if not activity:
        activity.append({"time": now_iso, "agent": "David", "event": "status API sampled local runtime", "level": "info"})
    return activity


def build_blockers(systems: dict) -> List[dict]:
    blockers = [
        {
            "title": "MVP status API has no TLS/auth",
            "severity": "warning",
            "detail": "CORS is open and API is intended for localhost/trusted-network MVP usage only.",
        },
        {
            "title": "Remote access may require security group/firewall rules",
            "severity": "info",
            "detail": "Ports 4317, 4318, 8088, and 8090 must be explicitly allowed if accessed remotely.",
        },
    ]
    if not systems["otel_collector"]["running"]:
        blockers.append(
            {
                "title": "OTEL collector not listening",
                "severity": "error",
                "detail": "Ports 4317/4318 are not listening; trace ingest may be unavailable.",
            }
        )
    elif not systems["otel_collector"]["recent_trace_seen"]:
        blockers.append(
            {
                "title": "No recent trace detected",
                "severity": "warning",
                "detail": "Collector port is open, but recent agent trace fields were not found in agent-otel-collector logs.",
            }
        )
    if not systems["mission_control_frontend"]["running"]:
        blockers.append(
            {
                "title": "Mission Control frontend not detected on 8088",
                "severity": "warning",
                "detail": "Vivi's UI may still be building or serving on a different port.",
            }
        )
    return blockers


def build_status(run_cmd: RunCmd = run_command, now: Now = utc_now) -> dict:
    current = now()
    now_iso = iso(current)
    profile_output = run_cmd(["hermes", "profile", "list"], 5)
    gateways = parse_profile_gateways(profile_output)
    systems, parsed_logs = collect_systems(run_cmd)
    return {
        "updated_at": now_iso,
        "source": "local-hermes-runtime",
        "agents": build_agents(gateways, systems, parsed_logs),
        "activity": build_activity(now_iso, gateways, systems, parsed_logs),
        "blockers": build_blockers(systems),
        "systems": systems,
    }


def json_response(payload: dict, status: int = 200) -> Tuple[bytes, int, dict]:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        status,
        {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Cache-Control": "no-store",
        },
    )


def handle_request(path: str, build: Callable[[], dict] = build_status) -> Tuple[bytes, int, dict]:
    route = path.split("?", 1)[0]
    if route == "/health":
        return json_response({"ok": True})
    if route == "/api/status":
        try:
            return json_response(build())
        except Exception as exc:  # defensive: status API should fail gracefully
            return json_response({"error": "status_collection_failed", "detail": str(exc)}, 500)
    return json_response({"error": "not_found"}, 404)


class StatusHandler(BaseHTTPRequestHandler):
    server_version = "HermesStatusAPI/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
        self.send_response(204)
        for key, value in json_response({})[2].items():
            self.send_header(key, value)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        body, status, headers = handle_request(self.path)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {self.log_date_time_string()} - {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), StatusHandler)
    print(f"status_api listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
