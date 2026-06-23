package agentotelclickhouseexporter

import (
	"testing"

	"github.com/stretchr/testify/require"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

func TestBuildRowsCreatesObservationTraceAndSessionRows(t *testing.T) {
	td := ptrace.NewTraces()
	rs := td.ResourceSpans().AppendEmpty()
	rs.Resource().Attributes().PutStr("service.name", "cto")
	span := rs.ScopeSpans().AppendEmpty().Spans().AppendEmpty()
	span.SetName("tool.call")
	span.SetTraceID([16]byte{1, 2, 3})
	span.SetSpanID([8]byte{4, 5, 6})
	span.SetStartTimestamp(pcommon.Timestamp(1000000000))
	span.SetEndTimestamp(pcommon.Timestamp(2000000000))
	span.Attributes().PutStr("session.id", "s1")
	span.Attributes().PutStr("agent.name", "cto")
	span.Attributes().PutStr("tool.name", "terminal")
	span.Attributes().PutInt("llm.usage.input_tokens", 3)
	span.Attributes().PutInt("llm.usage.output_tokens", 4)

	obs, traces, sessions := buildRows(td, Config{ProjectID: "p1", Environment: "dev"})

	require.Len(t, obs, 1)
	require.Len(t, traces, 1)
	require.Len(t, sessions, 1)
	require.Equal(t, "p1", obs[0].ProjectID)
	require.Equal(t, "dev", obs[0].Environment)
	require.Equal(t, "s1", obs[0].SessionID)
	require.Equal(t, "tool", obs[0].ObservationType)
	require.Equal(t, "terminal", obs[0].ToolName)
	require.Equal(t, uint32(7), traces[0].TotalTokens)
	require.Equal(t, uint32(1), sessions[0].TraceCount)
}
