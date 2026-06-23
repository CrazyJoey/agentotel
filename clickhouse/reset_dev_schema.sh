#!/usr/bin/env bash
set -euo pipefail

# Destructive dev-only schema reset. This project is still in development and has no
# production migration burden yet.
DB="${CLICKHOUSE_DB:-agent_observability}"
CONTAINER="${CLICKHOUSE_CONTAINER:-agent-observability-clickhouse}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cat <<'MSG'
[reset_dev_schema] WARNING: destructive dev reset.
Dropping old lf_* objects and recreating MVP tables: sessions, traces, observations.
MSG

docker exec -i "$CONTAINER" clickhouse-client --multiquery < "$ROOT_DIR/clickhouse/init/001_init_schema.sql"

echo "[reset_dev_schema] tables in $DB:"
docker exec "$CONTAINER" clickhouse-client --database "$DB" --query "SHOW TABLES" | sort
