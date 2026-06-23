package agentotelprocessor

import (
	"testing"

	"github.com/stretchr/testify/require"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

func TestNormalizeTracesAddsAgentOTelCompatibilityAttributes(t *testing.T) {
	td := ptrace.NewTraces()
	rs := td.ResourceSpans().AppendEmpty()
	rs.Resource().Attributes().PutStr("service.name", "cto")
	span := rs.ScopeSpans().AppendEmpty().Spans().AppendEmpty()
	span.SetName("llm.call")
	span.SetTraceID([16]byte{1, 2, 3})
	span.SetSpanID([8]byte{4, 5, 6})
	span.SetStartTimestamp(pcommon.Timestamp(1000000000))
	span.SetEndTimestamp(pcommon.Timestamp(1500000000))
	span.Attributes().PutStr("session.id", "s1")
	span.Attributes().PutStr("gen_ai.request.model", "gpt-4.1")
	span.Attributes().PutInt("gen_ai.usage.input_tokens", 12)
	span.Attributes().PutInt("gen_ai.usage.output_tokens", 7)

	NormalizeTraces(td, Config{DefaultAgentName: "fallback"})
	attrs := span.Attributes()

	require.Equal(t, "cto", mustString(attrs, "agent.name"))
	require.Equal(t, "gpt-4.1", mustString(attrs, "llm.model"))
	require.Equal(t, int64(12), mustInt(attrs, "llm.usage.input_tokens"))
	require.Equal(t, int64(7), mustInt(attrs, "llm.usage.output_tokens"))
	require.Equal(t, int64(19), mustInt(attrs, "llm.usage.total_tokens"))
	require.Equal(t, "llm", mustString(attrs, "agentotel.observation_type"))
}

func mustString(attrs pcommon.Map, key string) string {
	v, ok := attrs.Get(key)
	if !ok {
		return ""
	}
	return v.Str()
}

func mustInt(attrs pcommon.Map, key string) int64 {
	v, ok := attrs.Get(key)
	if !ok {
		return 0
	}
	return v.Int()
}
