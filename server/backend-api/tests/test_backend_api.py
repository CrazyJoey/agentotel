import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import backend_api
from backend_api import (
    aggregate_batch,
    api_key_prefix,
    authenticate_api_key,
    api_key_filter_sql,
    normalize_phone,
    normalize_time_param,
    redact_sensitive,
    search_by_session,
    session_card,
    token_card,
    trace_card,
    trace_detail,
    create_project_tables,
    transform_otlp_json,
)


SAMPLE_OTLP = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "agent-service"}}
                ]
            },
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": "trace_demo_001",
                            "spanId": "span_root",
                            "name": "agent.run",
                            "kind": "SPAN_KIND_INTERNAL",
                            "startTimeUnixNano": "1781500000000000000",
                            "endTimeUnixNano": "1781500001200000000",
                            "status": {"code": "STATUS_CODE_OK"},
                            "attributes": [
                                {"key": "session.id", "value": {"stringValue": "session_demo_001"}},
                                {"key": "agent.name", "value": {"stringValue": "demo-agent"}},
                                {"key": "llm.provider", "value": {"stringValue": "openai"}},
                                {"key": "llm.model", "value": {"stringValue": "gpt-4o-mini"}},
                                {"key": "llm.usage.input_tokens", "value": {"intValue": "10"}},
                                {"key": "llm.usage.output_tokens", "value": {"intValue": "20"}},
                                {"key": "input_preview", "value": {"stringValue": "hello"}},
                                {"key": "output_preview", "value": {"stringValue": "world"}},
                            ],
                        },
                        {
                            "trace_id": "trace_demo_001",
                            "span_id": "span_tool",
                            "parent_span_id": "span_root",
                            "name": "tool.search",
                            "kind": "CLIENT",
                            "start_time_unix_nano": 1781500001200000000,
                            "end_time_unix_nano": 1781500002000000000,
                            "status": {"code": "ERROR", "message": "tool timeout"},
                            "attributes": [
                                {"key": "session.id", "value": {"stringValue": "session_demo_001"}},
                                {"key": "tool.name", "value": {"stringValue": "search"}},
                                {"key": "tool_input_preview", "value": {"stringValue": "{\"q\":\"hello\"}"}},
                                {"key": "tool_output_preview", "value": {"stringValue": "timeout"}},
                            ],
                        },
                    ]
                }
            ],
        }
    ]
}


def test_transform_otlp_json_maps_spans_to_observations():
    rows = transform_otlp_json(SAMPLE_OTLP)

    assert len(rows) == 2
    root = rows[0]
    tool = rows[1]

    assert root["trace_id"] == "trace_demo_001"
    assert root["span_id"] == "span_root"
    assert root["parent_span_id"] == ""
    assert root["session_id"] == "session_demo_001"
    assert "agent_name" not in root
    assert root["api_key_id"] == ""
    assert root["kind"] == "INTERNAL"
    assert root["started_at"] == "2026-06-15 05:06:40.000"
    assert root["ended_at"] == "2026-06-15 05:06:41.200"
    assert root["duration_ms"] == 1200
    assert root["status_code"] == "OK"
    assert root["model_provider"] == "openai"
    assert root["model_name"] == "gpt-4o-mini"
    assert root["input_tokens"] == 10
    assert root["output_tokens"] == 20
    assert root["total_tokens"] == 30
    assert root["input_preview"] == "hello"
    assert root["output_preview"] == "world"
    assert root["resource_attributes"]["service.name"] == "agent-service"

    assert tool["parent_span_id"] == "span_root"
    assert tool["kind"] == "CLIENT"
    assert tool["status_code"] == "ERROR"
    assert tool["status_message"] == "tool timeout"
    assert tool["tool_name"] == "search"
    assert tool["tool_input_preview"] == "{\"q\":\"hello\"}"
    assert tool["tool_output_preview"] == "timeout"


def test_aggregate_batch_creates_trace_and_session_latest_rows():
    observations = transform_otlp_json(SAMPLE_OTLP)

    trace_rows, session_rows = aggregate_batch(observations)

    assert len(trace_rows) == 1
    trace = trace_rows[0]
    assert trace["trace_id"] == "trace_demo_001"
    assert trace["session_id"] == "session_demo_001"
    assert trace["root_span_name"] == "agent.run"
    assert "agent_name" not in trace
    assert trace["api_key_id"] == ""
    assert trace["duration_ms"] == 2000
    assert trace["observation_count"] == 2
    assert trace["error_count"] == 1
    assert trace["input_tokens"] == 10
    assert trace["output_tokens"] == 20
    assert trace["total_tokens"] == 30
    assert trace["status_code"] == "ERROR"

    assert len(session_rows) == 1
    session = session_rows[0]
    assert session["session_id"] == "session_demo_001"
    assert session["trace_count"] == 1
    assert session["observation_count"] == 2
    assert session["error_count"] == 1
    assert session["input_tokens"] == 10
    assert session["output_tokens"] == 20
    assert session["total_tokens"] == 30


def test_normalize_time_param_accepts_iso_and_clickhouse_values():
    assert normalize_time_param("2026-06-15T05:06:40Z", "from") == "2026-06-15T05:06:40Z"
    assert normalize_time_param("2026-06-15 05:06:40.123", "to") == "2026-06-15 05:06:40.123"
    assert normalize_time_param("", "from") is None
    assert normalize_time_param(None, "to") is None


@pytest.mark.parametrize("bad", ["2026-06-15'; DROP TABLE sessions; --", "now()", "2026/06/15", "abc"])
def test_normalize_time_param_rejects_unsafe_values(bad):
    with pytest.raises(ValueError):
        normalize_time_param(bad, "from")


def test_search_by_session_adds_started_at_time_range(monkeypatch):
    captured = {}

    def fake_query(query):
        captured["query"] = query
        return []

    monkeypatch.setattr(backend_api, "ch_query_json", fake_query)

    rows = search_by_session("session_demo_001", from_time="2026-06-15T00:00:00Z", to_time="2026-06-16 00:00:00")

    assert rows == []
    query = captured["query"]
    assert "WHERE session_id = 'session_demo_001'" in query
    assert "from_ts" in query
    assert "started_at >= from_ts" in query
    assert "started_at < to_ts" in query


def test_trace_detail_filters_observations_but_not_trace_summary(monkeypatch):
    queries = []

    def fake_query(query):
        queries.append(query)
        return []

    monkeypatch.setattr(backend_api, "ch_query_json", fake_query)

    detail = trace_detail("trace_demo_001", from_time="2026-06-15 00:00:00", to_time="2026-06-16 00:00:00")

    assert detail == {"trace": None, "observations": []}
    summary_query, observation_query = queries
    assert "FROM traces" in summary_query
    assert "started_at >= parseDateTime64BestEffort" not in summary_query
    assert "FROM observations" in observation_query
    assert "trace_id = 'trace_demo_001'" in observation_query
    assert "started_at >= parseDateTime64BestEffort('2026-06-15 00:00:00', 3)" in observation_query
    assert "started_at <= parseDateTime64BestEffort('2026-06-16 00:00:00', 3)" in observation_query


def test_session_card_returns_backend_authoritative_kpi(monkeypatch):
    queries = []

    def fake_query(query):
        queries.append(query)
        if "current_sessions" in query and "previous_sessions" in query:
            return [
                {"window": "current", "session_id": "session_ok", "error_count": 0},
                {"window": "current", "session_id": "session_error", "error_count": 2},
                {"window": "previous", "session_id": "session_prev", "error_count": 0},
            ]
        if "sum(duration_ms)" in query:
            return [
                {"session_id": "session_ok", "duration_ms": 3000},
                {"session_id": "session_error", "duration_ms": 9000},
                {"session_id": "", "duration_ms": 999999},
            ]
        if "sum(total_tokens)" in query:
            return [
                {"session_id": "session_ok", "total_tokens": 100},
                {"session_id": "session_error", "total_tokens": 300},
            ]
        return [
            {"ts": "2026-06-15 00:00:00", "t": 1781485200000, "value": 2},
            {"ts": "2026-06-15 00:01:00", "t": 1781485260000, "value": 3},
        ]

    monkeypatch.setattr(backend_api, "ch_query_json", fake_query)

    result = session_card("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z")

    assert result == {
        "active_sessions": 2,
        "active_sessions_delta_pct": 100.0,
        "completion_rate": 0.5,
        "avg_duration_ms": 6000,
        "avg_tokens_per_session": 200,
        "error_session_rate": 0.5,
        "sparkline": [
            {"ts": "2026-06-15 00:00:00", "t": 1781485200000, "value": 2},
            {"ts": "2026-06-15 00:01:00", "t": 1781485260000, "value": 3},
        ],
        "meta": {"from": "2026-06-15T00:00:00Z", "to": "2026-06-16T00:00:00Z"},
    }
    assert "session_id != ''" in queries[0]
    assert "ended_at >= from_ts" in queries[0]
    assert "started_at < to_ts" in queries[0]
    assert "SELECT session_id, sum(duration_ms) AS duration_ms" in queries[1]
    assert "FROM traces" in queries[1]
    assert "SELECT session_id, sum(total_tokens) AS total_tokens" in queries[2]
    assert "FROM traces" in queries[2]
    assert "FROM sessions" in queries[3]
    assert "FROM observations" not in queries[3]
    assert "intDiv(toUnixTimestamp64Milli(started_at), 60000) * 60000" in queries[3]
    assert "count() AS value" in queries[3]
    assert "session_id != ''" in queries[3]
    assert "started_at >= from_ts" in queries[3]
    assert "started_at < to_ts" in queries[3]


def test_trace_card_returns_backend_authoritative_kpi_from_traces(monkeypatch):
    queries = []

    def fake_query(query):
        queries.append(query)
        if "current_traces" in query and "previous_traces" in query:
            return [
                {
                    "window": "current",
                    "active_traces": 2,
                    "avg_duration_ms": 2000,
                    "avg_tokens_per_trace": 100,
                    "error_traces": 1,
                },
                {
                    "window": "previous",
                    "active_traces": 1,
                    "avg_duration_ms": 5000,
                    "avg_tokens_per_trace": 200,
                    "error_traces": 0,
                },
            ]
        return [
            {"ts": "2026-06-15 00:00:00", "t": 1781485200000, "value": 2},
            {"ts": "2026-06-15 00:01:00", "t": 1781485260000, "value": 1},
        ]

    monkeypatch.setattr(backend_api, "ch_query_json", fake_query)

    result = trace_card("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z")

    assert result == {
        "active_traces": 2,
        "active_traces_delta_pct": 100.0,
        "avg_duration_ms": 2000,
        "avg_tokens_per_trace": 100,
        "error_trace_rate": 0.5,
        "sparkline": [
            {"ts": "2026-06-15 00:00:00", "t": 1781485200000, "value": 2},
            {"ts": "2026-06-15 00:01:00", "t": 1781485260000, "value": 1},
        ],
        "meta": {"from": "2026-06-15T00:00:00Z", "to": "2026-06-16T00:00:00Z"},
    }
    assert len(queries) == 2
    assert "FROM traces" in queries[0]
    assert "trace_id != ''" in queries[0]
    assert "GROUP BY trace_id" in queries[0]
    assert "uniqExact(trace_id) AS active_traces" in queries[0]
    assert "started_at >= from_ts" in queries[0]
    assert "started_at < to_ts" in queries[0]
    assert "FROM traces" in queries[1]
    assert "FROM observations" not in queries[1]
    assert "intDiv(toUnixTimestamp64Milli(started_at), 60000) * 60000" in queries[1]
    assert "uniqExact(trace_id) AS value" in queries[1]
    assert "trace_id != ''" in queries[1]
    assert "started_at >= from_ts" in queries[1]
    assert "started_at < to_ts" in queries[1]


def test_token_card_returns_llm_observation_kpi_with_costs(monkeypatch):
    queries = []

    def fake_query(query):
        queries.append(query)
        if "current_llm_calls" in query and "previous_llm_calls" in query:
            return [
                {
                    "window": "current",
                    "active_llm_calls": 3,
                    "input_tokens": 3000,
                    "output_tokens": 7000,
                    "total_tokens": 10000,
                },
                {
                    "window": "previous",
                    "active_llm_calls": 2,
                    "input_tokens": 1000,
                    "output_tokens": 3000,
                    "total_tokens": 4000,
                },
            ]
        if "GROUP BY model_provider, model_name" in query:
            return [
                {
                    "model_provider": "openai",
                    "model_name": "gpt-4o-mini",
                    "active_llm_calls": 2,
                    "input_tokens": 1000,
                    "output_tokens": 2000,
                    "total_tokens": 3000,
                },
                {
                    "model_provider": "anthropic",
                    "model_name": "claude-3-5-sonnet-20241022",
                    "active_llm_calls": 1,
                    "input_tokens": 2000,
                    "output_tokens": 5000,
                    "total_tokens": 7000,
                },
            ]
        return [
            {"ts": "2026-06-15 00:00:00", "t": 1781485200000, "value": 3000, "input_tokens": 1000, "output_tokens": 2000},
            {"ts": "2026-06-15 00:01:00", "t": 1781485260000, "value": 7000, "input_tokens": 2000, "output_tokens": 5000},
        ]

    monkeypatch.setattr(backend_api, "ch_query_json", fake_query)

    result = token_card("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z")

    assert result == {
        "total_tokens": 10000,
        "input_tokens": 3000,
        "output_tokens": 7000,
        "total_cost_cny": 0.59292,
        "avg_tokens_per_llm_call": 3333,
        "active_llm_calls": 3,
        "token_delta_pct": 150.0,
        "sparkline": [
            {"ts": "2026-06-15 00:00:00", "t": 1781485200000, "value": 3000, "input_tokens": 1000, "output_tokens": 2000},
            {"ts": "2026-06-15 00:01:00", "t": 1781485260000, "value": 7000, "input_tokens": 2000, "output_tokens": 5000},
        ],
        "cost_by_model": [
            {
                "model_provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "active_llm_calls": 1,
                "input_tokens": 2000,
                "output_tokens": 5000,
                "total_tokens": 7000,
                "input_cost_cny": 0.0432,
                "output_cost_cny": 0.54,
                "cost_cny": 0.5832,
            },
            {
                "model_provider": "openai",
                "model_name": "gpt-4o-mini",
                "active_llm_calls": 2,
                "input_tokens": 1000,
                "output_tokens": 2000,
                "total_tokens": 3000,
                "input_cost_cny": 0.00108,
                "output_cost_cny": 0.00864,
                "cost_cny": 0.00972,
            },
        ],
        "meta": {"from": "2026-06-15T00:00:00Z", "to": "2026-06-16T00:00:00Z"},
    }
    assert len(queries) == 3
    assert "FROM observations" in queries[0]
    assert "observation_type = 'llm.call'" in queries[0]
    assert "started_at >= from_ts" in queries[0]
    assert "started_at < to_ts" in queries[0]
    assert "started_at >= previous_from_ts" in queries[0]
    assert "started_at < from_ts" in queries[0]
    assert "FROM traces" not in queries[0]
    assert "GROUP BY model_provider, model_name" in queries[1]
    assert "sum(input_tokens) AS input_tokens" in queries[1]
    assert "sum(output_tokens) AS output_tokens" in queries[1]
    assert "sum(total_tokens) AS total_tokens" in queries[1]
    assert "FROM observations" in queries[1]
    assert "FROM traces" not in queries[1]
    assert "intDiv(toUnixTimestamp64Milli(started_at), 60000) * 60000" in queries[2]
    assert "sum(total_tokens) AS value" in queries[2]
    assert "sum(input_tokens) AS input_tokens" in queries[2]
    assert "sum(output_tokens) AS output_tokens" in queries[2]
    assert "FROM observations" in queries[2]
    assert "FROM traces" not in queries[2]


def test_token_normalization_supports_common_llm_fields_and_missing_defaults_zero():
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace_tokens",
                                "spanId": "span_genai",
                                "name": "llm.call",
                                "startTimeUnixNano": "1781500000000000000",
                                "endTimeUnixNano": "1781500000100000000",
                                "attributes": [
                                    {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "11"}},
                                    {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "22"}},
                                ],
                            },
                            {
                                "traceId": "trace_tokens",
                                "spanId": "span_openai",
                                "name": "llm.call",
                                "startTimeUnixNano": "1781500000200000000",
                                "endTimeUnixNano": "1781500000300000000",
                                "attributes": [
                                    {"key": "usage.prompt_tokens", "value": {"intValue": "33"}},
                                    {"key": "usage.completion_tokens", "value": {"intValue": "44"}},
                                    {"key": "usage.total_tokens", "value": {"intValue": "99"}},
                                ],
                            },
                            {
                                "traceId": "trace_tokens",
                                "spanId": "span_claude",
                                "name": "llm.call",
                                "startTimeUnixNano": "1781500000400000000",
                                "endTimeUnixNano": "1781500000500000000",
                                "attributes": [
                                    {"key": "llm.token_count.prompt", "value": {"intValue": "55"}},
                                    {"key": "llm.token_count.completion", "value": {"intValue": "66"}},
                                ],
                            },
                            {
                                "traceId": "trace_tokens_missing",
                                "spanId": "span_missing",
                                "name": "plain.span",
                                "startTimeUnixNano": "1781500000600000000",
                                "endTimeUnixNano": "1781500000700000000",
                                "attributes": [],
                            },
                        ]
                    }
                ],
            }
        ]
    }

    rows = transform_otlp_json(payload)

    assert [(r["input_tokens"], r["output_tokens"], r["total_tokens"]) for r in rows] == [
        (11, 22, 33),
        (33, 44, 99),
        (55, 66, 121),
        (0, 0, 0),
    ]


def test_redact_sensitive_removes_headers_tokens_api_keys_password_credentials():
    value = {
        "Authorization": "Bearer secret",
        "x-api-key": "ak_live_secret",
        "nested": {"password": "pw", "credentials": "cred", "safe": "ok"},
        "events": [{"token": "secret-token", "name": "visible"}],
    }

    redacted = redact_sensitive(value)

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["x-api-key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["credentials"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "ok"
    assert redacted["events"][0]["token"] == "[REDACTED]"



def test_transform_and_aggregate_use_api_key_id_not_agent_name():
    rows = transform_otlp_json(SAMPLE_OTLP, api_key_id="key_demo")

    assert len(rows) == 2
    assert all(row["api_key_id"] == "key_demo" for row in rows)
    assert all("agent_name" not in row for row in rows)

    trace_rows, session_rows = aggregate_batch(rows)

    assert trace_rows[0]["api_key_id"] == "key_demo"
    assert session_rows[0]["api_key_id"] == "key_demo"
    assert "agent_name" not in trace_rows[0]
    assert "agent_name" not in session_rows[0]


def test_api_key_filter_sql_builds_safe_where_in_and_rejects_empty():
    assert api_key_filter_sql(["key_a", "key_b"]) == "api_key_id IN ('key_a', 'key_b')"
    assert api_key_filter_sql(["", None, "key_a"]) == "api_key_id IN ('key_a')"
    with pytest.raises(ValueError):
        api_key_filter_sql([])


def test_agent_scoped_sessions_query_filters_by_api_key_ids(monkeypatch):
    captured = {}

    def fake_query(query):
        captured["query"] = query
        return []

    monkeypatch.setattr(backend_api, "ch_query_json", fake_query)

    assert backend_api.latest_sessions(limit=5, api_key_ids=["key_a", "key_b"]) == []
    assert "api_key_id IN ('key_a', 'key_b')" in captured["query"]
    assert "agent_name" not in captured["query"]


def test_create_project_tables_uses_api_key_id_and_no_agent_name(monkeypatch):
    queries = []

    def fake_post(query, data=None):
        queries.append(query)
        return ""

    monkeypatch.setattr(backend_api, "ch_post", fake_post)

    create_project_tables("agentotel_project_test")
    ddl = "\n".join(queries)

    assert "api_key_id" in ddl
    assert "agent_name" not in ddl


def test_phone_normalization_defaults_to_china_country_code():
    assert normalize_phone("13800000000", None) == ("+86", "13800000000", "+8613800000000")
    assert normalize_phone("+1 415-555-2671", "+86") == ("+1", "4155552671", "+14155552671")


def test_api_key_auth_uses_hash_only_and_returns_project_context(monkeypatch):
    api_key = "ak_live_test_secret"
    expected_hash = backend_api.hash_secret(api_key)
    queries = []

    def fake_meta_query(query, args=()):
        queries.append(query + " " + repr(args))
        assert api_key not in query
        assert all(api_key not in str(arg) for arg in args)
        if "FROM project_api_keys" in query:
            return [{"api_key_id": "key_1", "project_id": "proj_1", "agent_id": "agent_1", "status": "active"}]
        if "FROM projects" in query:
            return [{"project_id": "proj_1", "owner_user_id": "user_1", "ck_database": "agentotel_project_proj_1", "status": "active"}]
        return []

    monkeypatch.setattr(backend_api, "meta_query", fake_meta_query)
    monkeypatch.setattr(backend_api, "meta_execute", lambda query, args=(): 1)

    context = authenticate_api_key("Bearer " + api_key)

    assert context["project_id"] == "proj_1"
    assert context["ck_database"] == "agentotel_project_proj_1"
    assert expected_hash in queries[0]
    assert api_key_prefix(api_key) in queries[0]


def test_project_scoped_query_uses_project_database_and_requires_owner(monkeypatch):
    queries = []

    def fake_meta_query(query, args=()):
        queries.append(query)
        if "FROM projects" in query:
            return [{"project_id": "proj_1", "owner_user_id": "user_1", "ck_database": "agentotel_project_proj_1", "status": "active"}]
        return []

    def fake_ch_query(query):
        queries.append(query)
        if "FROM sessions" in query:
            return [{"session_id": "s1"}]
        return []

    monkeypatch.setattr(backend_api, "meta_query", fake_meta_query)
    monkeypatch.setattr(backend_api, "ch_query_json", fake_ch_query)

    ctx = backend_api.require_project_owner("proj_1", {"sub": "user_1"})
    with backend_api.project_database(ctx["ck_database"]):
        rows = backend_api.latest_sessions(limit=1)
        assert "database=agentotel_project_proj_1" in backend_api.CLICKHOUSE_URL

    assert rows == [{"session_id": "s1"}]
    assert "FROM projects" in queries[0]

    with pytest.raises(PermissionError):
        backend_api.require_project_owner("proj_1", {"sub": "user_2"})
