# AgentOTel

Open Agent Observability Platform for AI engineering teams.

## Repository layout

```text
front/                    Console frontend and same-origin proxy on :8088
server/                   Console backend services
  backend-api/            OTLP JSON ingest + query API on :8091
  backend-status-api/     Legacy status API
opentelemetry-collector/  OTel Collector source + AgentOTel local config
clickhouse/               ClickHouse schema and smoke scripts
```

## Local single-server run

### 1. Start ClickHouse and Collector containers

The Collector forwards OTLP traces to the backend API and requires the current AgentOTel API key.

```bash
export AGENTOTEL_API_KEY='<current Agent API Key>'
docker compose up -d clickhouse opentelemetry-collector
```

### 2. Start backend API from source

```bash
cd /home/admin/workspace/agentotel
CLICKHOUSE_DB=agent_observability \
CLICKHOUSE_URL='http://127.0.0.1:8123/?database=agent_observability' \
PROJECT_ID=default ENVIRONMENT=default PYTHONUNBUFFERED=1 \
python3 server/backend-api/backend_api.py --host 0.0.0.0 --port 8091
```

### 3. Start frontend from source

```bash
cd /home/admin/workspace/agentotel
PYTHONUNBUFFERED=1 python3 front/server.py --host 0.0.0.0 --port 8088
```

Open:

```text
http://127.0.0.1:8088
```

## Health checks

```bash
curl -sS http://127.0.0.1:8088/health
curl -sS http://127.0.0.1:8091/health
curl -sS 'http://127.0.0.1:8123/?query=SELECT%201'
curl -i http://127.0.0.1:4318/
```

Expected:

- `8088` returns `OK`
- `8091` returns backend JSON health
- `8123` returns `1`
- `4318` returns HTTP `404` for `/`, which means the Collector HTTP listener is reachable

## Core APIs

```text
POST /v1/traces
POST /ingest/otel/v1/traces
GET  /sessions
GET  /traces/{trace_id}
GET  /search?session_id=...
```

## Security notes

- Do not commit `.env`, API keys, Aliyun credentials, JWT secrets, or Collector Bearer headers.
- `run-backend-aliyun.sh` reads secrets from environment variables only.
- Collector config uses `${env:AGENTOTEL_API_KEY}`.
