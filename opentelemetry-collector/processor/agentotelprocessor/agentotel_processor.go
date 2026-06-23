package agentotelprocessor

import (
	"context"
	"fmt"

	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/consumer"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.opentelemetry.io/collector/processor"
	"go.opentelemetry.io/collector/processor/processorhelper"
)

var componentType = component.MustNewType("agentotel")

type Config struct {
	DefaultAgentName string `mapstructure:"default_agent_name"`
}

func NewFactory() processor.Factory {
	return processor.NewFactory(
		componentType,
		func() component.Config { return &Config{} },
		processor.WithTraces(createTraces, component.StabilityLevelDevelopment),
	)
}

func createTraces(ctx context.Context, set processor.Settings, cfg component.Config, next consumer.Traces) (processor.Traces, error) {
	c := cfg.(*Config)
	return processorhelper.NewTraces(ctx, set, cfg, next, func(ctx context.Context, td ptrace.Traces) (ptrace.Traces, error) {
		NormalizeTraces(td, *c)
		return td, nil
	}, processorhelper.WithCapabilities(consumer.Capabilities{MutatesData: true}))
}

func NormalizeTraces(td ptrace.Traces, cfg Config) {
	for i := 0; i < td.ResourceSpans().Len(); i++ {
		rs := td.ResourceSpans().At(i)
		resourceAttrs := rs.Resource().Attributes()
		serviceName := stringValue(resourceAttrs, "service.name")
		for j := 0; j < rs.ScopeSpans().Len(); j++ {
			spans := rs.ScopeSpans().At(j).Spans()
			for k := 0; k < spans.Len(); k++ {
				attrs := spans.At(k).Attributes()
				if stringValue(attrs, "agent.name") == "" {
					if serviceName != "" {
						attrs.PutStr("agent.name", serviceName)
					} else if cfg.DefaultAgentName != "" {
						attrs.PutStr("agent.name", cfg.DefaultAgentName)
					}
				}
				copyString(attrs, "gen_ai.request.model", "llm.model")
				copyString(attrs, "gen_ai.response.model", "llm.model")
				copyString(attrs, "gen_ai.system", "llm.provider")
				copyInt(attrs, "gen_ai.usage.input_tokens", "llm.usage.input_tokens")
				copyInt(attrs, "gen_ai.usage.output_tokens", "llm.usage.output_tokens")
				in := intValue(attrs, "llm.usage.input_tokens")
				out := intValue(attrs, "llm.usage.output_tokens")
				if _, ok := attrs.Get("llm.usage.total_tokens"); !ok && (in > 0 || out > 0) {
					attrs.PutInt("llm.usage.total_tokens", in+out)
				}
				if stringValue(attrs, "agentotel.observation_type") == "" {
					attrs.PutStr("agentotel.observation_type", inferObservationType(attrs))
				}
			}
		}
	}
}

func inferObservationType(attrs pcommon.Map) string {
	if stringValue(attrs, "tool.name") != "" {
		return "tool"
	}
	if stringValue(attrs, "llm.model") != "" || stringValue(attrs, "gen_ai.request.model") != "" {
		return "llm"
	}
	return "span"
}

func copyString(attrs pcommon.Map, from, to string) {
	if stringValue(attrs, to) != "" {
		return
	}
	if value := stringValue(attrs, from); value != "" {
		attrs.PutStr(to, value)
	}
}

func copyInt(attrs pcommon.Map, from, to string) {
	if _, ok := attrs.Get(to); ok {
		return
	}
	if value := intValue(attrs, from); value != 0 {
		attrs.PutInt(to, value)
	}
}

func stringValue(attrs pcommon.Map, key string) string {
	v, ok := attrs.Get(key)
	if !ok {
		return ""
	}
	return v.AsString()
}

func intValue(attrs pcommon.Map, key string) int64 {
	v, ok := attrs.Get(key)
	if !ok {
		return 0
	}
	switch v.Type() {
	case pcommon.ValueTypeInt:
		return v.Int()
	case pcommon.ValueTypeDouble:
		return int64(v.Double())
	case pcommon.ValueTypeStr:
		var n int64
		_, _ = fmt.Sscan(v.Str(), &n)
		return n
	default:
		return 0
	}
}
