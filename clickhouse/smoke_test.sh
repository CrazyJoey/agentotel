#!/usr/bin/env bash
set -euo pipefail

DB="${CLICKHOUSE_DB:-agent_observability}"
CONTAINER="${CLICKHOUSE_CONTAINER:-agent-observability-clickhouse}"

# Insert one session, one trace, and two observations; then query all three MVP tables.
docker exec "$CONTAINER" clickhouse-client --database "$DB" --multiquery --query "
TRUNCATE TABLE observations;
TRUNCATE TABLE traces;
TRUNCATE TABLE sessions;

INSERT INTO sessions
(project_id, environment, session_id, user_id, agent_name, started_at, ended_at, duration_ms, trace_count, observation_count, error_count, input_tokens, output_tokens, total_tokens)
VALUES
('proj_demo', 'dev', 'session_smoke_001', 'user_demo', 'demo-agent', toDateTime64('2026-06-15 09:00:00.000', 3, 'UTC'), toDateTime64('2026-06-15 09:00:02.000', 3, 'UTC'), 2000, 1, 2, 1, 10, 20, 30);

INSERT INTO traces
(project_id, environment, trace_id, session_id, root_span_name, agent_name, started_at, ended_at, duration_ms, observation_count, error_count, input_tokens, output_tokens, total_tokens, status_code)
VALUES
('proj_demo', 'dev', 'trace_smoke_001', 'session_smoke_001', 'agent.run', 'demo-agent', toDateTime64('2026-06-15 09:00:00.000', 3, 'UTC'), toDateTime64('2026-06-15 09:00:02.000', 3, 'UTC'), 2000, 2, 1, 10, 20, 30, 'ERROR');

INSERT INTO observations
(project_id, environment, trace_id, span_id, parent_span_id, session_id, observation_type, name, kind, started_at, ended_at, duration_ms, status_code, status_message, agent_name, model_provider, model_name, input_tokens, output_tokens, total_tokens, input_preview, output_preview, tool_name, tool_input_preview, tool_output_preview, attributes, resource_attributes, source)
VALUES
('proj_demo', 'dev', 'trace_smoke_001', 'span_smoke_root', '', 'session_smoke_001', 'llm', 'agent.run', 'INTERNAL', toDateTime64('2026-06-15 09:00:00.000', 3, 'UTC'), toDateTime64('2026-06-15 09:00:01.200', 3, 'UTC'), 1200, 'OK', '', 'demo-agent', 'openai', 'gpt-4o-mini', 10, 20, 30, 'hello', 'world', '', '', '', map('session.id','session_smoke_001','agent.name','demo-agent'), map('service.name','demo-agent-service'), 'smoke-test'),
('proj_demo', 'dev', 'trace_smoke_001', 'span_smoke_tool', 'span_smoke_root', 'session_smoke_001', 'tool', 'tool.search', 'CLIENT', toDateTime64('2026-06-15 09:00:01.200', 3, 'UTC'), toDateTime64('2026-06-15 09:00:02.000', 3, 'UTC'), 800, 'ERROR', 'tool timeout', 'demo-agent', '', '', 0, 0, 0, '', '', 'search', '{\"q\":\"hello\"}', 'timeout', map('error','true'), map('service.name','demo-agent-service'), 'smoke-test');

SELECT 'sessions' AS table_name, project_id, environment, session_id, trace_count, observation_count, error_count, total_tokens
FROM sessions
WHERE session_id='session_smoke_001'
FORMAT TSVWithNames;

SELECT 'traces' AS table_name, project_id, environment, trace_id, session_id, observation_count, error_count, status_code, total_tokens
FROM traces
WHERE trace_id='trace_smoke_001'
FORMAT TSVWithNames;

SELECT 'observations' AS table_name, trace_id, span_id, parent_span_id, observation_type, name, status_code, total_tokens
FROM observations
WHERE trace_id='trace_smoke_001'
ORDER BY started_at, span_id
FORMAT TSVWithNames;
"
