package agentotelclickhouseexporter

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/consumer"
	"go.opentelemetry.io/collector/exporter"
	"go.opentelemetry.io/collector/exporter/exporterhelper"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

var componentType = component.MustNewType("agentotelclickhouse")

type Config struct {
	Endpoint          string `mapstructure:"endpoint"`
	Database          string `mapstructure:"database"`
	ProjectID         string `mapstructure:"project_id"`
	Environment       string `mapstructure:"environment"`
	Username          string `mapstructure:"username"`
	Password          string `mapstructure:"password"`
	ObservationsTable string `mapstructure:"observations_table"`
	TracesTable       string `mapstructure:"traces_table"`
	SessionsTable     string `mapstructure:"sessions_table"`
}

func NewFactory() exporter.Factory {
	return exporter.NewFactory(
		componentType,
		createDefaultConfig,
		exporter.WithTraces(createTraces, component.StabilityLevelDevelopment),
	)
}

func createDefaultConfig() component.Config {
	return &Config{
		Endpoint:          "http://127.0.0.1:8123",
		Database:          "agent_observability",
		ProjectID:         "default",
		Environment:       "default",
		ObservationsTable: "observations",
		TracesTable:       "traces",
		SessionsTable:     "sessions",
	}
}

func createTraces(ctx context.Context, set exporter.Settings, cfg component.Config) (exporter.Traces, error) {
	exp := &clickHouseExporter{cfg: normalizeConfig(*(cfg.(*Config))), client: http.DefaultClient}
	return exporterhelper.NewTraces(ctx, set, cfg, exp.pushTraces,
		exporterhelper.WithCapabilities(consumer.Capabilities{MutatesData: false}))
}

type clickHouseExporter struct {
	cfg    Config
	client *http.Client
}

func normalizeConfig(cfg Config) Config {
	if cfg.Endpoint == "" {
		cfg.Endpoint = "http://127.0.0.1:8123"
	}
	if cfg.Database == "" {
		cfg.Database = "agent_observability"
	}
	if cfg.ProjectID == "" {
		cfg.ProjectID = "default"
	}
	if cfg.Environment == "" {
		cfg.Environment = "default"
	}
	if cfg.ObservationsTable == "" {
		cfg.ObservationsTable = "observations"
	}
	if cfg.TracesTable == "" {
		cfg.TracesTable = "traces"
	}
	if cfg.SessionsTable == "" {
		cfg.SessionsTable = "sessions"
	}
	return cfg
}

func (e *clickHouseExporter) pushTraces(ctx context.Context, td ptrace.Traces) error {
	obs, traces, sessions := buildRows(td, e.cfg)
	if err := e.insert(ctx, e.cfg.ObservationsTable, observationColumns, obs); err != nil {
		return err
	}
	if err := e.insert(ctx, e.cfg.TracesTable, traceColumns, traces); err != nil {
		return err
	}
	return e.insert(ctx, e.cfg.SessionsTable, sessionColumns, sessions)
}

func (e *clickHouseExporter) insert(ctx context.Context, table string, columns []string, rows any) error {
	body, count, err := jsonEachRow(rows)
	if err != nil {
		return err
	}
	if count == 0 {
		return nil
	}
	endpoint, err := url.Parse(e.cfg.Endpoint)
	if err != nil {
		return err
	}
	q := endpoint.Query()
	q.Set("database", e.cfg.Database)
	q.Set("query", fmt.Sprintf("INSERT INTO %s (%s) FORMAT JSONEachRow", table, strings.Join(columns, ",")))
	endpoint.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint.String(), bytes.NewReader(body))
	if err != nil {
		return err
	}
	if e.cfg.Username != "" {
		req.SetBasicAuth(e.cfg.Username, e.cfg.Password)
	}
	resp, err := e.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("clickhouse insert %s failed: %s", table, resp.Status)
	}
	return nil
}

func jsonEachRow(rows any) ([]byte, int, error) {
	var buf bytes.Buffer
	count := 0
	switch r := rows.(type) {
	case []observationRow:
		for _, row := range r {
			b, err := json.Marshal(row)
			if err != nil {
				return nil, count, err
			}
			buf.Write(b)
			buf.WriteByte('\n')
			count++
		}
	case []traceRow:
		for _, row := range r {
			b, err := json.Marshal(row)
			if err != nil {
				return nil, count, err
			}
			buf.Write(b)
			buf.WriteByte('\n')
			count++
		}
	case []sessionRow:
		for _, row := range r {
			b, err := json.Marshal(row)
			if err != nil {
				return nil, count, err
			}
			buf.Write(b)
			buf.WriteByte('\n')
			count++
		}
	default:
		return nil, 0, fmt.Errorf("unsupported rows type %T", rows)
	}
	return buf.Bytes(), count, nil
}

type observationRow struct {
	ProjectID          string            `json:"project_id"`
	Environment        string            `json:"environment"`
	TraceID            string            `json:"trace_id"`
	SpanID             string            `json:"span_id"`
	ParentSpanID       string            `json:"parent_span_id"`
	SessionID          string            `json:"session_id"`
	ObservationType    string            `json:"observation_type"`
	Name               string            `json:"name"`
	Kind               string            `json:"kind"`
	StartedAt          string            `json:"started_at"`
	EndedAt            string            `json:"ended_at"`
	DurationMS         uint64            `json:"duration_ms"`
	StatusCode         string            `json:"status_code"`
	StatusMessage      string            `json:"status_message"`
	AgentName          string            `json:"agent_name"`
	ModelProvider      string            `json:"model_provider"`
	ModelName          string            `json:"model_name"`
	InputTokens        uint32            `json:"input_tokens"`
	OutputTokens       uint32            `json:"output_tokens"`
	TotalTokens        uint32            `json:"total_tokens"`
	InputPreview       string            `json:"input_preview"`
	OutputPreview      string            `json:"output_preview"`
	ToolName           string            `json:"tool_name"`
	ToolInputPreview   string            `json:"tool_input_preview"`
	ToolOutputPreview  string            `json:"tool_output_preview"`
	Attributes         map[string]string `json:"attributes"`
	ResourceAttributes map[string]string `json:"resource_attributes"`
	Source             string            `json:"source"`
}

type traceRow struct {
	ProjectID        string `json:"project_id"`
	Environment      string `json:"environment"`
	TraceID          string `json:"trace_id"`
	SessionID        string `json:"session_id"`
	RootSpanName     string `json:"root_span_name"`
	AgentName        string `json:"agent_name"`
	StartedAt        string `json:"started_at"`
	EndedAt          string `json:"ended_at"`
	DurationMS       uint64 `json:"duration_ms"`
	ObservationCount uint32 `json:"observation_count"`
	ErrorCount       uint32 `json:"error_count"`
	InputTokens      uint32 `json:"input_tokens"`
	OutputTokens     uint32 `json:"output_tokens"`
	TotalTokens      uint32 `json:"total_tokens"`
	StatusCode       string `json:"status_code"`
}

type sessionRow struct {
	ProjectID        string `json:"project_id"`
	Environment      string `json:"environment"`
	SessionID        string `json:"session_id"`
	UserID           string `json:"user_id"`
	AgentName        string `json:"agent_name"`
	StartedAt        string `json:"started_at"`
	EndedAt          string `json:"ended_at"`
	DurationMS       uint64 `json:"duration_ms"`
	TraceCount       uint32 `json:"trace_count"`
	ObservationCount uint32 `json:"observation_count"`
	ErrorCount       uint32 `json:"error_count"`
	InputTokens      uint32 `json:"input_tokens"`
	OutputTokens     uint32 `json:"output_tokens"`
	TotalTokens      uint32 `json:"total_tokens"`
}

var observationColumns = []string{"project_id", "environment", "trace_id", "span_id", "parent_span_id", "session_id", "observation_type", "name", "kind", "started_at", "ended_at", "duration_ms", "status_code", "status_message", "agent_name", "model_provider", "model_name", "input_tokens", "output_tokens", "total_tokens", "input_preview", "output_preview", "tool_name", "tool_input_preview", "tool_output_preview", "attributes", "resource_attributes", "source"}
var traceColumns = []string{"project_id", "environment", "trace_id", "session_id", "root_span_name", "agent_name", "started_at", "ended_at", "duration_ms", "observation_count", "error_count", "input_tokens", "output_tokens", "total_tokens", "status_code"}
var sessionColumns = []string{"project_id", "environment", "session_id", "user_id", "agent_name", "started_at", "ended_at", "duration_ms", "trace_count", "observation_count", "error_count", "input_tokens", "output_tokens", "total_tokens"}

func buildRows(td ptrace.Traces, cfg Config) ([]observationRow, []traceRow, []sessionRow) {
	cfg = normalizeConfig(cfg)
	var obs []observationRow
	for i := 0; i < td.ResourceSpans().Len(); i++ {
		rs := td.ResourceSpans().At(i)
		resourceAttrs := mapFromAttrs(rs.Resource().Attributes())
		serviceName := resourceAttrs["service.name"]
		for j := 0; j < rs.ScopeSpans().Len(); j++ {
			spans := rs.ScopeSpans().At(j).Spans()
			for k := 0; k < spans.Len(); k++ {
				span := spans.At(k)
				attrs := mapFromAttrs(span.Attributes())
				traceID, spanID := span.TraceID().String(), span.SpanID().String()
				if traceID == "" || spanID == "" {
					continue
				}
				in, out := uint32From(attrs, "llm.usage.input_tokens"), uint32From(attrs, "llm.usage.output_tokens")
				total := uint32From(attrs, "llm.usage.total_tokens")
				if total == 0 {
					total = in + out
				}
				agent := firstNonEmpty(attrs["agent.name"], serviceName)
				status, msg := statusFromSpan(span.Status())
				start, end := span.StartTimestamp(), span.EndTimestamp()
				if end == 0 {
					end = start
				}
				obs = append(obs, observationRow{ProjectID: cfg.ProjectID, Environment: cfg.Environment, TraceID: traceID, SpanID: spanID, ParentSpanID: span.ParentSpanID().String(), SessionID: attrs["session.id"], ObservationType: inferObservationType(attrs), Name: span.Name(), Kind: span.Kind().String(), StartedAt: ts(start), EndedAt: ts(end), DurationMS: durationMS(start, end), StatusCode: status, StatusMessage: msg, AgentName: agent, ModelProvider: firstNonEmpty(attrs["llm.provider"], attrs["gen_ai.system"]), ModelName: firstNonEmpty(attrs["llm.model"], attrs["gen_ai.request.model"], attrs["model.name"]), InputTokens: in, OutputTokens: out, TotalTokens: total, InputPreview: attrs["input_preview"], OutputPreview: attrs["output_preview"], ToolName: attrs["tool.name"], ToolInputPreview: attrs["tool_input_preview"], ToolOutputPreview: attrs["tool_output_preview"], Attributes: attrs, ResourceAttributes: resourceAttrs, Source: "otel-collector"})
			}
		}
	}
	return obs, aggregateTraces(obs, cfg), aggregateSessions(obs, cfg)
}

func aggregateTraces(obs []observationRow, cfg Config) []traceRow {
	by := map[string][]observationRow{}
	for _, o := range obs {
		by[o.TraceID] = append(by[o.TraceID], o)
	}
	out := make([]traceRow, 0, len(by))
	for id, rows := range by {
		sort.Slice(rows, func(i, j int) bool { return rows[i].StartedAt < rows[j].StartedAt })
		root := rows[0]
		for _, r := range rows {
			if r.ParentSpanID == "" {
				root = r
				break
			}
		}
		tr := traceRow{ProjectID: cfg.ProjectID, Environment: cfg.Environment, TraceID: id, SessionID: firstSession(rows), RootSpanName: root.Name, AgentName: firstAgent(rows), StartedAt: rows[0].StartedAt, EndedAt: maxEnded(rows), ObservationCount: uint32(len(rows))}
		tr.DurationMS = durationFromStrings(tr.StartedAt, tr.EndedAt)
		for _, r := range rows {
			tr.InputTokens += r.InputTokens
			tr.OutputTokens += r.OutputTokens
			tr.TotalTokens += r.TotalTokens
			if r.StatusCode == "ERROR" {
				tr.ErrorCount++
			}
		}
		if tr.ErrorCount > 0 {
			tr.StatusCode = "ERROR"
		} else {
			tr.StatusCode = "UNSET"
		}
		out = append(out, tr)
	}
	return out
}
func aggregateSessions(obs []observationRow, cfg Config) []sessionRow {
	by := map[string][]observationRow{}
	for _, o := range obs {
		if o.SessionID != "" {
			by[o.SessionID] = append(by[o.SessionID], o)
		}
	}
	out := make([]sessionRow, 0, len(by))
	for id, rows := range by {
		sort.Slice(rows, func(i, j int) bool { return rows[i].StartedAt < rows[j].StartedAt })
		sr := sessionRow{ProjectID: cfg.ProjectID, Environment: cfg.Environment, SessionID: id, UserID: firstAttr(rows, "user.id"), AgentName: firstAgent(rows), StartedAt: rows[0].StartedAt, EndedAt: maxEnded(rows), ObservationCount: uint32(len(rows))}
		traces := map[string]struct{}{}
		for _, r := range rows {
			traces[r.TraceID] = struct{}{}
			sr.InputTokens += r.InputTokens
			sr.OutputTokens += r.OutputTokens
			sr.TotalTokens += r.TotalTokens
			if r.StatusCode == "ERROR" {
				sr.ErrorCount++
			}
		}
		sr.TraceCount = uint32(len(traces))
		sr.DurationMS = durationFromStrings(sr.StartedAt, sr.EndedAt)
		out = append(out, sr)
	}
	return out
}

func mapFromAttrs(attrs pcommon.Map) map[string]string {
	m := map[string]string{}
	attrs.Range(func(k string, v pcommon.Value) bool { m[k] = v.AsString(); return true })
	return m
}
func uint32From(m map[string]string, k string) uint32 {
	var n uint32
	_, _ = fmt.Sscan(m[k], &n)
	return n
}
func inferObservationType(attrs map[string]string) string {
	if attrs["agentotel.observation_type"] != "" {
		return attrs["agentotel.observation_type"]
	}
	if attrs["tool.name"] != "" {
		return "tool"
	}
	if attrs["llm.model"] != "" || attrs["gen_ai.request.model"] != "" {
		return "llm"
	}
	return "span"
}
func statusFromSpan(s ptrace.Status) (string, string) {
	switch s.Code() {
	case ptrace.StatusCodeOk:
		return "OK", s.Message()
	case ptrace.StatusCodeError:
		return "ERROR", s.Message()
	default:
		return "UNSET", s.Message()
	}
}
func ts(t pcommon.Timestamp) string {
	return time.Unix(0, int64(t)).UTC().Format("2006-01-02 15:04:05.000")
}
func durationMS(start, end pcommon.Timestamp) uint64 {
	if end < start {
		return 0
	}
	return uint64(end-start) / 1_000_000
}
func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}
func firstSession(rows []observationRow) string {
	for _, r := range rows {
		if r.SessionID != "" {
			return r.SessionID
		}
	}
	return ""
}
func firstAgent(rows []observationRow) string {
	for _, r := range rows {
		if r.AgentName != "" {
			return r.AgentName
		}
	}
	return ""
}
func firstAttr(rows []observationRow, key string) string {
	for _, r := range rows {
		if r.Attributes[key] != "" {
			return r.Attributes[key]
		}
	}
	return ""
}
func maxEnded(rows []observationRow) string {
	out := ""
	for _, r := range rows {
		if r.EndedAt > out {
			out = r.EndedAt
		}
	}
	return out
}
func durationFromStrings(start, end string) uint64 {
	st, e1 := time.Parse("2006-01-02 15:04:05.000", start)
	en, e2 := time.Parse("2006-01-02 15:04:05.000", end)
	if e1 != nil || e2 != nil || en.Before(st) {
		return 0
	}
	return uint64(en.Sub(st).Milliseconds())
}
