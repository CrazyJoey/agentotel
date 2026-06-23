window.AGENT_OBSERVABILITY_MOCK = {
  sessions: [
    {
      session_id: "mock-session-demo-001",
      agent_name: "Demo Agent",
      started_at: "2026-06-15 10:20:00.000",
      ended_at: "2026-06-15 10:20:02.450",
      duration_ms: 2450,
      trace_count: 1,
      observation_count: 3,
      error_count: 0,
      input_tokens: 120,
      output_tokens: 80,
      total_tokens: 200,
      updated_at: "2026-06-15 10:20:02.500"
    }
  ],
  tracesBySession: {
    "mock-session-demo-001": [
      {
        trace_id: "mock-trace-demo-001",
        session_id: "mock-session-demo-001",
        root_span_name: "demo.agent.run",
        agent_name: "Demo Agent",
        started_at: "2026-06-15 10:20:00.000",
        duration_ms: 2450,
        observation_count: 3,
        error_count: 0,
        total_tokens: 200,
        status_code: "OK",
        updated_at: "2026-06-15 10:20:02.500"
      }
    ]
  },
  traceDetails: {
    "mock-trace-demo-001": {
      trace: {
        trace_id: "mock-trace-demo-001",
        session_id: "mock-session-demo-001",
        root_span_name: "demo.agent.run",
        agent_name: "Demo Agent",
        started_at: "2026-06-15 10:20:00.000",
        duration_ms: 2450,
        observation_count: 3,
        error_count: 0,
        total_tokens: 200,
        status_code: "OK",
        updated_at: "2026-06-15 10:20:02.500"
      },
      observations: [
        {
          trace_id: "mock-trace-demo-001",
          span_id: "mock-root-span",
          parent_span_id: "",
          session_id: "mock-session-demo-001",
          observation_type: "span",
          name: "demo.agent.run",
          kind: "INTERNAL",
          started_at: "2026-06-15 10:20:00.000",
          duration_ms: 2450,
          status_code: "OK",
          status_message: "",
          agent_name: "Demo Agent",
          total_tokens: 0,
          input_preview: "User asks the demo agent to inspect a ticket.",
          output_preview: "Agent starts the workflow.",
          source: "mock"
        },
        {
          trace_id: "mock-trace-demo-001",
          span_id: "mock-llm-span",
          parent_span_id: "mock-root-span",
          session_id: "mock-session-demo-001",
          observation_type: "llm",
          name: "llm.chat",
          kind: "CLIENT",
          started_at: "2026-06-15 10:20:00.220",
          duration_ms: 900,
          status_code: "OK",
          agent_name: "Demo Agent",
          model_provider: "mock-provider",
          model_name: "mock-model",
          input_tokens: 120,
          output_tokens: 80,
          total_tokens: 200,
          input_preview: "Summarize the ticket and choose next step.",
          output_preview: "The ticket needs backend verification first.",
          source: "mock"
        },
        {
          trace_id: "mock-trace-demo-001",
          span_id: "mock-tool-span",
          parent_span_id: "mock-root-span",
          session_id: "mock-session-demo-001",
          observation_type: "tool",
          name: "tool.search",
          kind: "CLIENT",
          started_at: "2026-06-15 10:20:01.300",
          duration_ms: 650,
          status_code: "OK",
          agent_name: "Demo Agent",
          total_tokens: 0,
          tool_name: "search_files",
          tool_input_preview: "ticket_id=DEMO-1",
          tool_output_preview: "Found matching backend trace notes.",
          source: "mock"
        }
      ]
    }
  }
};

window.MISSION_CONTROL_DATA = window.AGENT_OBSERVABILITY_MOCK;
