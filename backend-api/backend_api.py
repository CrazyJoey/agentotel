#!/usr/bin/env python3
"""Minimal Agent Observability backend API.

MVP scope:
- OTLP HTTP JSON trace ingest -> ClickHouse sessions/traces/observations
- Simple query APIs for frontend
- Python stdlib only
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DB = os.getenv("CLICKHOUSE_DB", "agent_observability")
CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", f"http://127.0.0.1:8123/?database={DB}")
PROJECT_ID = os.getenv("PROJECT_ID", "default")
ENVIRONMENT = os.getenv("ENVIRONMENT", "default")
META_DB = os.getenv("META_DB", "agentotel_meta")
JWT_SECRET = os.getenv("JWT_SECRET", "agentotel-dev-secret-change-me")
SECRET_PEPPER = os.getenv("SECRET_PEPPER", JWT_SECRET)
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "console")
PHONE_CODE_TTL_SECONDS = int(
    os.getenv("PHONE_CODE_TTL_SECONDS")
    or int(os.getenv("ALIYUN_SMS_CODE_EXPIRE_MINUTES", "5")) * 60
)
PHONE_CODE_RESEND_INTERVAL_SECONDS = int(os.getenv("PHONE_CODE_RESEND_INTERVAL_SECONDS", os.getenv("ALIYUN_SMS_MIN_INTERVAL_SECONDS", "60")))
PHONE_CODE_DAILY_LIMIT = int(os.getenv("PHONE_CODE_DAILY_LIMIT", os.getenv("ALIYUN_SMS_DAILY_LIMIT", "10")))
PHONE_CODE_IP_HOURLY_LIMIT = int(os.getenv("PHONE_CODE_IP_HOURLY_LIMIT", "30"))
ALIYUN_SMS_ENDPOINT = os.getenv("ALIYUN_SMS_ENDPOINT", "https://dysmsapi.aliyuncs.com/")
ALIYUN_SMS_REGION_ID = os.getenv("ALIYUN_SMS_REGION_ID", "cn-hangzhou")
ALIYUN_SMS_ACCESS_KEY_ID = os.getenv("ALIYUN_SMS_ACCESS_KEY_ID", "")
ALIYUN_SMS_ACCESS_KEY_SECRET = os.getenv("ALIYUN_SMS_ACCESS_KEY_SECRET", "")
ALIYUN_SMS_SIGN_NAME = os.getenv("ALIYUN_SMS_SIGN_NAME", "")
ALIYUN_SMS_LOGIN_TEMPLATE_CODE = os.getenv("ALIYUN_SMS_LOGIN_TEMPLATE_CODE", "")
ALIYUN_SMS_REGISTER_TEMPLATE_CODE = os.getenv("ALIYUN_SMS_REGISTER_TEMPLATE_CODE", ALIYUN_SMS_LOGIN_TEMPLATE_CODE)
ALIYUN_SMS_FORGET_PASSWORD_TEMPLATE_CODE = os.getenv("ALIYUN_SMS_FORGET_PASSWORD_TEMPLATE_CODE", ALIYUN_SMS_LOGIN_TEMPLATE_CODE)
API_KEY_PREFIX = "ak_live_"
SENSITIVE_KEY_RE = re.compile(r"(authorization|header|headers|token|api[_-]?key|password|credential|secret)", re.I)

OBS_COLUMNS = [
    "project_id",
    "environment",
    "trace_id",
    "span_id",
    "parent_span_id",
    "session_id",
    "observation_type",
    "name",
    "kind",
    "started_at",
    "ended_at",
    "duration_ms",
    "status_code",
    "status_message",
    "agent_name",
    "model_provider",
    "model_name",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "input_preview",
    "output_preview",
    "tool_name",
    "tool_input_preview",
    "tool_output_preview",
    "attributes",
    "resource_attributes",
    "source",
]

TRACE_COLUMNS = [
    "project_id",
    "environment",
    "trace_id",
    "session_id",
    "root_span_name",
    "agent_name",
    "started_at",
    "ended_at",
    "duration_ms",
    "observation_count",
    "error_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "status_code",
]

SESSION_COLUMNS = [
    "project_id",
    "environment",
    "session_id",
    "user_id",
    "agent_name",
    "started_at",
    "ended_at",
    "duration_ms",
    "trace_count",
    "observation_count",
    "error_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
]


def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def _unwrap_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in (
        "stringValue",
        "string_value",
        "intValue",
        "int_value",
        "doubleValue",
        "double_value",
        "boolValue",
        "bool_value",
        "bytesValue",
        "bytes_value",
    ):
        if key in value:
            return value[key]
    if "arrayValue" in value or "array_value" in value:
        arr = value.get("arrayValue") or value.get("array_value") or {}
        return [_unwrap_value(v) for v in arr.get("values", [])]
    if "kvlistValue" in value or "kvlist_value" in value:
        kv = value.get("kvlistValue") or value.get("kvlist_value") or {}
        return attrs_to_map(kv.get("values", []))
    return value


def attrs_to_map(attrs: Any) -> dict[str, str]:
    if isinstance(attrs, dict):
        return {str(k): stringify(v) for k, v in attrs.items()}
    result: dict[str, str] = {}
    for item in attrs or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key is None:
            continue
        value = item.get("value")
        result[str(key)] = stringify(_unwrap_value(value))
    return result


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if any(safe in lowered for safe in ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens", "usage", "token_count")):
        return False
    return bool(SENSITIVE_KEY_RE.search(key))


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if is_sensitive_key(str(k)) else redact_sensitive(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(v) for v in value]
    return value


def token_values(attrs: dict[str, str]) -> tuple[int, int, int]:
    input_tokens = to_int(_first(
        attrs,
        "llm.usage.input_tokens", "gen_ai.usage.input_tokens",
        "llm.usage.prompt_tokens", "gen_ai.usage.prompt_tokens",
        "llm.token_count.prompt", "usage.prompt_tokens", "prompt_tokens",
        default=0,
    ))
    output_tokens = to_int(_first(
        attrs,
        "llm.usage.output_tokens", "gen_ai.usage.output_tokens",
        "llm.usage.completion_tokens", "gen_ai.usage.completion_tokens",
        "llm.token_count.completion", "usage.completion_tokens", "completion_tokens",
        default=0,
    ))
    total_raw = _first(
        attrs,
        "llm.usage.total_tokens", "gen_ai.usage.total_tokens", "usage.total_tokens", "total_tokens",
        default=None,
    )
    total_tokens = to_int(total_raw, input_tokens + output_tokens) if total_raw is not None else input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def ns_to_dt64(value: Any) -> str:
    ns = to_int(value)
    seconds = ns // 1_000_000_000
    millis = (ns % 1_000_000_000) // 1_000_000
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f".{millis:03d}"


def now_dt64() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f".{dt.microsecond // 1000:03d}"


def normalize_kind(kind: Any) -> str:
    raw = stringify(kind).upper()
    if raw.startswith("SPAN_KIND_"):
        raw = raw.removeprefix("SPAN_KIND_")
    if raw.isdigit():
        return {0: "INTERNAL", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}.get(int(raw), "INTERNAL")
    if raw in {"INTERNAL", "CLIENT", "SERVER", "PRODUCER", "CONSUMER"}:
        return raw
    return "INTERNAL"


def normalize_status(status: Any) -> tuple[str, str]:
    if not isinstance(status, dict):
        return "UNSET", ""
    raw = stringify(_first(status, "code", "statusCode", "status_code", default="UNSET")).upper()
    if raw.startswith("STATUS_CODE_"):
        raw = raw.removeprefix("STATUS_CODE_")
    if raw.isdigit():
        raw = {0: "UNSET", 1: "OK", 2: "ERROR"}.get(int(raw), "UNSET")
    if raw not in {"OK", "ERROR", "UNSET"}:
        raw = "UNSET"
    return raw, stringify(_first(status, "message", "statusMessage", "status_message", default=""))


def _resource_spans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _first(payload, "resourceSpans", "resource_spans", default=[]) or []


def _scope_spans(resource_span: dict[str, Any]) -> list[dict[str, Any]]:
    return _first(resource_span, "scopeSpans", "scope_spans", "instrumentationLibrarySpans", "instrumentation_library_spans", default=[]) or []


def transform_otlp_json(payload: dict[str, Any], project_id: str | None = None) -> list[dict[str, Any]]:
    project_id = project_id or PROJECT_ID
    rows: list[dict[str, Any]] = []
    for resource_span in _resource_spans(payload):
        resource = resource_span.get("resource") or {}
        resource_attrs = attrs_to_map(resource.get("attributes", []))
        resource_attrs = redact_sensitive(resource_attrs)
        service_name = resource_attrs.get("service.name", "")
        for scope_span in _scope_spans(resource_span):
            for span in scope_span.get("spans", []) or []:
                attrs = attrs_to_map(span.get("attributes", []))
                attrs = redact_sensitive(attrs)
                trace_id = stringify(_first(span, "traceId", "trace_id", default=""))
                span_id = stringify(_first(span, "spanId", "span_id", default=""))
                start_ns = _first(span, "startTimeUnixNano", "start_time_unix_nano", default=0)
                end_ns = _first(span, "endTimeUnixNano", "end_time_unix_nano", default=start_ns)
                start_int = to_int(start_ns)
                end_int = to_int(end_ns, start_int)
                input_tokens, output_tokens, total_tokens = token_values(attrs)
                status_code, status_message = normalize_status(span.get("status") or {})
                row = {
                    "project_id": project_id,
                    "environment": ENVIRONMENT,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_span_id": stringify(_first(span, "parentSpanId", "parent_span_id", default="")),
                    "session_id": attrs.get("session.id", ""),
                    "observation_type": "tool" if attrs.get("tool.name") else ("llm" if (attrs.get("llm.model") or attrs.get("provider.model") or attrs.get("model.name")) else "span"),
                    "name": stringify(span.get("name", "")),
                    "kind": normalize_kind(span.get("kind", "INTERNAL")),
                    "started_at": ns_to_dt64(start_int),
                    "ended_at": ns_to_dt64(end_int),
                    "duration_ms": max(0, (end_int - start_int) // 1_000_000),
                    "status_code": status_code,
                    "status_message": status_message,
                    "agent_name": attrs.get("agent.name") or service_name,
                    "model_provider": attrs.get("llm.provider") or attrs.get("provider.name", ""),
                    "model_name": attrs.get("llm.model") or attrs.get("provider.model") or attrs.get("model.name", ""),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "input_preview": attrs.get("input_preview", ""),
                    "output_preview": attrs.get("output_preview", ""),
                    "tool_name": attrs.get("tool.name", ""),
                    "tool_input_preview": attrs.get("tool_input_preview", ""),
                    "tool_output_preview": attrs.get("tool_output_preview", ""),
                    "attributes": attrs,
                    "resource_attributes": resource_attrs,
                    "source": "otel",
                }
                if trace_id and span_id:
                    rows.append(row)
    return rows


def aggregate_batch(observations: list[dict[str, Any]], project_id: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    project_id = project_id or PROJECT_ID
    trace_rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        by_trace[row["trace_id"]].append(row)

    for trace_id, rows in by_trace.items():
        rows_sorted = sorted(rows, key=lambda r: (r["started_at"], r["span_id"]))
        root = next((r for r in rows_sorted if not r.get("parent_span_id")), rows_sorted[0])
        started_at = min(r["started_at"] for r in rows)
        ended_at = max(r["ended_at"] for r in rows)
        errors = sum(1 for r in rows if r["status_code"] == "ERROR")
        status = "ERROR" if errors else ("OK" if any(r["status_code"] == "OK" for r in rows) else "UNSET")
        trace_rows.append(
            {
                "project_id": project_id,
                "environment": ENVIRONMENT,
                "trace_id": trace_id,
                "session_id": root.get("session_id") or next((r.get("session_id", "") for r in rows if r.get("session_id")), ""),
                "root_span_name": root.get("name", ""),
                "agent_name": root.get("agent_name") or next((r.get("agent_name", "") for r in rows if r.get("agent_name")), ""),
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_ms": _duration_ms_from_dt64(started_at, ended_at),
                "observation_count": len(rows),
                "error_count": errors,
                "input_tokens": sum(to_int(r.get("input_tokens")) for r in rows),
                "output_tokens": sum(to_int(r.get("output_tokens")) for r in rows),
                "total_tokens": sum(to_int(r.get("total_tokens")) for r in rows),
                "status_code": status,
            }
        )

    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        if row.get("session_id"):
            by_session[row["session_id"]].append(row)
    for session_id, rows in by_session.items():
        started_at = min(r["started_at"] for r in rows)
        ended_at = max(r["ended_at"] for r in rows)
        session_rows.append(
            {
                "project_id": project_id,
                "environment": ENVIRONMENT,
                "session_id": session_id,
                "user_id": next((r["attributes"].get("user.id", "") for r in rows if r.get("attributes", {}).get("user.id")), ""),
                "agent_name": next((r.get("agent_name", "") for r in rows if r.get("agent_name")), ""),
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_ms": _duration_ms_from_dt64(started_at, ended_at),
                "trace_count": len({r["trace_id"] for r in rows}),
                "observation_count": len(rows),
                "error_count": sum(1 for r in rows if r["status_code"] == "ERROR"),
                "input_tokens": sum(to_int(r.get("input_tokens")) for r in rows),
                "output_tokens": sum(to_int(r.get("output_tokens")) for r in rows),
                "total_tokens": sum(to_int(r.get("total_tokens")) for r in rows),
            }
        )
    return trace_rows, session_rows


def _duration_ms_from_dt64(started_at: str, ended_at: str) -> int:
    start = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    end = datetime.strptime(ended_at, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds() * 1000))


def ch_post(query: str, data: bytes | None = None) -> str:
    request = urllib.request.Request(CLICKHOUSE_URL + "&query=" + urllib.parse.quote(query), data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ClickHouse connection failed: {exc}") from exc


def clickhouse_url_for_database(database: str) -> str:
    parsed = urllib.parse.urlparse(CLICKHOUSE_URL)
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    qs["database"] = [database]
    query = urllib.parse.urlencode(qs, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=query))


@contextlib.contextmanager
def project_database(database: str):
    global CLICKHOUSE_URL
    old_url = CLICKHOUSE_URL
    CLICKHOUSE_URL = clickhouse_url_for_database(database)
    try:
        yield
    finally:
        CLICKHOUSE_URL = old_url


def insert_json_each_row(table: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    body = "".join(json.dumps({col: row.get(col) for col in columns}, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    ch_post(f"INSERT INTO {table} ({','.join(columns)}) FORMAT JSONEachRow", body)


def ingest_payload(payload: dict[str, Any], project_id: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
    project_id = project_id or PROJECT_ID
    observations = transform_otlp_json(payload, project_id=project_id)
    if agent_name:
        for row in observations:
            row["agent_name"] = agent_name
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            attrs["agent.name"] = agent_name
            row["attributes"] = attrs
    trace_rows, session_rows = aggregate_batch(observations, project_id=project_id)
    insert_json_each_row("observations", OBS_COLUMNS, observations)
    insert_json_each_row("traces", TRACE_COLUMNS, trace_rows)
    insert_json_each_row("sessions", SESSION_COLUMNS, session_rows)
    return {"accepted": True, "observations": len(observations), "traces": len(trace_rows), "sessions": len(session_rows)}


def ch_query_json(query: str) -> list[dict[str, Any]]:
    text = ch_post(query.rstrip().rstrip(";") + " FORMAT JSONEachRow")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


_TIME_RE = re.compile(r"^[0-9TtZz:\-+. ]+$")



# --- Minimal auth/project metadata ---

def hash_secret(secret: str) -> str:
    return hmac.new(SECRET_PEPPER.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def aliyun_percent_encode(value: str) -> str:
    return urllib.parse.quote(value, safe="~")


def send_aliyun_sms_code(phone_number: str, code: str, purpose: str = "login") -> None:
    if not (ALIYUN_SMS_ACCESS_KEY_ID and ALIYUN_SMS_ACCESS_KEY_SECRET and ALIYUN_SMS_SIGN_NAME and ALIYUN_SMS_LOGIN_TEMPLATE_CODE):
        raise RuntimeError("aliyun_sms_not_configured")
    template_code = ALIYUN_SMS_LOGIN_TEMPLATE_CODE
    if purpose == "register":
        template_code = ALIYUN_SMS_REGISTER_TEMPLATE_CODE or template_code
    elif purpose == "forget_password":
        template_code = ALIYUN_SMS_FORGET_PASSWORD_TEMPLATE_CODE or template_code
    params = {
        "AccessKeyId": ALIYUN_SMS_ACCESS_KEY_ID,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone_number,
        "RegionId": ALIYUN_SMS_REGION_ID,
        "SignName": ALIYUN_SMS_SIGN_NAME,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "TemplateCode": template_code,
        "TemplateParam": json.dumps({"code": code}, ensure_ascii=False, separators=(",", ":")),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    canonical = "&".join(f"{aliyun_percent_encode(k)}={aliyun_percent_encode(str(params[k]))}" for k in sorted(params))
    string_to_sign = "GET&%2F&" + aliyun_percent_encode(canonical)
    digest = hmac.new((ALIYUN_SMS_ACCESS_KEY_SECRET + "&").encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    params["Signature"] = base64.b64encode(digest).decode("ascii")
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(ALIYUN_SMS_ENDPOINT + "?" + query, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("Code") != "OK":
        raise RuntimeError("aliyun_sms_failed:" + stringify(result.get("Code") or result.get("Message") or result))


def send_sms_code(phone_number: str, code: str, purpose: str = "login") -> None:
    if SMS_PROVIDER == "console":
        print(f"SMS console code phone={phone_number} code={code}", flush=True)
        return
    if SMS_PROVIDER == "aliyun":
        send_aliyun_sms_code(phone_number, code, purpose)
        return
    raise RuntimeError("unsupported_sms_provider")


def api_key_prefix(api_key: str) -> str:
    return api_key[:16]


def normalize_phone(phone: str, country_code: str | None = None) -> tuple[str, str, str]:
    raw = stringify(phone).strip()
    cc = stringify(country_code or "+86").strip() or "+86"
    if not cc.startswith("+"):
        cc = "+" + re.sub(r"\D", "", cc)
    if raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("86"):
            return "+86", digits[2:], "+" + digits
        if digits.startswith("1"):
            return "+1", digits[1:], "+" + digits
        return "+" + digits[:2], digits[2:], "+" + digits
    number = re.sub(r"\D", "", raw)
    return cc, number, cc + number


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def issue_jwt(user_id: str, ttl_seconds: int = 7 * 24 * 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + ttl_seconds}
    signing_input = b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + b64url(sig)


def verify_jwt(auth_header: str | None) -> dict[str, Any]:
    if not auth_header or not auth_header.startswith("Bearer "):
        raise PermissionError("missing_bearer_token")
    token = auth_header.removeprefix("Bearer ").strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise PermissionError("invalid_token")
    signing_input = parts[0] + "." + parts[1]
    expected = b64url(hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, parts[2]):
        raise PermissionError("invalid_token")
    payload = json.loads(b64url_decode(parts[1]))
    if to_int(payload.get("exp")) < int(time.time()):
        raise PermissionError("token_expired")
    return payload


def qid(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError("invalid_identifier")
    return "`" + value + "`"


def create_project_tables(database: str) -> None:
    ch_post(f"CREATE DATABASE IF NOT EXISTS {qid(database)}")
    with project_database(database):
        ch_post("""
        CREATE TABLE IF NOT EXISTS sessions (
          project_id LowCardinality(String) DEFAULT 'default', environment LowCardinality(String) DEFAULT 'default', session_id String,
          user_id String DEFAULT '', agent_name LowCardinality(String) DEFAULT '', started_at DateTime64(3, 'UTC'), ended_at DateTime64(3, 'UTC'),
          duration_ms UInt64 DEFAULT 0, trace_count UInt32 DEFAULT 0, observation_count UInt32 DEFAULT 0, error_count UInt32 DEFAULT 0,
          input_tokens UInt32 DEFAULT 0, output_tokens UInt32 DEFAULT 0, total_tokens UInt32 DEFAULT 0,
          created_at DateTime64(3, 'UTC') DEFAULT now64(3), updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
        ) ENGINE = MergeTree PARTITION BY toDate(started_at) ORDER BY (project_id, environment, session_id)
        """)
        ch_post("""
        CREATE TABLE IF NOT EXISTS traces (
          project_id LowCardinality(String) DEFAULT 'default', environment LowCardinality(String) DEFAULT 'default', trace_id String, session_id String DEFAULT '',
          root_span_name String DEFAULT '', agent_name LowCardinality(String) DEFAULT '', started_at DateTime64(3, 'UTC'), ended_at DateTime64(3, 'UTC'),
          duration_ms UInt64 DEFAULT 0, observation_count UInt32 DEFAULT 0, error_count UInt32 DEFAULT 0, input_tokens UInt32 DEFAULT 0,
          output_tokens UInt32 DEFAULT 0, total_tokens UInt32 DEFAULT 0, status_code LowCardinality(String) DEFAULT 'UNSET',
          created_at DateTime64(3, 'UTC') DEFAULT now64(3), updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
        ) ENGINE = MergeTree PARTITION BY toDate(started_at) ORDER BY (project_id, environment, trace_id)
        """)
        ch_post("""
        CREATE TABLE IF NOT EXISTS observations (
          project_id LowCardinality(String) DEFAULT 'default', environment LowCardinality(String) DEFAULT 'default', trace_id String, span_id String,
          parent_span_id String DEFAULT '', session_id String DEFAULT '', observation_type LowCardinality(String) DEFAULT 'span', name String,
          kind LowCardinality(String) DEFAULT 'INTERNAL', started_at DateTime64(3, 'UTC'), ended_at DateTime64(3, 'UTC'), duration_ms UInt64 DEFAULT 0,
          status_code LowCardinality(String) DEFAULT 'UNSET', status_message String DEFAULT '', agent_name LowCardinality(String) DEFAULT '',
          model_provider LowCardinality(String) DEFAULT '', model_name LowCardinality(String) DEFAULT '', input_tokens UInt32 DEFAULT 0, output_tokens UInt32 DEFAULT 0,
          total_tokens UInt32 DEFAULT 0, input_preview String DEFAULT '', output_preview String DEFAULT '', tool_name String DEFAULT '', tool_input_preview String DEFAULT '',
          tool_output_preview String DEFAULT '', attributes Map(String, String), resource_attributes Map(String, String), source LowCardinality(String) DEFAULT 'otel',
          ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
        ) ENGINE = MergeTree PARTITION BY toDate(started_at) ORDER BY (project_id, environment, trace_id, started_at, span_id)
        """)


def init_meta_schema() -> None:
    ch_post(f"CREATE DATABASE IF NOT EXISTS {qid(META_DB)}")
    ch_post(f"""
    CREATE TABLE IF NOT EXISTS {META_DB}.users (
      user_id String, phone_country_code String, phone_number String, phone_normalized String, display_name String DEFAULT '', status LowCardinality(String) DEFAULT 'active',
      last_login_at Nullable(DateTime64(3, 'UTC')), created_at DateTime64(3, 'UTC') DEFAULT now64(3), updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
    ) ENGINE = ReplacingMergeTree(updated_at) ORDER BY user_id
    """)
    ch_post(f"""
    CREATE TABLE IF NOT EXISTS {META_DB}.phone_login_codes (
      code_id String, phone_normalized String, code_hash String, status LowCardinality(String) DEFAULT 'active', expires_at DateTime64(3, 'UTC'),
      consumed_at Nullable(DateTime64(3, 'UTC')), request_ip String DEFAULT '', user_agent String DEFAULT '', attempt_count UInt32 DEFAULT 0,
      created_at DateTime64(3, 'UTC') DEFAULT now64(3), updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
    ) ENGINE = ReplacingMergeTree(updated_at) ORDER BY (phone_normalized, code_id)
    """)
    ch_post(f"""
    CREATE TABLE IF NOT EXISTS {META_DB}.projects (
      project_id String, owner_user_id String, name String, slug String, ck_database String, status LowCardinality(String) DEFAULT 'active',
      created_at DateTime64(3, 'UTC') DEFAULT now64(3), updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
    ) ENGINE = ReplacingMergeTree(updated_at) ORDER BY project_id
    """)
    ch_post(f"""
    CREATE TABLE IF NOT EXISTS {META_DB}.project_api_keys (
      api_key_id String, project_id String, agent_id String DEFAULT '', name String, key_prefix String, key_hash String, status LowCardinality(String) DEFAULT 'active',
      created_at DateTime64(3, 'UTC') DEFAULT now64(3), updated_at DateTime64(3, 'UTC') DEFAULT now64(3), last_used_at Nullable(DateTime64(3, 'UTC'))
    ) ENGINE = ReplacingMergeTree(updated_at) ORDER BY (project_id, api_key_id)
    """)
    ch_post(f"ALTER TABLE {META_DB}.project_api_keys ADD COLUMN IF NOT EXISTS agent_id String DEFAULT '' AFTER project_id")
    ch_post(f"ALTER TABLE {META_DB}.project_api_keys ADD COLUMN IF NOT EXISTS key_plaintext String DEFAULT '' AFTER key_hash")
    ch_post(f"""
    CREATE TABLE IF NOT EXISTS {META_DB}.project_agents (
      agent_id String, project_id String, name String, slug String, kind String DEFAULT 'custom', status LowCardinality(String) DEFAULT 'active',
      created_at DateTime64(3, 'UTC') DEFAULT now64(3), updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
    ) ENGINE = ReplacingMergeTree(updated_at) ORDER BY (project_id, agent_id)
    """)


def create_api_key(project_id: str, name: str = "默认接入 Key", agent_id: str = "") -> dict[str, str]:
    api_key_id = "key_" + uuid.uuid4().hex
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    row = {"api_key_id": api_key_id, "project_id": project_id, "agent_id": agent_id, "name": name, "key_prefix": api_key_prefix(key), "key_hash": hash_secret(key), "key_plaintext": key, "status": "active"}
    insert_json_each_row(f"{META_DB}.project_api_keys", ["api_key_id", "project_id", "agent_id", "name", "key_prefix", "key_hash", "key_plaintext", "status"], [row])
    return {"api_key_id": api_key_id, "project_id": project_id, "agent_id": agent_id, "name": name, "key_prefix": row["key_prefix"], "api_key": key}


def regenerate_api_key(project_id: str, name: str = "默认接入 Key") -> dict[str, str]:
    ch_post(f"ALTER TABLE {META_DB}.project_api_keys UPDATE status='revoked' WHERE project_id={sql_quote(project_id)} AND status='active' AND agent_id=''")
    return create_api_key(project_id, name)


def regenerate_agent_api_key(project_id: str, agent_id: str, name: str = "Agent 接入 Key") -> dict[str, str]:
    agent = agent_for_project(project_id, agent_id)
    if not agent:
        raise FileNotFoundError("agent_not_found")
    ch_post(f"ALTER TABLE {META_DB}.project_api_keys UPDATE status='revoked' WHERE project_id={sql_quote(project_id)} AND agent_id={sql_quote(agent_id)} AND status='active' SETTINGS mutations_sync=1")
    return create_api_key(project_id, name or f"{stringify(agent.get('name')) or 'Agent'} 接入 Key", agent_id=agent_id)


def create_project(owner_user_id: str, name: str = "默认项目") -> dict[str, Any]:
    project_id = "proj_" + uuid.uuid4().hex[:16]
    slug = "default" if name == "默认项目" else re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or "project"
    ck_database = "agentotel_project_" + project_id
    row = {"project_id": project_id, "owner_user_id": owner_user_id, "name": name, "slug": slug, "ck_database": ck_database, "status": "active"}
    insert_json_each_row(f"{META_DB}.projects", ["project_id", "owner_user_id", "name", "slug", "ck_database", "status"], [row])
    create_project_tables(ck_database)
    key = create_api_key(project_id)
    default_agent = create_agent(project_id, "default", "default")
    row["api_keys"] = [key]
    row["default_agent"] = default_agent
    return row


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {"user_id": row.get("user_id"), "phone_country_code": row.get("phone_country_code"), "phone_number": row.get("phone_number"), "phone_normalized": row.get("phone_normalized"), "display_name": row.get("display_name", ""), "status": row.get("status", "active")}


def public_project(row: dict[str, Any]) -> dict[str, Any]:
    return {"project_id": row.get("project_id"), "owner_user_id": row.get("owner_user_id"), "name": row.get("name"), "slug": row.get("slug"), "ck_database": row.get("ck_database"), "status": row.get("status", "active")}


def public_agent(row: dict[str, Any], key: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"agent_id": row.get("agent_id"), "project_id": row.get("project_id"), "name": row.get("name"), "slug": row.get("slug"), "kind": row.get("kind", "custom"), "status": row.get("status", "active"), "created_at": row.get("created_at")}
    if key:
        payload["api_key"] = key
    return payload


def _agent_slug(name: str, fallback: str = "agent") -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or fallback


def agent_name_filter_sql(agent_name: str | None, column: str = "agent_name", include_legacy_default: bool = True) -> str | None:
    clean = normalize_search_param(agent_name)
    if not clean:
        return None
    if include_legacy_default and clean == "default":
        return f"({column} = {sql_quote(clean)} OR {column} = '')"
    return f"{column} = {sql_quote(clean)}"


def agent_name_condition(agent_name: str | None, column: str = "agent_name", prefix: str = " AND ") -> str:
    expr = agent_name_filter_sql(agent_name, column)
    return f"{prefix}{expr}" if expr else ""


def active_agent_rows(project_id: str) -> list[dict[str, Any]]:
    return ch_query_json(f"SELECT * FROM {META_DB}.project_agents WHERE project_id={sql_quote(project_id)} AND status='active' ORDER BY created_at ASC")


def ensure_default_agent(project_id: str) -> dict[str, Any]:
    rows = active_agent_rows(project_id)
    default_rows = [row for row in rows if stringify(row.get("name")) == "default"]
    if default_rows:
        agent = default_rows[0]
    elif rows:
        agent = rows[0]
    else:
        agent_id = "agent_" + uuid.uuid4().hex[:16]
        agent = {"agent_id": agent_id, "project_id": project_id, "name": "default", "slug": "default", "kind": "default", "status": "active"}
        insert_json_each_row(f"{META_DB}.project_agents", ["agent_id", "project_id", "name", "slug", "kind", "status"], [agent])
    key_rows = ch_query_json(f"SELECT api_key_id FROM {META_DB}.project_api_keys WHERE project_id={sql_quote(project_id)} AND agent_id={sql_quote(stringify(agent.get('agent_id')))} AND status='active' ORDER BY created_at DESC LIMIT 1")
    if not key_rows:
        create_api_key(project_id, f"{stringify(agent.get('name')) or 'default'} 接入 Key", agent_id=stringify(agent.get("agent_id")))
    return agent


def list_agents(project_id: str) -> list[dict[str, Any]]:
    ensure_default_agent(project_id)
    agents = active_agent_rows(project_id)
    result: list[dict[str, Any]] = []
    for agent in agents:
        agent_id = stringify(agent.get("agent_id"))
        rows = ch_query_json(
            f"SELECT api_key_id, project_id, agent_id, name, key_prefix, key_plaintext AS api_key, status, created_at, updated_at, last_used_at "
            f"FROM {META_DB}.project_api_keys "
            f"WHERE project_id={sql_quote(project_id)} AND agent_id={sql_quote(agent_id)} AND status='active' "
            f"ORDER BY created_at DESC LIMIT 1"
        )
        key = rows[0] if rows else None
        if not key or not stringify(key.get("api_key")):
            # MVP policy: API Key is displayed directly. Old hash-only keys cannot be recovered,
            # so rotate them once and keep plaintext for Settings + Integrations.
            key = regenerate_agent_api_key(project_id, agent_id, f"{stringify(agent.get('name')) or 'Agent'} 接入 Key")
        result.append(public_agent(agent, key))
    return result


def create_agent(project_id: str, name: str, kind: str = "custom") -> dict[str, Any]:
    clean_name = (name or "").strip()[:80]
    if not clean_name:
        raise ValueError("agent_name_required")
    dup = ch_query_json(f"SELECT agent_id FROM {META_DB}.project_agents WHERE project_id={sql_quote(project_id)} AND name={sql_quote(clean_name)} AND status='active' LIMIT 1")
    if dup:
        raise ValueError("agent_name_exists")
    agent_id = "agent_" + uuid.uuid4().hex[:16]
    slug = _agent_slug(clean_name, agent_id)
    row = {"agent_id": agent_id, "project_id": project_id, "name": clean_name, "slug": slug, "kind": (kind or "custom")[:40], "status": "active"}
    insert_json_each_row(f"{META_DB}.project_agents", ["agent_id", "project_id", "name", "slug", "kind", "status"], [row])
    key = create_api_key(project_id, f"{clean_name} 接入 Key", agent_id=agent_id)
    return public_agent(row, key)


def rename_agent(project_id: str, agent_id: str, name: str) -> dict[str, Any]:
    clean_name = (name or "").strip()[:80]
    if not clean_name:
        raise ValueError("agent_name_required")
    agent = agent_for_project(project_id, agent_id)
    if not agent:
        raise FileNotFoundError("agent_not_found")
    dup = ch_query_json(f"SELECT agent_id FROM {META_DB}.project_agents WHERE project_id={sql_quote(project_id)} AND name={sql_quote(clean_name)} AND status='active' AND agent_id!={sql_quote(agent_id)} LIMIT 1")
    if dup:
        raise ValueError("agent_name_exists")
    ch_post(f"ALTER TABLE {META_DB}.project_agents UPDATE name={sql_quote(clean_name)}, slug={sql_quote(_agent_slug(clean_name, agent_id))} WHERE project_id={sql_quote(project_id)} AND agent_id={sql_quote(agent_id)} SETTINGS mutations_sync=1")
    updated = {**agent, "name": clean_name, "slug": _agent_slug(clean_name, agent_id)}
    return public_agent(updated)


def delete_agent(project_id: str, agent_id: str) -> None:
    agent = agent_for_project(project_id, agent_id)
    if not agent:
        raise FileNotFoundError("agent_not_found")
    active = active_agent_rows(project_id)
    if len(active) <= 1:
        raise ValueError("cannot_delete_last_agent")
    ch_post(f"ALTER TABLE {META_DB}.project_agents UPDATE status='deleted' WHERE project_id={sql_quote(project_id)} AND agent_id={sql_quote(agent_id)} SETTINGS mutations_sync=1")
    ch_post(f"ALTER TABLE {META_DB}.project_api_keys UPDATE status='revoked' WHERE project_id={sql_quote(project_id)} AND agent_id={sql_quote(agent_id)} AND status='active' SETTINGS mutations_sync=1")


def agent_for_project(project_id: str, agent_id: str) -> dict[str, Any] | None:
    if not agent_id:
        return None
    rows = ch_query_json(f"SELECT * FROM {META_DB}.project_agents WHERE project_id={sql_quote(project_id)} AND agent_id={sql_quote(agent_id)} AND status='active' ORDER BY updated_at DESC LIMIT 1")
    return rows[0] if rows else None


def latest_user_by_phone(phone_normalized: str) -> dict[str, Any] | None:
    rows = ch_query_json(f"SELECT * FROM {META_DB}.users WHERE phone_normalized = {sql_quote(phone_normalized)} AND status = 'active' ORDER BY updated_at DESC LIMIT 1")
    return rows[0] if rows else None


def projects_for_user(user_id: str) -> list[dict[str, Any]]:
    return [public_project(r) for r in ch_query_json(f"SELECT * FROM {META_DB}.projects WHERE owner_user_id = {sql_quote(user_id)} AND status = 'active' ORDER BY created_at ASC")]


def ensure_user_default_project(user_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    projects = projects_for_user(user_id)
    new_key = None
    if not projects:
        project = create_project(user_id, "默认项目")
        new_key = project["api_keys"][0]
        projects = [public_project(project)]
    for project in projects:
        ensure_default_agent(stringify(project.get("project_id")))
    return projects, new_key


def request_phone_code(phone: str, country_code: str | None, request_ip: str, user_agent: str) -> dict[str, Any]:
    cc, number, normalized = normalize_phone(phone, country_code)
    recent = ch_query_json(f"SELECT count() AS c FROM {META_DB}.phone_login_codes WHERE phone_normalized={sql_quote(normalized)} AND created_at > now64(3) - INTERVAL {PHONE_CODE_RESEND_INTERVAL_SECONDS} SECOND")
    if recent and to_int(recent[0].get("c")) > 0:
        raise ValueError("phone_code_resend_limited")
    daily_phone = ch_query_json(f"SELECT count() AS c FROM {META_DB}.phone_login_codes WHERE phone_normalized={sql_quote(normalized)} AND created_at > now64(3) - INTERVAL 1 DAY")
    if daily_phone and to_int(daily_phone[0].get("c")) >= PHONE_CODE_DAILY_LIMIT:
        raise ValueError("phone_daily_limited")
    hourly_ip = ch_query_json(f"SELECT count() AS c FROM {META_DB}.phone_login_codes WHERE request_ip={sql_quote(request_ip)} AND created_at > now64(3) - INTERVAL 1 HOUR")
    if hourly_ip and to_int(hourly_ip[0].get("c")) >= PHONE_CODE_IP_HOURLY_LIMIT:
        raise ValueError("ip_hourly_limited")
    code = f"{secrets.randbelow(1000000):06d}"
    row = {"code_id": "code_" + uuid.uuid4().hex, "phone_normalized": normalized, "code_hash": hash_secret(code), "status": "active", "expires_at": datetime.fromtimestamp(time.time() + PHONE_CODE_TTL_SECONDS, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:23], "request_ip": request_ip, "user_agent": user_agent[:256], "attempt_count": 0}
    insert_json_each_row(f"{META_DB}.phone_login_codes", ["code_id", "phone_normalized", "code_hash", "status", "expires_at", "request_ip", "user_agent", "attempt_count"], [row])
    send_sms_code(number if cc == "+86" else normalized, code, "login")
    return {"ok": True, "phone_normalized": normalized, "expires_in": PHONE_CODE_TTL_SECONDS}


def login_with_phone_code(phone: str, country_code: str | None, code: str) -> dict[str, Any]:
    cc, number, normalized = normalize_phone(phone, country_code)
    rows = ch_query_json(f"SELECT * FROM {META_DB}.phone_login_codes WHERE phone_normalized={sql_quote(normalized)} AND status='active' ORDER BY created_at DESC LIMIT 1")
    if not rows:
        raise PermissionError("invalid_code")
    code_row = rows[0]
    if to_int(code_row.get("attempt_count")) >= 5:
        raise PermissionError("too_many_code_attempts")
    if stringify(code_row.get("expires_at")) < now_dt64():
        raise PermissionError("code_expired")
    if not hmac.compare_digest(stringify(code_row.get("code_hash")), hash_secret(code)):
        ch_post(f"ALTER TABLE {META_DB}.phone_login_codes UPDATE attempt_count = attempt_count + 1 WHERE code_id={sql_quote(stringify(code_row.get('code_id')))}")
        raise PermissionError("invalid_code")
    ch_post(f"ALTER TABLE {META_DB}.phone_login_codes UPDATE status='consumed', consumed_at=now64(3) WHERE code_id={sql_quote(stringify(code_row.get('code_id')))}")
    user = latest_user_by_phone(normalized)
    if not user:
        user = {"user_id": "user_" + uuid.uuid4().hex, "phone_country_code": cc, "phone_number": number, "phone_normalized": normalized, "display_name": "", "status": "active"}
        insert_json_each_row(f"{META_DB}.users", ["user_id", "phone_country_code", "phone_number", "phone_normalized", "display_name", "status"], [user])
    else:
        ch_post(f"ALTER TABLE {META_DB}.users UPDATE last_login_at=now64(3) WHERE user_id={sql_quote(stringify(user.get('user_id')))}")
    projects, new_key = ensure_user_default_project(stringify(user["user_id"]))
    result = {"token": issue_jwt(stringify(user["user_id"])), "user": public_user(user), "projects": projects, "current_project_id": projects[0]["project_id"] if projects else None}
    if new_key:
        result["default_api_key"] = new_key
    return result


def require_project_owner(project_id: str, jwt_payload: dict[str, Any]) -> dict[str, Any]:
    rows = ch_query_json(f"SELECT * FROM {META_DB}.projects WHERE project_id={sql_quote(project_id)} AND status='active' ORDER BY updated_at DESC LIMIT 1")
    if not rows:
        raise FileNotFoundError("project_not_found")
    project = rows[0]
    if stringify(project.get("owner_user_id")) != stringify(jwt_payload.get("sub")):
        raise PermissionError("forbidden")
    return project


def authenticate_api_key(auth_header: str | None) -> dict[str, Any]:
    if not auth_header or not auth_header.startswith("Bearer "):
        raise PermissionError("missing_api_key")
    key = auth_header.removeprefix("Bearer ").strip()
    if not key.startswith(API_KEY_PREFIX):
        raise PermissionError("invalid_api_key")
    key_hash = hash_secret(key)
    prefix = api_key_prefix(key)
    rows = ch_query_json(f"SELECT api_key_id, project_id, agent_id, status FROM {META_DB}.project_api_keys WHERE key_prefix={sql_quote(prefix)} AND key_hash={sql_quote(key_hash)} AND status='active' ORDER BY updated_at DESC LIMIT 1")
    if not rows:
        raise PermissionError("invalid_api_key")
    key_row = rows[0]
    projects = ch_query_json(f"SELECT * FROM {META_DB}.projects WHERE project_id={sql_quote(stringify(key_row.get('project_id')))} AND status='active' ORDER BY updated_at DESC LIMIT 1")
    if not projects:
        raise PermissionError("invalid_api_key")
    ch_post(f"ALTER TABLE {META_DB}.project_api_keys UPDATE last_used_at=now64(3) WHERE api_key_id={sql_quote(stringify(key_row.get('api_key_id')))}")
    project = projects[0]
    agent = agent_for_project(stringify(project.get("project_id")), stringify(key_row.get("agent_id")))
    if not agent and not stringify(key_row.get("agent_id")):
        agent = ensure_default_agent(stringify(project.get("project_id")))
    return {"api_key_id": key_row.get("api_key_id"), "project_id": project.get("project_id"), "ck_database": project.get("ck_database"), "project": project, "agent_id": key_row.get("agent_id", ""), "agent_name": agent.get("name") if agent else "default"}


def list_api_keys(project_id: str) -> list[dict[str, Any]]:
    rows = ch_query_json(f"SELECT api_key_id, project_id, agent_id, name, key_prefix, key_plaintext AS api_key, status, created_at, updated_at, last_used_at FROM {META_DB}.project_api_keys WHERE project_id={sql_quote(project_id)} AND agent_id='' AND status='active' ORDER BY created_at ASC")
    return rows[-1:] if rows else []


def normalize_time_param(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 64 or not _TIME_RE.fullmatch(value):
        raise ValueError(f"invalid_{name}")
    parse_value = value.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise ValueError(f"invalid_{name}") from exc
    return value


def normalize_limit_param(value: str | None, default: int = 100, maximum: int = 500) -> int:
    limit = to_int(value, default)
    if limit < 1:
        return default
    return min(limit, maximum)


def time_meta(from_time: str | None, to_time: str | None, limit: int | None = None) -> dict[str, Any]:
    return {"from": from_time, "to": to_time, "limit": limit}


def time_filters(column: str, from_time: str | None, to_time: str | None) -> list[str]:
    filters: list[str] = []
    if from_time:
        filters.append(f"{column} >= parseDateTime64BestEffort({sql_quote(from_time)}, 3)")
    if to_time:
        filters.append(f"{column} <= parseDateTime64BestEffort({sql_quote(to_time)}, 3)")
    return filters


def session_card(from_time: str | None, to_time: str | None, agent_name: str | None = None) -> dict[str, Any]:
    from_expr = f"parseDateTime64BestEffort({sql_quote(from_time)}, 3)" if from_time else "now64(3) - INTERVAL 24 HOUR"
    to_expr = f"parseDateTime64BestEffort({sql_quote(to_time)}, 3)" if to_time else "now64(3)"
    agent_where = agent_name_condition(agent_name)
    session_rows = ch_query_json(
        f"""
        WITH bounds AS (
            SELECT
                {from_expr} AS from_ts,
                {to_expr} AS to_ts,
                from_ts - toIntervalSecond(dateDiff('second', from_ts, to_ts)) AS previous_from_ts
        ), current_sessions AS (
            SELECT
                'current' AS window,
                session_id,
                max(error_count) AS error_count
            FROM sessions, bounds
            WHERE session_id != ''{agent_where}
              AND ended_at >= from_ts
              AND started_at < to_ts
            GROUP BY session_id
        ), previous_sessions AS (
            SELECT
                'previous' AS window,
                session_id,
                max(error_count) AS error_count
            FROM sessions, bounds
            WHERE session_id != ''{agent_where}
              AND ended_at >= previous_from_ts
              AND started_at < from_ts
            GROUP BY session_id
        )
        SELECT window, session_id, error_count FROM current_sessions
        UNION ALL
        SELECT window, session_id, error_count FROM previous_sessions
        """
    )
    duration_rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts
        SELECT session_id, sum(duration_ms) AS duration_ms
        FROM traces
        WHERE session_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
        GROUP BY session_id
        """
    )
    token_rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts
        SELECT session_id, sum(total_tokens) AS total_tokens
        FROM traces
        WHERE session_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
        GROUP BY session_id
        """
    )
    trend_rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts
        SELECT
            toString(fromUnixTimestamp64Milli(t)) AS ts,
            t,
            count() AS value
        FROM (
            SELECT intDiv(toUnixTimestamp64Milli(started_at), 60000) * 60000 AS t
            FROM sessions
            WHERE session_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
        )
        GROUP BY t
        ORDER BY t ASC
        """
    )

    current_sessions: dict[str, dict[str, Any]] = {}
    previous_session_ids: set[str] = set()
    for row in session_rows:
        session_id = stringify(row.get("session_id", ""))
        if not session_id:
            continue
        if row.get("window") == "current":
            current_sessions[session_id] = row
        elif row.get("window") == "previous":
            previous_session_ids.add(session_id)

    current_session_ids = set(current_sessions)
    active_sessions = len(current_session_ids)
    previous_active_sessions = len(previous_session_ids)
    error_sessions = sum(1 for row in current_sessions.values() if to_int(row.get("error_count")) > 0)
    completed_sessions = active_sessions - error_sessions

    duration_by_session = {
        stringify(row.get("session_id", "")): to_int(row.get("duration_ms"))
        for row in duration_rows
        if stringify(row.get("session_id", "")) in current_session_ids
    }
    token_by_session = {
        stringify(row.get("session_id", "")): to_int(row.get("total_tokens"))
        for row in token_rows
        if stringify(row.get("session_id", "")) in current_session_ids
    }

    if previous_active_sessions == 0:
        active_sessions_delta_pct = 0 if active_sessions == 0 else 100
    else:
        active_sessions_delta_pct = (active_sessions - previous_active_sessions) / previous_active_sessions * 100

    return {
        "active_sessions": active_sessions,
        "active_sessions_delta_pct": float(active_sessions_delta_pct),
        "completion_rate": (completed_sessions / active_sessions) if active_sessions else 0,
        "avg_duration_ms": int(sum(duration_by_session.get(session_id, 0) for session_id in current_session_ids) / active_sessions) if active_sessions else 0,
        "avg_tokens_per_session": int(sum(token_by_session.get(session_id, 0) for session_id in current_session_ids) / active_sessions) if active_sessions else 0,
        "error_session_rate": (error_sessions / active_sessions) if active_sessions else 0,
        "sparkline": [{"ts": row.get("ts"), "t": to_int(row.get("t")), "value": to_int(row.get("value"))} for row in trend_rows],
        "meta": {"from": from_time, "to": to_time},
    }


TOKEN_PRICE_CNY_PER_TOKEN: list[tuple[str, float, float]] = [
    ("gpt-4o-mini", 0.00000108, 0.00000432),
    ("gpt-4o", 0.000018, 0.000072),
    ("gpt-4.1-mini", 0.00000288, 0.00001152),
    ("gpt-4.1", 0.0000144, 0.0000576),
    ("claude-sonnet-4", 0.0000216, 0.000108),
    ("claude-3-5-sonnet", 0.0000216, 0.000108),
    ("claude-3-7-sonnet", 0.0000216, 0.000108),
    ("claude-3-haiku", 0.0000018, 0.000009),
    ("gemini-1.5-pro", 0.000009, 0.000036),
    ("gemini-1.5-flash", 0.00000054, 0.00000216),
    ("deepseek-chat", 0.000001944, 0.00000792),
    ("deepseek-reasoner", 0.00000396, 0.000015768),
    ("qwen-plus", 0.00000288, 0.00000864),
    ("qwen-turbo", 0.00000036, 0.00000144),
    ("doubao", 0.000000576, 0.000001152),
    ("ark-code-latest", 0.00000576, 0.0000144),
    ("default", 0.00000576, 0.0000144),
]


def token_price_for_model(model_name: str | None) -> tuple[float, float]:
    normalized = stringify(model_name or "").lower()
    for key, input_price, output_price in TOKEN_PRICE_CNY_PER_TOKEN:
        if key == "default":
            continue
        if key in normalized:
            return input_price, output_price
    return 0.00000576, 0.0000144


def _round_cny(value: float) -> float:
    return round(float(value), 6)


def token_card(from_time: str | None, to_time: str | None, agent_name: str | None = None) -> dict[str, Any]:
    from_expr = f"parseDateTime64BestEffort({sql_quote(from_time)}, 3)" if from_time else "now64(3) - INTERVAL 24 HOUR"
    to_expr = f"parseDateTime64BestEffort({sql_quote(to_time)}, 3)" if to_time else "now64(3)"
    agent_where = agent_name_condition(agent_name)
    kpi_rows = ch_query_json(
        f"""
        WITH bounds AS (
            SELECT
                {from_expr} AS from_ts,
                {to_expr} AS to_ts,
                from_ts - toIntervalSecond(dateDiff('second', from_ts, to_ts)) AS previous_from_ts
        ), current_llm_calls AS (
            SELECT
                'current' AS window,
                count() AS active_llm_calls,
                sum(input_tokens) AS input_tokens,
                sum(output_tokens) AS output_tokens,
                sum(total_tokens) AS total_tokens
            FROM observations, bounds
            WHERE (name = 'llm.call' OR observation_type = 'llm.call' OR observation_type = 'llm'){agent_where}
              AND started_at >= from_ts
              AND started_at < to_ts
        ), previous_llm_calls AS (
            SELECT
                'previous' AS window,
                count() AS active_llm_calls,
                sum(input_tokens) AS input_tokens,
                sum(output_tokens) AS output_tokens,
                sum(total_tokens) AS total_tokens
            FROM observations, bounds
            WHERE (name = 'llm.call' OR observation_type = 'llm.call' OR observation_type = 'llm'){agent_where}
              AND started_at >= previous_from_ts
              AND started_at < from_ts
        )
        SELECT window, active_llm_calls, input_tokens, output_tokens, total_tokens FROM current_llm_calls
        UNION ALL
        SELECT window, active_llm_calls, input_tokens, output_tokens, total_tokens FROM previous_llm_calls
        """
    )
    model_rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts
        SELECT
            model_provider,
            model_name,
            count() AS active_llm_calls,
            sum(input_tokens) AS input_tokens,
            sum(output_tokens) AS output_tokens,
            sum(total_tokens) AS total_tokens
        FROM observations
        WHERE (name = 'llm.call' OR observation_type = 'llm.call' OR observation_type = 'llm'){agent_where} AND started_at >= from_ts AND started_at < to_ts
        GROUP BY model_provider, model_name
        ORDER BY total_tokens DESC
        """
    )
    trend_rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts
        SELECT
            toString(fromUnixTimestamp64Milli(t)) AS ts,
            t,
            sum(total_tokens) AS value,
            sum(input_tokens) AS input_tokens,
            sum(output_tokens) AS output_tokens
        FROM (
            SELECT
                intDiv(toUnixTimestamp64Milli(started_at), 60000) * 60000 AS t,
                input_tokens,
                output_tokens,
                total_tokens
            FROM observations
            WHERE (name = 'llm.call' OR observation_type = 'llm.call' OR observation_type = 'llm'){agent_where} AND started_at >= from_ts AND started_at < to_ts
        )
        GROUP BY t
        ORDER BY t ASC
        """
    )

    current = next((row for row in kpi_rows if row.get("window") == "current"), {})
    previous = next((row for row in kpi_rows if row.get("window") == "previous"), {})
    active_llm_calls = to_int(current.get("active_llm_calls"))
    total_tokens = to_int(current.get("total_tokens"))
    input_tokens = to_int(current.get("input_tokens"))
    output_tokens = to_int(current.get("output_tokens"))
    previous_total_tokens = to_int(previous.get("total_tokens"))

    if previous_total_tokens == 0:
        token_delta_pct = 0 if total_tokens == 0 else 100
    else:
        token_delta_pct = (total_tokens - previous_total_tokens) / previous_total_tokens * 100

    cost_by_model: list[dict[str, Any]] = []
    for row in model_rows:
        row_input_tokens = to_int(row.get("input_tokens"))
        row_output_tokens = to_int(row.get("output_tokens"))
        input_price, output_price = token_price_for_model(stringify(row.get("model_name", "")))
        input_cost = row_input_tokens * input_price
        output_cost = row_output_tokens * output_price
        cost_by_model.append(
            {
                "model_provider": stringify(row.get("model_provider", "")),
                "model_name": stringify(row.get("model_name", "")),
                "active_llm_calls": to_int(row.get("active_llm_calls")),
                "input_tokens": row_input_tokens,
                "output_tokens": row_output_tokens,
                "total_tokens": to_int(row.get("total_tokens")),
                "input_cost_cny": _round_cny(input_cost),
                "output_cost_cny": _round_cny(output_cost),
                "cost_cny": _round_cny(input_cost + output_cost),
            }
        )
    cost_by_model.sort(key=lambda row: row["cost_cny"], reverse=True)
    total_cost_cny = _round_cny(sum(float(row["cost_cny"]) for row in cost_by_model))

    return {
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_cost_cny": total_cost_cny,
        "avg_tokens_per_llm_call": int(total_tokens / active_llm_calls) if active_llm_calls else 0,
        "active_llm_calls": active_llm_calls,
        "token_delta_pct": float(token_delta_pct),
        "sparkline": [
            {
                "ts": row.get("ts"),
                "t": to_int(row.get("t")),
                "value": to_int(row.get("value")),
                "input_tokens": to_int(row.get("input_tokens")),
                "output_tokens": to_int(row.get("output_tokens")),
            }
            for row in trend_rows
        ],
        "cost_by_model": cost_by_model,
        "meta": {"from": from_time, "to": to_time},
    }


TOP_RANK_SORTS = {
    "tokens": ("total_tokens", "Token"),
    "duration": ("duration_ms", "时长"),
    "errors": ("error_count", "异常"),
    "latest": ("updated_at", "最新"),
}


TOP_SESSION_SORTS = TOP_RANK_SORTS


def normalize_top_rank_sort(value: str | None) -> str:
    normalized = stringify(value or "latest").lower().strip()
    if normalized not in TOP_RANK_SORTS:
        return "latest"
    return normalized


def normalize_top_session_sort(value: str | None) -> str:
    return normalize_top_rank_sort(value)


def normalize_search_param(value: str | None) -> str:
    value = stringify(value or "").strip()
    if len(value) > 256:
        raise ValueError("invalid_search_query")
    return value


def sql_search_literal(value: str) -> str:
    return sql_quote(f"%{value}%")


def top_sessions(
    from_time: str | None,
    to_time: str | None,
    sort_by: str = "latest",
    limit: int = 5,
    offset: int = 0,
    query: str | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    sort_by = normalize_top_session_sort(sort_by)
    sort_column, sort_label = TOP_SESSION_SORTS[sort_by]
    limit = normalize_limit_param(str(limit), 5, 100)
    offset = max(0, to_int(offset))
    query = normalize_search_param(query)
    agent_name = normalize_search_param(agent_name)
    agent_where = agent_name_condition(agent_name)
    query_limit = limit + 1
    from_expr = f"parseDateTime64BestEffort({sql_quote(from_time)}, 3)" if from_time else "now64(3) - INTERVAL 24 HOUR"
    to_expr = f"parseDateTime64BestEffort({sql_quote(to_time)}, 3)" if to_time else "now64(3)"
    query_literal = sql_quote(query) if query else "''"
    outer_filters = []
    if agent_name:
        outer_filters.append(agent_name_filter_sql(agent_name) or "")
    if sort_by == "errors":
        outer_filters.append("error_count > 0")
    if query:
        outer_filters.append(
            "(positionCaseInsensitive(session_id, {q}) > 0 OR "
            "positionCaseInsensitive(agent_name, {q}) > 0 OR "
            "session_id IN ("
            "SELECT DISTINCT session_id FROM observations "
            "WHERE session_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts AND ("
            "positionCaseInsensitive(input_preview, {q}) > 0 OR "
            "positionCaseInsensitive(tool_input_preview, {q}) > 0 OR "
            "positionCaseInsensitive(output_preview, {q}) > 0 OR "
            "positionCaseInsensitive(tool_output_preview, {q}) > 0"
            ")"
            "))".format(q=query_literal, agent_where=agent_where)
        )
    outer_filter = "WHERE " + " AND ".join(outer_filters) if outer_filters else ""
    rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts,
        ranked AS (
            SELECT *
            FROM (
                SELECT
                    session_id,
                    anyLast(agent_name) AS agent_name,
                    min(started_at) AS started_at,
                    max(ended_at) AS ended_at,
                    sum(duration_ms) AS duration_ms,
                    uniqExact(trace_id) AS trace_count,
                    sum(observation_count) AS observation_count,
                    sum(error_count) AS error_count,
                    sum(input_tokens) AS input_tokens,
                    sum(output_tokens) AS output_tokens,
                    sum(total_tokens) AS total_tokens,
                    max(updated_at) AS updated_at
                FROM (
                    SELECT *, row_number() OVER (PARTITION BY project_id, environment, trace_id ORDER BY updated_at DESC) AS rn
                    FROM traces
                    WHERE session_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
                      {f"AND agent_name = {sql_quote(agent_name)}" if agent_name else ""}
                )
                WHERE rn = 1
                GROUP BY session_id
            )
            {outer_filter}
            ORDER BY {sort_column} DESC, updated_at DESC
            LIMIT {query_limit} OFFSET {offset}
        ), previews AS (
            SELECT
                session_id,
                argMinIf(input_preview, started_at, input_preview != '') AS input_preview,
                argMaxIf(output_preview, ended_at, output_preview != '') AS output_preview,
                argMinIf(tool_input_preview, started_at, tool_input_preview != '') AS tool_input_preview,
                argMaxIf(tool_output_preview, ended_at, tool_output_preview != '') AS tool_output_preview,
                countIf(observation_type = 'llm') AS llm_call_count,
                countIf(observation_type = 'tool') AS tool_call_count,
                countIf(
                    positionCaseInsensitive(observation_type, 'retriev') > 0 OR
                    positionCaseInsensitive(observation_type, 'knowledge') > 0 OR
                    positionCaseInsensitive(observation_type, 'rag') > 0 OR
                    positionCaseInsensitive(name, 'retriev') > 0 OR
                    positionCaseInsensitive(name, 'knowledge') > 0 OR
                    positionCaseInsensitive(name, 'rag') > 0 OR
                    positionCaseInsensitive(name, 'vector') > 0 OR
                    positionCaseInsensitive(tool_name, 'retriev') > 0 OR
                    positionCaseInsensitive(tool_name, 'knowledge') > 0 OR
                    positionCaseInsensitive(tool_name, 'rag') > 0 OR
                    positionCaseInsensitive(tool_name, 'vector') > 0
                ) AS knowledge_call_count
            FROM observations
            WHERE session_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
            GROUP BY session_id
        )
        SELECT ranked.*, previews.input_preview, previews.output_preview, previews.tool_input_preview, previews.tool_output_preview,
               previews.llm_call_count, previews.tool_call_count, previews.knowledge_call_count
        FROM ranked
        LEFT JOIN previews USING session_id
        ORDER BY {sort_column} DESC, updated_at DESC
        """
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "sort": sort_by,
        "sort_label": sort_label,
        "sessions": rows,
        "meta": {"from": from_time, "to": to_time, "limit": limit, "offset": offset, "has_more": has_more},
    }


def top_traces(
    from_time: str | None,
    to_time: str | None,
    sort_by: str = "latest",
    limit: int = 5,
    offset: int = 0,
    query: str | None = None,
    session_id: str | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    sort_by = normalize_top_rank_sort(sort_by)
    sort_column, sort_label = TOP_RANK_SORTS[sort_by]
    limit = normalize_limit_param(str(limit), 5, 100)
    offset = max(0, to_int(offset))
    query = normalize_search_param(query)
    session_id = normalize_search_param(session_id)
    agent_name = normalize_search_param(agent_name)
    agent_where = agent_name_condition(agent_name)
    query_limit = limit + 1
    from_expr = f"parseDateTime64BestEffort({sql_quote(from_time)}, 3)" if from_time else "now64(3) - INTERVAL 24 HOUR"
    to_expr = f"parseDateTime64BestEffort({sql_quote(to_time)}, 3)" if to_time else "now64(3)"
    query_literal = sql_quote(query) if query else "''"
    session_literal = sql_quote(session_id) if session_id else "''"
    outer_filters = []
    if agent_name:
        outer_filters.append(agent_name_filter_sql(agent_name) or "")
    if sort_by == "errors":
        outer_filters.append("error_count > 0")
    if session_id:
        outer_filters.append("session_id = {s}".format(s=session_literal))
    if query:
        outer_filters.append(
            "(positionCaseInsensitive(trace_id, {q}) > 0 OR "
            "positionCaseInsensitive(session_id, {q}) > 0 OR "
            "positionCaseInsensitive(root_span_name, {q}) > 0 OR "
            "positionCaseInsensitive(agent_name, {q}) > 0 OR "
            "trace_id IN ("
            "SELECT DISTINCT trace_id FROM observations "
            "WHERE trace_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts AND ("
            "positionCaseInsensitive(input_preview, {q}) > 0 OR "
            "positionCaseInsensitive(tool_input_preview, {q}) > 0 OR "
            "positionCaseInsensitive(output_preview, {q}) > 0 OR "
            "positionCaseInsensitive(tool_output_preview, {q}) > 0"
            ")"
            "))".format(q=query_literal, agent_where=agent_where)
        )
    outer_filter = "WHERE " + " AND ".join(outer_filters) if outer_filters else ""
    rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts,
        ranked AS (
            SELECT *
            FROM (
                SELECT
                    project_id,
                    environment,
                    trace_id,
                    session_id,
                    root_span_name,
                    agent_name,
                    started_at,
                    ended_at,
                    duration_ms,
                    observation_count,
                    error_count,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    status_code,
                    updated_at
                FROM (
                    SELECT *, row_number() OVER (PARTITION BY project_id, environment, trace_id ORDER BY updated_at DESC) AS rn
                    FROM traces
                    WHERE trace_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
                      {f"AND agent_name = {sql_quote(agent_name)}" if agent_name else ""}
                )
                WHERE rn = 1
            )
            {outer_filter}
            ORDER BY {sort_column} DESC, updated_at DESC
            LIMIT {query_limit} OFFSET {offset}
        ), previews AS (
            SELECT
                trace_id,
                argMinIf(input_preview, started_at, input_preview != '') AS input_preview,
                argMaxIf(output_preview, ended_at, output_preview != '') AS output_preview,
                argMinIf(tool_input_preview, started_at, tool_input_preview != '') AS tool_input_preview,
                argMaxIf(tool_output_preview, ended_at, tool_output_preview != '') AS tool_output_preview,
                countIf(observation_type = 'llm') AS llm_call_count,
                countIf(observation_type = 'tool') AS tool_call_count,
                countIf(
                    positionCaseInsensitive(observation_type, 'retriev') > 0 OR
                    positionCaseInsensitive(observation_type, 'knowledge') > 0 OR
                    positionCaseInsensitive(observation_type, 'rag') > 0 OR
                    positionCaseInsensitive(name, 'retriev') > 0 OR
                    positionCaseInsensitive(name, 'knowledge') > 0 OR
                    positionCaseInsensitive(name, 'rag') > 0 OR
                    positionCaseInsensitive(name, 'vector') > 0 OR
                    positionCaseInsensitive(tool_name, 'retriev') > 0 OR
                    positionCaseInsensitive(tool_name, 'knowledge') > 0 OR
                    positionCaseInsensitive(tool_name, 'rag') > 0 OR
                    positionCaseInsensitive(tool_name, 'vector') > 0
                ) AS knowledge_call_count
            FROM observations
            WHERE trace_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
              {f"AND agent_name = {sql_quote(agent_name)}" if agent_name else ""}
            GROUP BY trace_id
        )
        SELECT ranked.*, previews.input_preview, previews.output_preview, previews.tool_input_preview, previews.tool_output_preview,
               previews.llm_call_count, previews.tool_call_count, previews.knowledge_call_count
        FROM ranked
        LEFT JOIN previews USING trace_id
        ORDER BY {sort_column} DESC, updated_at DESC
        """
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "sort": sort_by,
        "sort_label": sort_label,
        "traces": rows,
        "meta": {"from": from_time, "to": to_time, "limit": limit, "offset": offset, "has_more": has_more},
    }


def trace_card(from_time: str | None, to_time: str | None, agent_name: str | None = None) -> dict[str, Any]:
    from_expr = f"parseDateTime64BestEffort({sql_quote(from_time)}, 3)" if from_time else "now64(3) - INTERVAL 24 HOUR"
    to_expr = f"parseDateTime64BestEffort({sql_quote(to_time)}, 3)" if to_time else "now64(3)"
    agent_where = agent_name_condition(agent_name)
    kpi_rows = ch_query_json(
        f"""
        WITH bounds AS (
            SELECT
                {from_expr} AS from_ts,
                {to_expr} AS to_ts,
                from_ts - toIntervalSecond(dateDiff('second', from_ts, to_ts)) AS previous_from_ts
        ), current_traces AS (
            SELECT
                'current' AS window,
                trace_id,
                max(duration_ms) AS duration_ms,
                max(total_tokens) AS total_tokens,
                max(error_count) AS error_count
            FROM traces, bounds
            WHERE trace_id != ''{agent_where}
              AND started_at >= from_ts
              AND started_at < to_ts
            GROUP BY trace_id
        ), previous_traces AS (
            SELECT
                'previous' AS window,
                trace_id,
                max(duration_ms) AS duration_ms,
                max(total_tokens) AS total_tokens,
                max(error_count) AS error_count
            FROM traces, bounds
            WHERE trace_id != ''{agent_where}
              AND started_at >= previous_from_ts
              AND started_at < from_ts
            GROUP BY trace_id
        ), combined AS (
            SELECT window, trace_id, duration_ms, total_tokens, error_count FROM current_traces
            UNION ALL
            SELECT window, trace_id, duration_ms, total_tokens, error_count FROM previous_traces
        )
        SELECT
            window,
            uniqExact(trace_id) AS active_traces,
            avg(duration_ms) AS avg_duration_ms,
            avg(total_tokens) AS avg_tokens_per_trace,
            countIf(error_count > 0) AS error_traces
        FROM combined
        GROUP BY window
        """
    )
    trend_rows = ch_query_json(
        f"""
        WITH {from_expr} AS from_ts, {to_expr} AS to_ts
        SELECT
            toString(fromUnixTimestamp64Milli(t)) AS ts,
            t,
            uniqExact(trace_id) AS value
        FROM (
            SELECT trace_id, intDiv(toUnixTimestamp64Milli(started_at), 60000) * 60000 AS t
            FROM traces
            WHERE trace_id != ''{agent_where} AND started_at >= from_ts AND started_at < to_ts
        )
        GROUP BY t
        ORDER BY t ASC
        """
    )

    current = next((row for row in kpi_rows if row.get("window") == "current"), {})
    previous = next((row for row in kpi_rows if row.get("window") == "previous"), {})
    active_traces = to_int(current.get("active_traces"))
    previous_active_traces = to_int(previous.get("active_traces"))
    error_traces = to_int(current.get("error_traces"))

    if previous_active_traces == 0:
        active_traces_delta_pct = 0 if active_traces == 0 else 100
    else:
        active_traces_delta_pct = (active_traces - previous_active_traces) / previous_active_traces * 100

    return {
        "active_traces": active_traces,
        "active_traces_delta_pct": float(active_traces_delta_pct),
        "avg_duration_ms": int(float(current.get("avg_duration_ms") or 0)) if active_traces else 0,
        "avg_tokens_per_trace": int(float(current.get("avg_tokens_per_trace") or 0)) if active_traces else 0,
        "error_trace_rate": (error_traces / active_traces) if active_traces else 0,
        "sparkline": [{"ts": row.get("ts"), "t": to_int(row.get("t")), "value": to_int(row.get("value"))} for row in trend_rows],
        "meta": {"from": from_time, "to": to_time},
    }


def parse_time_range(params: dict[str, list[str]]) -> tuple[str | None, str | None]:
    return (
        normalize_time_param((params.get("from") or [None])[0], "from"),
        normalize_time_param((params.get("to") or [None])[0], "to"),
    )


def latest_sessions(limit: int = 100, from_time: str | None = None, to_time: str | None = None, agent_name: str | None = None) -> list[dict[str, Any]]:
    filters = time_filters("started_at", from_time, to_time)
    if agent_name:
        filters.append(agent_name_filter_sql(agent_name) or "")
    where = "WHERE " + " AND ".join(filters) if filters else ""
    obs_filters = time_filters("started_at", from_time, to_time)
    if agent_name:
        obs_filters.append(agent_name_filter_sql(agent_name) or "")
    obs_time_where = " AND " + " AND ".join(obs_filters) if obs_filters else ""
    return ch_query_json(
        f"""
        WITH latest AS (
            SELECT project_id, environment, session_id, user_id, agent_name, started_at, ended_at, duration_ms,
                   trace_count, observation_count, error_count, input_tokens, output_tokens, total_tokens, created_at, updated_at
            FROM (
                SELECT *, row_number() OVER (PARTITION BY project_id, environment, session_id ORDER BY updated_at DESC) AS rn
                FROM sessions
                {where}
            ) WHERE rn = 1
        ), previews AS (
            SELECT
                session_id,
                argMinIf(input_preview, started_at, input_preview != '') AS input_preview,
                argMaxIf(output_preview, ended_at, output_preview != '') AS output_preview,
                argMinIf(tool_input_preview, started_at, tool_input_preview != '') AS tool_input_preview,
                argMaxIf(tool_output_preview, ended_at, tool_output_preview != '') AS tool_output_preview,
                countIf(observation_type = 'llm') AS llm_call_count,
                countIf(observation_type = 'tool') AS tool_call_count,
                countIf(
                    positionCaseInsensitive(observation_type, 'retriev') > 0 OR
                    positionCaseInsensitive(observation_type, 'knowledge') > 0 OR
                    positionCaseInsensitive(observation_type, 'rag') > 0 OR
                    positionCaseInsensitive(name, 'retriev') > 0 OR
                    positionCaseInsensitive(name, 'knowledge') > 0 OR
                    positionCaseInsensitive(name, 'rag') > 0 OR
                    positionCaseInsensitive(name, 'vector') > 0 OR
                    positionCaseInsensitive(tool_name, 'retriev') > 0 OR
                    positionCaseInsensitive(tool_name, 'knowledge') > 0 OR
                    positionCaseInsensitive(tool_name, 'rag') > 0 OR
                    positionCaseInsensitive(tool_name, 'vector') > 0
                ) AS knowledge_call_count
            FROM observations
            WHERE session_id != ''{obs_time_where}
            GROUP BY session_id
        )
        SELECT latest.*, previews.input_preview, previews.output_preview, previews.tool_input_preview, previews.tool_output_preview,
               previews.llm_call_count, previews.tool_call_count, previews.knowledge_call_count
        FROM latest
        LEFT JOIN previews USING session_id
        ORDER BY latest.updated_at DESC
        LIMIT {int(limit)}
        """
    )


def trace_detail(trace_id: str, from_time: str | None = None, to_time: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
    quoted = sql_quote(trace_id)
    agent_filter = agent_name_condition(agent_name)
    obs_base_filters = time_filters("started_at", from_time, to_time)
    if agent_name:
        obs_base_filters.append(agent_name_filter_sql(agent_name) or "")
    obs_filters = " AND ".join(obs_base_filters)
    obs_time_where = f" AND {obs_filters}" if obs_filters else ""
    summaries = ch_query_json(
        f"""
        SELECT project_id, environment, trace_id, session_id, root_span_name, agent_name, started_at, ended_at,
               duration_ms, observation_count, error_count, input_tokens, output_tokens, total_tokens, status_code, created_at, updated_at
        FROM traces
        WHERE trace_id = {quoted}{agent_filter}
        ORDER BY updated_at DESC
        LIMIT 1
        """
    )
    observations = ch_query_json(
        f"""
        SELECT project_id, environment, trace_id, span_id, parent_span_id, session_id, observation_type, name, kind,
               started_at, ended_at, duration_ms, status_code, status_message, agent_name, model_provider, model_name,
               input_tokens, output_tokens, total_tokens, input_preview, output_preview, tool_name, tool_input_preview,
               tool_output_preview, attributes, resource_attributes, source, ingested_at
        FROM observations
        WHERE trace_id = {quoted}
        {obs_time_where}
        ORDER BY started_at ASC, span_id ASC
        """
    )
    return {"trace": summaries[0] if summaries else None, "observations": observations}


def search_by_session(session_id: str, from_time: str | None = None, to_time: str | None = None, agent_name: str | None = None) -> list[dict[str, Any]]:
    traces = top_traces(from_time, to_time, "latest", 200, 0, query=None, session_id=session_id, agent_name=agent_name).get("traces", [])
    return sorted(traces, key=lambda row: stringify(row.get("started_at") or row.get("updated_at") or row.get("ended_at") or ""))


def sql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-observability-backend/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict[str, Any]:
        length = to_int(self.headers.get("Content-Length"), 0)
        body = self.rfile.read(length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _auth_payload(self) -> dict[str, Any]:
        return verify_jwt(self.headers.get("Authorization"))

    def _handle_project_get(self, parsed) -> bool:
        m = re.fullmatch(r"/api/projects/([^/]+)/(sessions|traces|search)", parsed.path)
        detail_m = re.fullmatch(r"/api/projects/([^/]+)/traces/([^/]+)", parsed.path)
        overview_m = re.fullmatch(r"/api/projects/([^/]+)/overview/(session-card|trace-card|token-card|top-sessions|top-traces)", parsed.path)
        if not (m or detail_m or overview_m):
            return False
        jwt_payload = self._auth_payload()
        project_id = urllib.parse.unquote((m or detail_m or overview_m).group(1))
        project = require_project_owner(project_id, jwt_payload)
        params = urllib.parse.parse_qs(parsed.query)
        from_time, to_time = parse_time_range(params)
        agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
        with project_database(stringify(project["ck_database"])):
            if m:
                kind = m.group(2)
                if kind == "sessions":
                    limit = normalize_limit_param((params.get("limit") or [None])[0], 100)
                    self._send_json(200, {"sessions": latest_sessions(limit, from_time, to_time, agent_name=agent_name), "meta": time_meta(from_time, to_time, limit)})
                elif kind == "traces":
                    sort_by = (params.get("sort") or ["latest"])[0]
                    limit = normalize_limit_param((params.get("limit") or ["100"])[0], 100, 500)
                    offset = max(0, to_int((params.get("offset") or ["0"])[0]))
                    query = (params.get("q") or params.get("query") or [""])[0]
                    session_id = (params.get("session_id") or [""])[0]
                    self._send_json(200, top_traces(from_time, to_time, sort_by, limit, offset, query=query, session_id=session_id, agent_name=agent_name))
                else:
                    session_id = (params.get("session_id") or [""])[0]
                    if not session_id:
                        self._send_json(400, {"error": "missing_session_id"})
                    else:
                        self._send_json(200, {"traces": search_by_session(session_id, from_time, to_time, agent_name=agent_name), "meta": time_meta(from_time, to_time)})
            elif detail_m:
                trace_id = urllib.parse.unquote(detail_m.group(2))
                detail = trace_detail(trace_id, from_time, to_time, agent_name=agent_name)
                detail["meta"] = time_meta(from_time, to_time)
                self._send_json(200 if detail["trace"] or detail["observations"] else 404, detail if detail["trace"] or detail["observations"] else {"error": "trace_not_found", "trace_id": trace_id})
            else:
                endpoint = overview_m.group(2)
                if endpoint == "session-card":
                    self._send_json(200, session_card(from_time, to_time, agent_name=agent_name))
                elif endpoint == "trace-card":
                    self._send_json(200, trace_card(from_time, to_time, agent_name=agent_name))
                elif endpoint == "token-card":
                    self._send_json(200, token_card(from_time, to_time, agent_name=agent_name))
                elif endpoint == "top-sessions":
                    self._send_json(200, top_sessions(from_time, to_time, (params.get("sort") or ["latest"])[0], normalize_limit_param((params.get("limit") or ["5"])[0], 5, 100), max(0, to_int((params.get("offset") or ["0"])[0])), query=(params.get("q") or params.get("query") or [""])[0], agent_name=agent_name))
                else:
                    self._send_json(200, top_traces(from_time, to_time, (params.get("sort") or ["latest"])[0], normalize_limit_param((params.get("limit") or ["5"])[0], 5, 100), max(0, to_int((params.get("offset") or ["0"])[0])), query=(params.get("q") or params.get("query") or [""])[0], session_id=(params.get("session_id") or [""])[0], agent_name=agent_name))
        return True

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/health":
                self._send_json(200, {"ok": True, "service": "backend-api", "clickhouse_url": CLICKHOUSE_URL})
            elif parsed.path == "/api/me":
                jwt_payload = self._auth_payload()
                rows = ch_query_json(f"SELECT * FROM {META_DB}.users WHERE user_id={sql_quote(stringify(jwt_payload.get('sub')))} AND status='active' ORDER BY updated_at DESC LIMIT 1")
                self._send_json(200, {"user": public_user(rows[0]) if rows else None})
            elif parsed.path == "/api/projects":
                jwt_payload = self._auth_payload()
                self._send_json(200, {"projects": projects_for_user(stringify(jwt_payload.get("sub")))})
            elif re.fullmatch(r"/api/projects/[^/]+/api-keys", parsed.path):
                jwt_payload = self._auth_payload()
                project_id = urllib.parse.unquote(parsed.path.split("/")[3])
                require_project_owner(project_id, jwt_payload)
                self._send_json(200, {"api_keys": list_api_keys(project_id)})
            elif re.fullmatch(r"/api/projects/[^/]+/agents", parsed.path):
                jwt_payload = self._auth_payload()
                project_id = urllib.parse.unquote(parsed.path.split("/")[3])
                require_project_owner(project_id, jwt_payload)
                self._send_json(200, {"agents": list_agents(project_id)})
            elif self._handle_project_get(parsed):
                return
            elif parsed.path == "/sessions":
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                limit = normalize_limit_param((params.get("limit") or [None])[0], 100)
                self._send_json(200, {"sessions": latest_sessions(limit, from_time, to_time, agent_name=agent_name), "meta": time_meta(from_time, to_time, limit)})
            elif parsed.path == "/overview/session-card":
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                self._send_json(200, session_card(from_time, to_time, agent_name=agent_name))
            elif parsed.path == "/overview/trace-card":
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                self._send_json(200, trace_card(from_time, to_time, agent_name=agent_name))
            elif parsed.path == "/overview/token-card":
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                self._send_json(200, token_card(from_time, to_time, agent_name=agent_name))
            elif parsed.path == "/overview/top-sessions":
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                sort_by = (params.get("sort") or ["latest"])[0]
                limit = normalize_limit_param((params.get("limit") or ["5"])[0], 5, 100)
                offset = max(0, to_int((params.get("offset") or ["0"])[0]))
                query = (params.get("q") or params.get("query") or [""])[0]
                self._send_json(200, top_sessions(from_time, to_time, sort_by, limit, offset, query=query))
            elif parsed.path == "/overview/top-traces":
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                sort_by = (params.get("sort") or ["latest"])[0]
                limit = normalize_limit_param((params.get("limit") or ["5"])[0], 5, 100)
                offset = max(0, to_int((params.get("offset") or ["0"])[0]))
                query = (params.get("q") or params.get("query") or [""])[0]
                session_id = (params.get("session_id") or [""])[0]
                self._send_json(200, top_traces(from_time, to_time, sort_by, limit, offset, query=query, session_id=session_id, agent_name=agent_name))
            elif parsed.path.startswith("/traces/"):
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                trace_id = urllib.parse.unquote(parsed.path[len("/traces/") :])
                detail = trace_detail(trace_id, from_time, to_time, agent_name=agent_name)
                detail["meta"] = time_meta(from_time, to_time)
                if detail["trace"] is None and not detail["observations"]:
                    self._send_json(404, {"error": "trace_not_found", "trace_id": trace_id})
                else:
                    self._send_json(200, detail)
            elif parsed.path == "/search":
                params = urllib.parse.parse_qs(parsed.query)
                from_time, to_time = parse_time_range(params)
                agent_name = normalize_search_param((params.get("agent_name") or [""])[0])
                session_id = (params.get("session_id") or [""])[0]
                if not session_id:
                    self._send_json(400, {"error": "missing_session_id"})
                else:
                    self._send_json(200, {"traces": search_by_session(session_id, from_time, to_time, agent_name=agent_name), "meta": time_meta(from_time, to_time)})
            else:
                self._send_json(404, {"error": "not_found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self._send_json(403 if str(exc) == "forbidden" else 401, {"error": str(exc)})
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/auth/phone/code":
                payload = self._read_json_body()
                self._send_json(200, request_phone_code(stringify(payload.get("phone")), payload.get("country_code"), self.client_address[0], self.headers.get("User-Agent", "")))
                return
            if parsed.path == "/api/auth/phone/login":
                payload = self._read_json_body()
                self._send_json(200, login_with_phone_code(stringify(payload.get("phone")), payload.get("country_code"), stringify(payload.get("code"))))
                return
            if parsed.path == "/api/projects":
                jwt_payload = self._auth_payload()
                payload = self._read_json_body()
                project = create_project(stringify(jwt_payload.get("sub")), stringify(payload.get("name") or "默认项目"))
                self._send_json(201, {"project": public_project(project), "api_key": project["api_keys"][0]})
                return
            m_key = re.fullmatch(r"/api/projects/([^/]+)/api-keys", parsed.path)
            if m_key:
                jwt_payload = self._auth_payload()
                project_id = urllib.parse.unquote(m_key.group(1))
                require_project_owner(project_id, jwt_payload)
                payload = self._read_json_body()
                self._send_json(201, {"api_key": regenerate_api_key(project_id, stringify(payload.get("name") or "默认接入 Key"))})
                return
            m_agent_key = re.fullmatch(r"/api/projects/([^/]+)/agents/([^/]+)/api-key", parsed.path)
            if m_agent_key:
                jwt_payload = self._auth_payload()
                project_id = urllib.parse.unquote(m_agent_key.group(1))
                agent_id = urllib.parse.unquote(m_agent_key.group(2))
                require_project_owner(project_id, jwt_payload)
                payload = self._read_json_body()
                key = regenerate_agent_api_key(project_id, agent_id, stringify(payload.get("name") or "Agent 接入 Key"))
                self._send_json(201, {"api_key": key})
                return
            m_agent = re.fullmatch(r"/api/projects/([^/]+)/agents", parsed.path)
            if m_agent:
                jwt_payload = self._auth_payload()
                project_id = urllib.parse.unquote(m_agent.group(1))
                require_project_owner(project_id, jwt_payload)
                payload = self._read_json_body()
                self._send_json(201, {"agent": create_agent(project_id, stringify(payload.get("name")), stringify(payload.get("kind") or "custom"))})
                return
            if parsed.path in {"/ingest/otel/v1/traces", "/v1/traces"}:
                api_context = authenticate_api_key(self.headers.get("Authorization"))
                payload = self._read_json_body()
                with project_database(stringify(api_context["ck_database"])):
                    self._send_json(200, ingest_payload(payload, project_id=stringify(api_context["project_id"]), agent_name=stringify(api_context.get("agent_name"))))
                return
            self._send_json(404, {"error": "not_found"})
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self._send_json(403 if str(exc) == "forbidden" else 401, {"error": str(exc)})
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})

    def do_PATCH(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            agent_m = re.fullmatch(r"/api/projects/([^/]+)/agents/([^/]+)", parsed.path)
            if agent_m:
                jwt_payload = self._auth_payload()
                project_id = urllib.parse.unquote(agent_m.group(1))
                agent_id = urllib.parse.unquote(agent_m.group(2))
                require_project_owner(project_id, jwt_payload)
                payload = self._read_json_body()
                self._send_json(200, {"agent": rename_agent(project_id, agent_id, stringify(payload.get("name")))})
                return
            m = re.fullmatch(r"/api/projects/([^/]+)", parsed.path)
            if not m:
                self._send_json(404, {"error": "not_found"})
                return
            jwt_payload = self._auth_payload()
            project_id = urllib.parse.unquote(m.group(1))
            require_project_owner(project_id, jwt_payload)
            payload = self._read_json_body()
            sets = []
            if "name" in payload:
                sets.append(f"name={sql_quote(stringify(payload.get('name')))}")
            if "slug" in payload:
                sets.append(f"slug={sql_quote(stringify(payload.get('slug')))}")
            if not sets:
                self._send_json(400, {"error": "nothing_to_update"})
                return
            ch_post(f"ALTER TABLE {META_DB}.projects UPDATE {', '.join(sets)} WHERE project_id={sql_quote(project_id)}")
            self._send_json(200, {"ok": True})
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self._send_json(403 if str(exc) == "forbidden" else 401, {"error": str(exc)})
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            agent_m = re.fullmatch(r"/api/projects/([^/]+)/agents/([^/]+)", parsed.path)
            if agent_m:
                jwt_payload = self._auth_payload()
                project_id = urllib.parse.unquote(agent_m.group(1))
                agent_id = urllib.parse.unquote(agent_m.group(2))
                require_project_owner(project_id, jwt_payload)
                delete_agent(project_id, agent_id)
                self._send_json(200, {"ok": True})
                return
            m = re.fullmatch(r"/api/projects/([^/]+)/api-keys/([^/]+)", parsed.path)
            if not m:
                self._send_json(404, {"error": "not_found"})
                return
            jwt_payload = self._auth_payload()
            project_id = urllib.parse.unquote(m.group(1))
            api_key_id = urllib.parse.unquote(m.group(2))
            require_project_owner(project_id, jwt_payload)
            ch_post(f"ALTER TABLE {META_DB}.project_api_keys UPDATE status='revoked' WHERE project_id={sql_quote(project_id)} AND api_key_id={sql_quote(api_key_id)}")
            self._send_json(200, {"ok": True})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self._send_json(403 if str(exc) == "forbidden" else 401, {"error": str(exc)})
        except FileNotFoundError as exc:
            self._send_json(404, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": "internal_error", "detail": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8091")))
    args = parser.parse_args()
    try:
        init_meta_schema()
    except Exception as exc:
        print(f"warning: failed to initialize metadata schema: {exc}", file=sys.stderr, flush=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"backend-api listening on http://{args.host}:{args.port}, clickhouse={CLICKHOUSE_URL}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
