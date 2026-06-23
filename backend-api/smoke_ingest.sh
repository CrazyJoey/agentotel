#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8091}"
DB="${CLICKHOUSE_DB:-agent_observability}"
CONTAINER="${CLICKHOUSE_CONTAINER:-agent-observability-clickhouse}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACE_ID="trace_ingest_smoke_001"
SESSION_ID="session_ingest_smoke_001"
PAST_FROM="2026-06-15T00:00:00Z"
PAST_TO="2026-06-16T00:00:00Z"
OBS_FROM="2026-06-15T05:06:41Z"
FUTURE_FROM="2999-01-01T00:00:00Z"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

printf 'health:\n'
curl -fsS "$API_BASE/health"
printf '\n\ningest:\n'
curl -fsS -X POST "$API_BASE/ingest/otel/v1/traces" \
  -H 'Content-Type: application/json' \
  --data-binary "@$DIR/sample_otlp_trace.json"
printf '\n\nsessions API:\n'
curl -fsS "$API_BASE/sessions?limit=5"
printf '\n\nsessions API with matching time range:\n'
curl -fsS "$API_BASE/sessions?from=$PAST_FROM&to=$PAST_TO&limit=5" | tee "$TMP_DIR/sessions_past.json"
python3 - "$TMP_DIR/sessions_past.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload["meta"]["from"] == "2026-06-15T00:00:00Z"
assert payload["meta"]["to"] == "2026-06-16T00:00:00Z"
assert payload["meta"]["limit"] == 5
assert payload["sessions"], payload
PY
printf '\n\nsessions API with future range (expect empty):\n'
curl -fsS "$API_BASE/sessions?from=$FUTURE_FROM&limit=5" | tee "$TMP_DIR/sessions_future.json"
python3 - "$TMP_DIR/sessions_future.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload["meta"]["from"] == "2999-01-01T00:00:00Z"
assert payload["sessions"] == [], payload
PY
printf '\n\ntrace API:\n'
curl -fsS "$API_BASE/traces/$TRACE_ID"
printf '\n\ntrace API with observation time range:\n'
curl -fsS "$API_BASE/traces/$TRACE_ID?from=$OBS_FROM&to=$PAST_TO" | tee "$TMP_DIR/trace_range.json"
python3 - "$TMP_DIR/trace_range.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload["trace"]["trace_id"] == "trace_ingest_smoke_001"
assert payload["meta"]["from"] == "2026-06-15T05:06:41Z"
assert payload["observations"], payload
assert all(row["started_at"] >= "2026-06-15 05:06:41" for row in payload["observations"]), payload["observations"]
PY
printf '\n\nsearch API:\n'
curl -fsS "$API_BASE/search?session_id=$SESSION_ID"
printf '\n\nsearch API with matching time range:\n'
curl -fsS "$API_BASE/search?session_id=$SESSION_ID&from=$PAST_FROM&to=$PAST_TO" | tee "$TMP_DIR/search_past.json"
python3 - "$TMP_DIR/search_past.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload["meta"]["from"] == "2026-06-15T00:00:00Z"
assert payload["traces"], payload
PY
printf '\n\nsearch API with future range (expect empty):\n'
curl -fsS "$API_BASE/search?session_id=$SESSION_ID&from=$FUTURE_FROM" | tee "$TMP_DIR/search_future.json"
python3 - "$TMP_DIR/search_future.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
assert payload["traces"] == [], payload
PY
printf '\n\nclickhouse counts:\n'
docker exec "$CONTAINER" clickhouse-client --database "$DB" --query "
SELECT 'observations' AS table_name, count() AS c FROM observations WHERE trace_id='$TRACE_ID'
UNION ALL SELECT 'traces', count() FROM traces WHERE trace_id='$TRACE_ID'
UNION ALL SELECT 'sessions', count() FROM sessions WHERE session_id='$SESSION_ID'
FORMAT TSVWithNames"
