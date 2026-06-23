CREATE DATABASE IF NOT EXISTS agent_observability;
USE agent_observability;

-- Dev-stage cleanup: no migration burden yet. Remove the earlier over-designed Langfuse-like objects.
DROP VIEW IF EXISTS v_lf_sessions;
DROP VIEW IF EXISTS v_lf_traces;
DROP TABLE IF EXISTS lf_scores;
DROP TABLE IF EXISTS lf_observations;

CREATE TABLE IF NOT EXISTS sessions (
  project_id LowCardinality(String) DEFAULT 'default',
  environment LowCardinality(String) DEFAULT 'default',
  session_id String,
  user_id String DEFAULT '',
  agent_name LowCardinality(String) DEFAULT '',
  started_at DateTime64(3, 'UTC'),
  ended_at DateTime64(3, 'UTC'),
  duration_ms UInt64 DEFAULT 0,
  trace_count UInt32 DEFAULT 0,
  observation_count UInt32 DEFAULT 0,
  error_count UInt32 DEFAULT 0,
  input_tokens UInt32 DEFAULT 0,
  output_tokens UInt32 DEFAULT 0,
  total_tokens UInt32 DEFAULT 0,
  created_at DateTime64(3, 'UTC') DEFAULT now64(3),
  updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = MergeTree
PARTITION BY toDate(started_at)
ORDER BY (project_id, environment, session_id);

CREATE TABLE IF NOT EXISTS traces (
  project_id LowCardinality(String) DEFAULT 'default',
  environment LowCardinality(String) DEFAULT 'default',
  trace_id String,
  session_id String DEFAULT '',
  root_span_name String DEFAULT '',
  agent_name LowCardinality(String) DEFAULT '',
  started_at DateTime64(3, 'UTC'),
  ended_at DateTime64(3, 'UTC'),
  duration_ms UInt64 DEFAULT 0,
  observation_count UInt32 DEFAULT 0,
  error_count UInt32 DEFAULT 0,
  input_tokens UInt32 DEFAULT 0,
  output_tokens UInt32 DEFAULT 0,
  total_tokens UInt32 DEFAULT 0,
  status_code LowCardinality(String) DEFAULT 'UNSET',
  created_at DateTime64(3, 'UTC') DEFAULT now64(3),
  updated_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = MergeTree
PARTITION BY toDate(started_at)
ORDER BY (project_id, environment, trace_id);

CREATE TABLE IF NOT EXISTS observations (
  project_id LowCardinality(String) DEFAULT 'default',
  environment LowCardinality(String) DEFAULT 'default',
  trace_id String,
  span_id String,
  parent_span_id String DEFAULT '',
  session_id String DEFAULT '',
  observation_type LowCardinality(String) DEFAULT 'span',
  name String,
  kind LowCardinality(String) DEFAULT 'INTERNAL',
  started_at DateTime64(3, 'UTC'),
  ended_at DateTime64(3, 'UTC'),
  duration_ms UInt64 DEFAULT 0,
  status_code LowCardinality(String) DEFAULT 'UNSET',
  status_message String DEFAULT '',
  agent_name LowCardinality(String) DEFAULT '',
  model_provider LowCardinality(String) DEFAULT '',
  model_name LowCardinality(String) DEFAULT '',
  input_tokens UInt32 DEFAULT 0,
  output_tokens UInt32 DEFAULT 0,
  total_tokens UInt32 DEFAULT 0,
  input_preview String DEFAULT '',
  output_preview String DEFAULT '',
  tool_name String DEFAULT '',
  tool_input_preview String DEFAULT '',
  tool_output_preview String DEFAULT '',
  attributes Map(String, String),
  resource_attributes Map(String, String),
  source LowCardinality(String) DEFAULT 'otel',
  ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = MergeTree
PARTITION BY toDate(started_at)
ORDER BY (project_id, environment, trace_id, started_at, span_id);
