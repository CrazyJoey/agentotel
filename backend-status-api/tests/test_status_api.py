import json
from datetime import datetime, timezone

import status_api


def test_parse_hermes_profile_list_extracts_gateway_states():
    output = """
NAME      PATH                                      GATEWAY
cto       /home/admin/.hermes/profiles/cto          running
backend   /home/admin/.hermes/profiles/backend      stopped
frontend  /home/admin/.hermes/profiles/frontend     unknown
"""

    states = status_api.parse_profile_gateways(output)

    assert states["cto"] == "running"
    assert states["backend"] == "stopped"
    assert states["frontend"] == "unknown"


def test_parse_hermes_profile_list_handles_selected_profile_marker():
    output = """
Profile          Model                        Gateway
 ───────────────    ───────────────────────────    ───────────
 ◆backend         ark-code-latest              stopped
  cto             ark-code-latest              running
"""

    states = status_api.parse_profile_gateways(output)

    assert states["backend"] == "stopped"
    assert states["cto"] == "running"


def test_parse_collector_logs_extracts_recent_trace_fields():
    logs = """
2026-06-15T10:00:00Z info service.name=pi-coding-agent session.id=sess-123 Trace ID: abcdef Span Name: agent.run
2026-06-15T10:00:01Z info something else
"""

    parsed = status_api.parse_collector_logs(logs)

    assert parsed["recent_trace_seen"] is True
    assert parsed["last_service_name"] == "pi-coding-agent"
    assert parsed["last_session_id"] == "sess-123"
    assert parsed["last_trace_id"] == "abcdef"
    assert parsed["last_span_name"] == "agent.run"


def test_parse_collector_logs_extracts_opentelemetry_debug_exporter_format():
    logs = '''
Span #0
    Trace ID       : b123bdf46fe12ef1854a4e73315a4db8
    Name           : POST
Attributes:
     -> session.id: Str(sess-debug)
	{"resource": {"service.instance.id": "abc", "service.name": "otelcol"}, "otelcol.signal": "traces"}
'''

    parsed = status_api.parse_collector_logs(logs)

    assert parsed["recent_trace_seen"] is True
    assert parsed["last_service_name"] == "otelcol"
    assert parsed["last_session_id"] == "sess-debug"
    assert parsed["last_trace_id"] == "b123bdf46fe12ef1854a4e73315a4db8"
    assert parsed["last_span_name"] == "POST"


def test_build_status_contract_uses_real_signals_from_injected_collectors():
    def fake_run(cmd, timeout=3):
        if cmd[:3] == ["hermes", "profile", "list"]:
            return "cto /x running\nbackend /y running\nfrontend /z stopped\n"
        if cmd and cmd[0] == "ss":
            return "LISTEN 0 4096 *:4317 *:*\nLISTEN 0 4096 *:4318 *:*\nLISTEN 0 4096 *:8088 *:*\n"
        if cmd[:3] in (["docker", "logs", "--tail"], ["podman", "logs", "--tail"]):
            return "service.name=pi-coding-agent session.id=sess-456 Trace ID: trace-1 Span Name: chat.completion"
        return ""

    payload = status_api.build_status(run_cmd=fake_run, now=lambda: datetime(2026, 6, 15, tzinfo=timezone.utc))

    assert payload["source"] == "local-hermes-runtime"
    assert payload["systems"]["otel_collector"]["running"] is True
    assert payload["systems"]["otel_collector"]["recent_trace_seen"] is True
    assert payload["systems"]["otel_collector"]["last_service_name"] == "pi-coding-agent"
    assert payload["systems"]["mission_control_frontend"]["running"] is True
    assert payload["systems"]["status_api"] == {"running": True, "port": 8090}
    assert {agent["id"]: agent["gateway"] for agent in payload["agents"]} == {
        "cto": "running",
        "backend": "running",
        "frontend": "stopped",
    }
    assert any(item["agent"] == "David" and "trace" in item["event"] for item in payload["activity"])
    assert any("TLS/auth" in item["title"] for item in payload["blockers"])


def test_handler_status_response_has_cors_and_json():
    body, status, headers = status_api.handle_request("/api/status", build=lambda: {"ok": True})

    assert status == 200
    assert json.loads(body.decode()) == {"ok": True}
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Access-Control-Allow-Origin"] == "*"


def test_handler_health_response():
    body, status, headers = status_api.handle_request("/health")

    assert status == 200
    assert json.loads(body.decode()) == {"ok": True}
    assert headers["Access-Control-Allow-Origin"] == "*"
