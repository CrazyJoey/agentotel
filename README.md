# Agent Observability MVP

Static, no-framework Agent Observability Console. The browser uses same-origin `/api/*`; `server.py` serves `index.html`, `styles.css`, and `app.js` on port `8088` and proxies query APIs to local backend services.

## Page structure

The MVP is now a dark, data-dense observability/debugging console inspired by Linear/Sentry/Datadog:

- Fixed top app bar: `Agent Observability`, `Live OTEL`, `CK storage`, `Time Range`, manual `Refresh`, `Last sync`.
- Left sidebar: Overview, Sessions, Traces, Errors, disabled Settings placeholder.
- KPI strip: Active sessions, Traces, Observations, Error rate, Tokens with selected time range summary.
- Control bar: session search by `session_id` or `agent`, plus `All / Errors only` status filter.
- Three-column drilldown:
  - Sessions inbox: highlights `session_id`, agent, last update, error badge, trace/obs/token/duration counts.
  - Trace list: selected session traces with status, duration, obs count, error count, token count, root span name.
  - Trace inspector: trace summary plus observation timeline.
- Observation timeline rows/cards: vertical line/dot, type pill (`llm/tool/span/event`), status pill, duration/token/model/tool metadata, preview blocks, and collapsible JSON for `attributes` and `resource_attributes`.
- Empty/loading/error states are product-style panels rather than raw debug text.
- Time filtering defaults to `Last 24h`; presets include Last 1h, 3h, 6h, 24h, 3d, 7d, plus Custom `from/to` datetime inputs.
- Refresh is manual only; the selected time range is applied to sessions, search, and trace detail requests.
- Responsive: desktop-first three columns; narrower screens stack panels.

## API integration points

Same-origin frontend routes:

```text
GET /api/status              -> http://127.0.0.1:8090/api/status   (legacy status API, retained)
GET /api/sessions?limit=100&from=<iso>&to=<iso>  -> http://127.0.0.1:8091/sessions?limit=100&from=<iso>&to=<iso>
GET /api/search?session_id=X&from=<iso>&to=<iso> -> http://127.0.0.1:8091/search?session_id=X&from=<iso>&to=<iso>
GET /api/traces/{trace_id}?from=<iso>&to=<iso>   -> http://127.0.0.1:8091/traces/{trace_id}?from=<iso>&to=<iso>
```

Backend API contract:

```text
GET /sessions?limit=100&from={iso}&to={iso}
Response: { sessions: [{ session_id, agent_name, started_at, ended_at, duration_ms, trace_count, observation_count, error_count, input_tokens, output_tokens, total_tokens, updated_at }] }

GET /search?session_id={session_id}&from={iso}&to={iso}
Response: { traces: [{ trace_id, session_id, root_span_name, agent_name, started_at, duration_ms, observation_count, error_count, total_tokens, status_code, updated_at }] }

GET /traces/{trace_id}?from={iso}&to={iso}
Response: { trace: {...}, observations: [{ trace_id, span_id, parent_span_id, session_id, observation_type, name, kind, started_at, duration_ms, status_code, status_message, agent_name, model_provider, model_name, input_tokens, output_tokens, total_tokens, input_preview, output_preview, tool_name, tool_input_preview, tool_output_preview, attributes, resource_attributes, source, ingested_at }] }
```

Proxy configuration env vars:

```bash
MISSION_CONTROL_BACKEND_HOST=127.0.0.1
MISSION_CONTROL_BACKEND_PORT=8090
AGENT_OBSERVABILITY_BACKEND_HOST=127.0.0.1
AGENT_OBSERVABILITY_BACKEND_PORT=8091
```

Remote access only needs port `8088` open. Port `8091` can stay private/local to the machine when using the same-origin proxy.

## Implementation steps

1. Start backend-api first:

```bash
cd /home/admin/workspace/agent-mission-control/backend-api
CLICKHOUSE_URL='http://127.0.0.1:8123/?database=agent_observability' python3 backend_api.py --host 0.0.0.0 --port 8091
```

2. Start frontend proxy/static server:

```bash
cd /home/admin/workspace/agent-mission-control
python3 server.py --host 0.0.0.0 --port 8088
```

3. Open:

```text
http://127.0.0.1:8088
```

4. Validate same-origin APIs with explicit time filtering:

```bash
curl http://127.0.0.1:8088/health
FROM=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)
TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl "http://127.0.0.1:8088/api/sessions?limit=100&from=$FROM&to=$TO"
curl "http://127.0.0.1:8088/api/search?session_id=smoke-session-david-20260615-1026&from=$FROM&to=$TO"
curl "http://127.0.0.1:8088/api/traces/<trace_id>?from=$FROM&to=$TO"
```

## Acceptance checklist

- First screen clearly reads as `Agent Observability Console`, not a generic CRUD table.
- Dark theme uses `#08090a` background, `#0f1011/#15171a` panels, subtle borders, violet accent `#7170ff`.
- Session -> traces -> observation timeline drilldown works.
- `/api/sessions`, `/api/search`, `/api/traces/<trace_id>` remain same-origin and functional.
- All three data requests include `from` and `to` query params from the selected time range.
- Default `Last 24h` and Custom datetime range both reload sessions and clear out-of-range selections.
- `attributes` and `resource_attributes` are available in collapsible `<details>` JSON blocks.
- Search/filter/copy interactions are available with non-blocking clipboard fallback.
- Loading, empty, and API fallback/error states render as product UI.
- There is no automatic refresh loop; users refresh manually and keep the active time range.

## Backend API: OTel ingest + query APIs

The MVP backend API is stdlib Python only and listens on `0.0.0.0:8091`.
It supports OTLP HTTP JSON trace ingest only; protobuf is intentionally out of scope for this MVP.

Endpoints:

```text
GET  /health
POST /ingest/otel/v1/traces
POST /v1/traces                         OTLP HTTP JSON alias
GET  /sessions?limit=100&from={iso}&to={iso}
GET  /traces/{trace_id}?from={iso}&to={iso}
GET  /search?session_id={session_id}&from={iso}&to={iso}
```

Run smoke ingest:

```bash
cd /home/admin/workspace/agent-mission-control
./backend-api/smoke_ingest.sh
```

## ClickHouse MVP schema

14-day MVP keeps ClickHouse storage intentionally simple. There are only three core tables in database `agent_observability`:

- `sessions`: session-level aggregate/entry table for session list.
- `traces`: trace-level aggregate/entry table for trace list and search.
- `observations`: span/LLM/tool/event detail table for trace detail.

Schema init file:

```text
clickhouse/init/001_init_schema.sql
```

Start ClickHouse and run smoke test:

```bash
cd /home/admin/workspace/agent-mission-control
docker compose up -d clickhouse
./clickhouse/smoke_test.sh
```

## Fallback mock logic

If `/api/sessions` fails, returns non-2xx, or returns invalid JSON, the page renders `mock-data.js` and shows a visible banner:

```text
API unavailable via same-origin /api/*; showing fallback mock data.
```

The fallback is only for UI usability when the backend is down; real API is used by default.

## Files

```text
index.html                         App shell and three-column Agent Observability Console structure
styles.css                         Dark Linear/Sentry-style dashboard styling and responsive layout
app.js                             API fetch, time range params, filters, copy, render logic, manual refresh
mock-data.js                       Local fallback mock data source
server.py                          Python stdlib static server + /api proxy routes
Dockerfile                         Optional container image for server.py
backend-api/backend_api.py          Stdlib backend API: OTel JSON ingest + query APIs
backend-api/sample_otlp_trace.json  Two-span OTLP JSON fixture
backend-api/smoke_ingest.sh         End-to-end ingest/API smoke test
clickhouse/init/001_init_schema.sql ClickHouse MVP schema
clickhouse/smoke_test.sh            ClickHouse MVP smoke test
README.md                          Usage instructions and acceptance checklist
```
